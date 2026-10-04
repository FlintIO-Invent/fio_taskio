"""Reusable tenant-safe shipment operations for staff and future API/scanner callers.

Business locks follow parcel_services' ordering and serialize membership, lifecycle,
and parcel events within each tenant. Moving a parcel is explicit remove then assign.
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.businesses.models import Business, BusinessSubscription, BusinessUser

from .models import Parcel, Shipment
from .parcel_services import change_parcel_status, require_parcel_access
from .shipment_policy import (
    ALLOWED_TRANSITIONS,
    ASSIGNABLE_PARCEL_STATUSES,
    ASSIGNABLE_SHIPMENT_STATUSES,
    SHIPMENT_MANAGE_ROLES,
    SHIPMENT_VIEW_ROLES,
)

SHIPMENT_INPUT_FIELDS = ("origin", "destination", "departure_at", "estimated_arrival_at", "notes")


def require_shipment_access(*, business, actor, write=False, manifest=False):
    current = Business.objects.filter(pk=getattr(business, "pk", None), is_active=True).first()
    if current is None or current.vertical != Business.Vertical.LOGISTICS:
        raise PermissionDenied("Shipment operations require an active Logistics workspace.")
    if not BusinessUser.objects.filter(
        business=current,
        user_id=getattr(actor, "pk", None),
        is_active=True,
        user__is_active=True,
        role__in=SHIPMENT_MANAGE_ROLES if write else SHIPMENT_VIEW_ROLES,
    ).exists():
        raise PermissionDenied("Your workspace role does not permit this shipment operation.")
    subscription = (
        BusinessSubscription.objects.select_related("business", "plan")
        .filter(business=current)
        .first()
    )
    modules = ("shipments", "manifests") if manifest else ("shipments",)
    if not subscription or not all(
        subscription.can_use_module(module) if write else subscription.can_view_module(module)
        for module in modules
    ):
        raise PermissionDenied(
            "Your workspace subscription does not permit this shipment operation."
        )
    return current


def shipments_for_business(*, business, actor):
    return Shipment.objects.filter(business=require_shipment_access(business=business, actor=actor))


def _locked_business(business, actor, *, write=True, manifest=False):
    current = Business.objects.select_for_update().filter(pk=getattr(business, "pk", None)).first()
    return require_shipment_access(business=current, actor=actor, write=write, manifest=manifest)


def _shipment(current, shipment):
    locked = (
        Shipment.objects.select_for_update()
        .filter(business=current, pk=getattr(shipment, "pk", shipment))
        .first()
    )
    if locked is None:
        raise ValidationError("Shipment is unavailable in this workspace.")
    return locked


def _parcel(current, parcel):
    locked = (
        Parcel.objects.select_for_update()
        .filter(business=current, client__business=current, pk=getattr(parcel, "pk", parcel))
        .first()
    )
    if locked is None:
        raise ValidationError("Parcel is unavailable in this workspace.")
    return locked


def _before_departure(shipment):
    if shipment.status not in ASSIGNABLE_SHIPMENT_STATUSES:
        raise ValidationError("Parcel membership can only change before shipment departure.")


def _input_fields(fields):
    if set(fields) - set(SHIPMENT_INPUT_FIELDS):
        raise ValidationError("Unsupported shipment fields.")


@transaction.atomic
def create_shipment(*, business, actor, **fields):
    current = _locked_business(business, actor)
    _input_fields(fields)
    shipment = Shipment(business=current, created_by=actor, **fields)
    shipment._domain_save(force_insert=True)
    return shipment


@transaction.atomic
def update_shipment(*, business, shipment, actor, **fields):
    current = _locked_business(business, actor)
    locked = _shipment(current, shipment)
    _input_fields(fields)
    if locked.status != Shipment.Status.DRAFT:
        raise ValidationError("Only draft shipment details can be edited.")
    for name, value in fields.items():
        setattr(locked, name, value)
    locked._domain_save(update_fields=[*fields, "updated_at"])
    return locked


@transaction.atomic
def assign_parcel(*, business, shipment, parcel, actor):
    current = _locked_business(business, actor)
    require_parcel_access(business=current, actor=actor, write=True)
    locked = _shipment(current, shipment)
    _before_departure(locked)
    item = _parcel(current, parcel)
    if item.current_status not in ASSIGNABLE_PARCEL_STATUSES:
        raise ValidationError("Only registered or received parcels can be assigned.")
    if item.shipment_id == locked.pk:
        return item  # A repeated assignment is a harmless no-op, never another membership.
    if item.shipment_id is not None:
        raise ValidationError("Remove the parcel from its current shipment before reassigning it.")
    item.shipment = locked
    item._domain_save(update_fields=["shipment", "updated_at"])
    return item


@transaction.atomic
def remove_parcel(*, business, shipment, parcel, actor):
    current = _locked_business(business, actor)
    require_parcel_access(business=current, actor=actor, write=True)
    locked = _shipment(current, shipment)
    _before_departure(locked)
    item = _parcel(current, parcel)
    if item.shipment_id != locked.pk:
        raise ValidationError("This parcel is not assigned to this shipment.")
    item.shipment = None
    item._domain_save(update_fields=["shipment", "updated_at"])
    return item


@transaction.atomic
def change_shipment_status(*, business, shipment, actor, status, expected_status=None):
    current = _locked_business(business, actor)
    locked = _shipment(current, shipment)
    if expected_status is not None and expected_status != locked.status:
        raise ValidationError("The shipment status changed. Reload before recording this update.")
    if status not in Shipment.Status.values or status not in ALLOWED_TRANSITIONS[locked.status]:
        raise ValidationError("This shipment status transition is not allowed.")
    # Inspect every member, including corrupt inbound relations; never silently depart
    # with an incomplete tenant-filtered grouping.
    members = Parcel.objects.filter(shipment=locked)
    if (
        members.exclude(business=current).exists()
        or members.exclude(client__business=current).exists()
    ):
        raise ValidationError("Shipment parcel relationships require integrity review.")
    items = list(
        members.select_for_update()
        .filter(business=current, client__business=current)
        .order_by("pk")
    )
    if status in {Shipment.Status.READY, Shipment.Status.IN_TRANSIT}:
        if not items or any(item.current_status != Parcel.Status.RECEIVED for item in items):
            raise ValidationError(
                "Readiness and departure require at least one parcel, all received."
            )
    if status == Shipment.Status.ARRIVED:
        if not items or any(item.current_status != Parcel.Status.IN_TRANSIT for item in items):
            raise ValidationError("Arrival requires all assigned parcels to be in transit.")
    if status == Shipment.Status.COMPLETED:
        if not items or any(item.current_status != Parcel.Status.DELIVERED for item in items):
            raise ValidationError(
                "Complete the shipment only after all assigned parcels are delivered."
            )
    parcel_status = {
        Shipment.Status.IN_TRANSIT: Parcel.Status.IN_TRANSIT,
        Shipment.Status.ARRIVED: Parcel.Status.ARRIVED,
    }.get(status)
    if parcel_status:
        for item in items:
            change_parcel_status(
                business=current,
                parcel=item,
                actor=actor,
                status=parcel_status,
                expected_status=item.current_status,
                public_message=(
                    "Parcel in transit."
                    if status == Shipment.Status.IN_TRANSIT
                    else "Parcel arrived."
                ),
                internal_note=f"Shipment {locked.reference}: {status}",
            )
    if status == Shipment.Status.CANCELLED:
        # Cancellation before departure releases membership without cancelling parcels.
        for item in items:
            remove_parcel(business=current, shipment=locked, parcel=item, actor=actor)
    locked.status = status
    locked._domain_save(update_fields=["status", "updated_at"])
    return locked


@transaction.atomic
def generate_manifest(*, business, shipment, actor):
    """Current operational snapshot; explicit allowlist excludes client contact/private data."""
    current = _locked_business(business, actor, write=False, manifest=True)
    locked = _shipment(current, shipment)
    items = list(
        Parcel.objects.select_for_update()
        .filter(shipment=locked, business=current, client__business=current)
        .select_related("client")
        .order_by("tracking_code")
    )
    rows = [
        {
            "tracking_code": item.tracking_code,
            "client_name": f"{item.client.first_name} {item.client.last_name}".strip(),
            "package_description": item.package_description,
            "quantity": item.quantity,
            "weight_kg": item.weight_kg,
        }
        for item in items
    ]
    return {
        "reference": locked.reference,
        "origin": locked.origin,
        "destination": locked.destination,
        "departure_at": locked.departure_at,
        "estimated_arrival_at": locked.estimated_arrival_at,
        "parcels": rows,
        "parcel_count": len(rows),
        "total_quantity": sum(row["quantity"] for row in rows),
        "total_known_weight_kg": sum(
            (row["weight_kg"] for row in rows if row["weight_kg"] is not None), Decimal("0")
        ),
        "unknown_weight_count": sum(row["weight_kg"] is None for row in rows),
    }
