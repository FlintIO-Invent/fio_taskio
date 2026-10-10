"""Verified work context and action-specific rules, called under the Business lock.

EXPECTED is an explicitly approved next stop, not an inferred geographic route.
STOP grants handling visibility; it does not independently authorize an arrival.
"""

from django.core.exceptions import PermissionDenied, ValidationError

from .location_access import has_wide_access, membership_for, require_work_location
from .models import LogisticsHandlingSite, LogisticsLocationAssignment, LogisticsProfile, Parcel


def operations_enabled(business):
    return LogisticsProfile.objects.filter(
        business=business, location_operations_enabled_at__isnull=False
    ).exists()


def operation_location(business, actor):
    if not has_wide_access(business, actor):
        return require_work_location(business, actor)
    member = membership_for(business, actor)
    context = (
        LogisticsLocationAssignment.objects.filter(
            business=business,
            membership=member,
            is_current=True,
            location__business=business,
            location__is_active=True,
        )
        .select_related("location")
        .first()
    )
    if context:
        return context.location
    if operations_enabled(business):
        raise PermissionDenied("Select an active workspace work location before operating.")
    return None


def _associations(record, kind):
    return record.handling_sites.filter(
        business_id=record.business_id,
        location__business_id=record.business_id,
        kind=kind,
    ).values_list("location_id", flat=True)


def _history(record):
    if isinstance(record, Parcel):
        return list(
            record.events.filter(
                business_id=record.business_id,
                operational_location__isnull=False,
                event_type="STATUS",
            )
            .order_by("timestamp", "pk")
            .values_list("status", "operational_location_id")
        )
    return [
        (entry["new_state"], entry["location_id"])
        for entry in record.operation_history
        if entry.get("action") == "status" and entry.get("location_id")
    ]


def current_site(record):
    # A departure retains its source; notes and administrative edits cannot move cargo.
    handled = [
        (state, site)
        for state, site in _history(record)
        if state not in ("REGISTERED", "IN_TRANSIT", "DRAFT", "CANCELLED")
    ]
    if handled:
        return handled[-1][1]
    sites = set(_associations(record, LogisticsHandlingSite.Kind.CURRENT))
    if len(sites) > 1:
        raise ValidationError("Current handling site is ambiguous; request a route review.")
    source = next(iter(sites), record.origin_location_id)
    if source is None and isinstance(record, Parcel) and record.shipment_id:
        if record.shipment.business_id != record.business_id:
            raise ValidationError("Shipment relationship requires integrity review.")
        return current_site(record.shipment)
    return source


def next_site(record):
    visited = {site for state, site in _history(record) if state == "ARRIVED"}
    expected = set(_associations(record, LogisticsHandlingSite.Kind.EXPECTED)) - visited
    if len(expected) > 1:
        raise ValidationError("Approve exactly one next expected site before arrival.")
    target = next(iter(expected), record.destination_location_id)
    if target is None and isinstance(record, Parcel) and record.shipment_id:
        if record.shipment.business_id != record.business_id:
            raise ValidationError("Shipment relationship requires integrity review.")
        return next_site(record.shipment)
    return target


def validate_transition_location(
    record, *, business, actor, status=None, override_reason="", shipment_context=None
):
    site = operation_location(business, actor)
    reason = (override_reason or "").strip()
    if reason and (len(reason) > 1000 or not has_wide_access(business, actor)):
        raise PermissionDenied("Only owners and administrators can approve a site override.")
    if reason and site is None:
        raise PermissionDenied("A site override requires a selected work location.")
    if site is None:
        return None  # Explicit pre-rollout compatibility; workers never take this path.
    if reason:
        return site  # Tenant, role, active site, subscription and lifecycle still apply.
    if not operations_enabled(business):
        return site  # Preserve existing route rules until the explicit rollout review.
    source = current_site(record)
    if status == "HOLD":
        state = record.current_status if isinstance(record, Parcel) else record.status
        eligible = {source}
        if state == "IN_TRANSIT" and site.pk != source:
            eligible.add(next_site(record))
        if site.pk not in eligible:
            raise PermissionDenied(
                "A hold requires the current site or the approved next transit stop."
            )
    elif status == "ARRIVED":
        target = next_site(record)
        # Shipment arrival is an approved intermediate movement for its cargo.
        if shipment_context is not None:
            target = next_site(shipment_context)
        if target is None or target != site.pk:
            raise PermissionDenied("Arrival requires the approved next operating site.")
    elif status in ("RECEIVED", "IN_TRANSIT", "DRAFT"):
        # Legacy intake can be mapped explicitly to one CURRENT/STOP association.
        if source is None and status == "RECEIVED":
            approved = set(_associations(record, LogisticsHandlingSite.Kind.STOP))
            source = site.pk if approved == {site.pk} else None
        if source is None or source != site.pk:
            raise PermissionDenied(
                "Intake or departure requires the current/origin operating site."
            )
    elif status in ("READY", "DELIVERED", "COMPLETED"):
        if source != site.pk:
            raise PermissionDenied("Readiness and delivery require the current handling site.")
        if status in ("DELIVERED", "COMPLETED"):
            eligible = {record.destination_location_id} | set(
                _associations(record, LogisticsHandlingSite.Kind.STOP)
            )
            if site.pk not in eligible:
                raise PermissionDenied(
                    "Delivery requires a destination or approved handling facility."
                )
    else:
        approved = {record.origin_location_id, record.destination_location_id, source}
        approved |= set(
            record.handling_sites.filter(
                business=business, location__business=business
            ).values_list("location_id", flat=True)
        )
        if site.pk not in approved:
            raise PermissionDenied("Handling requires an approved operational site.")
    return site
