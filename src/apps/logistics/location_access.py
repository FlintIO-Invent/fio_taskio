"""Persisted location policy layered under existing role/subscription guards.

Read helpers return empty querysets during review and for unassigned workers.
All write helpers require an approved operational grant and an active work site.
Call mutation helpers while holding the Business lock, as the existing services do.
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.businesses.models import BusinessUser

from .models import LogisticsLocation, LogisticsLocationAssignment, LogisticsProfile

WIDE_ROLES = (BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN)


def lock_actor_membership(business, actor):
    """Call inside the Business transaction before authorization.

    Team deactivation updates this existing row without taking a Business lock.
    Lock only this tenant's membership so other tenants can operate independently.
    """
    return (
        BusinessUser.objects.order_by("pk")
        .select_for_update(of=("self",))
        .filter(business=business, user_id=getattr(actor, "pk", None))
        .first()
    )


def membership_for(business, actor):
    return BusinessUser.objects.filter(
        business=business, user_id=getattr(actor, "pk", None), is_active=True, user__is_active=True
    ).first()


def has_wide_access(business, actor):
    member = membership_for(business, actor)
    return bool(member and member.role in WIDE_ROLES)


def assignments_for(business, actor):
    member = membership_for(business, actor)
    if (
        not member
        or not LogisticsProfile.objects.filter(
            business=business, location_access_reviewed_at__isnull=False
        ).exists()
    ):
        return LogisticsLocationAssignment.objects.none()
    return LogisticsLocationAssignment.objects.filter(
        business=business,
        membership=member,
        location__business=business,
        location__is_active=True,
        is_work_context=False,
    ).select_related("location")


def locations_for(business, actor):
    locations = LogisticsLocation.objects.filter(business=business, is_active=True)
    if has_wide_access(business, actor):
        return locations
    return locations.filter(pk__in=assignments_for(business, actor).values("location_id"))


def site_filter(location_ids, *, prefix=""):
    return (
        Q(**{f"{prefix}origin_location_id__in": location_ids})
        | Q(**{f"{prefix}destination_location_id__in": location_ids})
        | Q(**{f"{prefix}handling_sites__location_id__in": location_ids})
    )


def scope_records(queryset, *, business, actor, location_ids=None):
    if location_ids is None and has_wide_access(business, actor):
        return queryset
    ids = location_ids if location_ids is not None else locations_for(business, actor).values("pk")
    condition = site_filter(ids)
    # Cargo in a shipment is expected at that shipment's approved handling sites.
    if queryset.model._meta.model_name == "parcel":
        condition |= site_filter(ids, prefix="shipment__") & Q(shipment__business=business)
    # PK subquery avoids duplicate rows and permits select_for_update on PostgreSQL.
    return queryset.filter(pk__in=queryset.filter(condition).values("pk"))


def require_work_location(business, actor):
    if has_wide_access(business, actor):
        return None
    assignment = assignments_for(business, actor).filter(is_current=True, can_operate=True).first()
    if assignment is None:
        raise PermissionDenied(
            "An approved operational assignment and active work location are required."
        )
    return assignment.location


def require_record_operation(record, *, business, actor):
    from .location_operations import operation_location

    operation_location(business, actor)
    location = require_work_location(business, actor)
    if (
        location is not None
        and not scope_records(
            type(record).objects.filter(pk=record.pk, business=business),
            business=business,
            actor=actor,
            location_ids=[location.pk],
        ).exists()
    ):
        raise PermissionDenied("This record is unavailable at your active work location.")


def require_creation_site(record, *, business, actor):
    from .location_operations import operation_location, operations_enabled

    location = require_work_location(business, actor)
    if has_wide_access(business, actor) and operations_enabled(business):
        location = operation_location(business, actor)
    if location is not None:
        if record.origin_location_id != location.pk:
            raise PermissionDenied("The origin facility must be your active work location.")
        if (
            not has_wide_access(business, actor)
            and record.destination_location_id
            and not locations_for(business, actor)
            .filter(pk=record.destination_location_id)
            .exists()
        ):
            raise PermissionDenied("Select an authorized destination facility.")


def require_route_edit(record, fields, *, business, actor):
    if has_wide_access(business, actor):
        return
    for name in ("origin_location", "destination_location"):
        if name in fields and getattr(fields[name], "pk", fields[name]) != getattr(
            record, name + "_id"
        ):
            raise PermissionDenied(
                "Only owners and administrators can change operating-site associations."
            )


def can_operate_record(record, *, business, actor):
    member = membership_for(business, actor)
    if not member or member.role not in (*WIDE_ROLES, BusinessUser.Role.STAFF):
        return False
    try:
        require_record_operation(record, business=business, actor=actor)
    except PermissionDenied:
        return False
    return True
