"""Owner-approved grants, work-site selection and explicit handling associations."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.businesses.models import Business, BusinessUser

from .location_access import (
    WIDE_ROLES,
    assignments_for,
    has_wide_access,
    lock_actor_membership,
    membership_for,
)
from .models import (
    LogisticsHandlingSite,
    LogisticsLocation,
    LogisticsLocationAssignment,
    LogisticsProfile,
    Parcel,
    Shipment,
)
from .parcel_services import require_parcel_access


def _business(business, actor, *, manage=False):
    current = Business.objects.select_for_update().filter(pk=getattr(business, "pk", None)).first()
    lock_actor_membership(current, actor)
    current = require_parcel_access(business=current, actor=actor, write=manage)
    if manage and not has_wide_access(current, actor):
        raise PermissionDenied("Only owners and administrators can manage Logistics access.")
    return current


@transaction.atomic
def set_location_assignment(
    *, business, actor, membership, location, can_operate=False, revoke=False
):
    current = _business(business, actor, manage=True)
    member = (
        BusinessUser.objects.filter(
            pk=getattr(membership, "pk", membership),
            business=current,
        )
        .select_related("user")
        .first()
    )
    site = LogisticsLocation.objects.filter(
        pk=getattr(location, "pk", location), business=current
    ).first()
    if not member or not site or (member.role in WIDE_ROLES and not revoke):
        raise ValidationError(
            "Select an active non-administrator membership and a workspace location."
        )
    existing = LogisticsLocationAssignment.objects.filter(
        business=current, membership=member, location=site
    )
    if revoke:
        existing.delete()
        return None
    if not member.is_active or not member.user.is_active:
        raise ValidationError("Only active memberships can receive location access.")
    if not site.is_active:
        raise ValidationError("Inactive locations cannot receive new assignments.")
    if can_operate and member.role != BusinessUser.Role.STAFF:
        raise ValidationError("Only the existing staff role may receive operational permission.")
    item = existing.first() or LogisticsLocationAssignment(
        business=current, membership=member, location=site
    )
    item.can_operate = can_operate
    item.is_work_context = False
    if not LogisticsLocationAssignment.objects.filter(membership=member, is_current=True).exists():
        item.is_current = True
    item.save()
    return item


@transaction.atomic
def review_location_access(*, business, actor):
    current = _business(business, actor, manage=True)
    profile, _ = LogisticsProfile.objects.get_or_create(business=current)
    profile.location_access_reviewed_at = timezone.now()
    profile.save(update_fields=["location_access_reviewed_at"])
    return profile


@transaction.atomic
def select_work_location(*, business, actor, location):
    current = _business(business, actor)
    try:
        location_id = int(getattr(location, "pk", location))
    except (ValueError, TypeError) as exc:
        raise PermissionDenied("Select an authorized work location.") from exc
    if has_wide_access(current, actor):
        site = LogisticsLocation.objects.filter(
            business=current, pk=location_id, is_active=True
        ).first()
        if site is None:
            raise PermissionDenied("Select an active workspace location.")
        member = membership_for(current, actor)
        selected = LogisticsLocationAssignment.objects.filter(
            business=current, membership=member, location=site
        ).first() or LogisticsLocationAssignment(business=current, membership=member, location=site)
        selected.is_work_context = True
        selected.can_operate = False  # Context is not a grant if this administrator is demoted.
    else:
        selected = assignments_for(current, actor).filter(location_id=location_id).first()
    if selected is None:
        raise PermissionDenied("Select one of your active, reviewed location assignments.")
    LogisticsLocationAssignment.objects.filter(membership=selected.membership).update(
        is_current=False
    )
    selected.is_current = True
    selected.save()
    return selected.location


@transaction.atomic
def enable_location_operations(*, business, actor):
    """Irreversible through ordinary UI: never quietly disable an operational guard."""
    current = _business(business, actor, manage=True)
    profile = LogisticsProfile.objects.filter(business=current).first()
    if not profile or not profile.location_access_reviewed_at:
        raise ValidationError("Review worker assignments and route mappings first.")
    if not LogisticsLocation.objects.filter(business=current, is_active=True).exists():
        raise ValidationError("Register active operating facilities before enabling verification.")
    from .location_operations import operation_location

    if operation_location(current, actor) is None:
        raise ValidationError("Select your work location before enabling verification.")
    if not profile.location_operations_enabled_at:
        profile.location_operations_enabled_at = timezone.now()
        profile.save(update_fields=["location_operations_enabled_at"])
    return profile


@transaction.atomic
def set_handling_site(*, business, actor, location, parcel=None, shipment=None, kind, remove=False):
    current = _business(business, actor, manage=True)
    if bool(parcel is not None) == bool(shipment is not None):
        raise ValidationError("Select exactly one parcel or shipment.")
    model, target = (Parcel, parcel) if parcel is not None else (Shipment, shipment)
    if model is Shipment:
        from .shipment_services import require_shipment_access

        require_shipment_access(business=current, actor=actor, write=True)
    target = (
        model.objects.select_for_update()
        .filter(business=current, pk=getattr(target, "pk", target))
        .first()
    )
    site = LogisticsLocation.objects.filter(
        business=current, pk=getattr(location, "pk", location)
    ).first()
    if target is None or site is None or kind not in LogisticsHandlingSite.Kind.values:
        raise ValidationError("Select a workspace target, site and association type.")
    if isinstance(target, Parcel) and target.client.business_id != current.pk:
        raise ValidationError("Parcel client requires integrity review.")
    fields = {"parcel" if model is Parcel else "shipment": target}
    existing = LogisticsHandlingSite.objects.filter(
        business=current, location=site, kind=kind, **fields
    )
    if remove:
        existing.delete()
        return None
    if not site.is_active:
        raise ValidationError("Select an active handling site.")
    item = existing.first() or LogisticsHandlingSite(
        business=current, location=site, kind=kind, **fields
    )
    item.save()
    return item
