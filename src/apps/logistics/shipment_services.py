"""Reusable tenant-safe shipment operations for staff and future API/scanner callers.

Business locks follow parcel_services' ordering and serialize membership, lifecycle,
and parcel events within each tenant. Moving a parcel is explicit remove then assign.
"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from apps.businesses.models import Business, BusinessSubscription, BusinessUser

from .models import Parcel, Shipment
from .parcel_services import _key, change_parcel_status, require_parcel_access
from .shipment_policy import (
    ALLOWED_TRANSITIONS,
    ASSIGNABLE_PARCEL_STATUSES,
    ASSIGNABLE_SHIPMENT_STATUSES,
    SHIPMENT_MANAGE_ROLES,
    SHIPMENT_VIEW_ROLES,
)

SHIPMENT_INPUT_FIELDS = ("origin", "destination", "departure_at", "estimated_arrival_at", "notes")


class _ReceiptEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, datetime):
            # Django's default encoder truncates to milliseconds; retry identity
            # must distinguish the full precision accepted by the services.
            return value.isoformat()
        return super().default(value)


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


def _fingerprint(kind, actor, payload):
    return hashlib.sha256(
        json.dumps(
            {"operation": kind, "actor": actor.pk, "payload": payload},
            cls=_ReceiptEncoder,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _replayed(shipment, key, fingerprint):
    receipt = shipment.write_receipts.get(str(key)) if key else None
    if receipt is None:
        return False
    if receipt != fingerprint:
        raise ValidationError(
            "This retry key was already used for a different shipment operation. Reload before retrying."
        )
    return True


def _check_revision(shipment, expected_revision):
    if expected_revision is not None and (
        type(expected_revision) is not int or expected_revision != shipment.revision
    ):
        raise ValidationError(
            "The shipment changed after this form was loaded. Reload before saving."
        )


def _save_write(shipment, *, fields, key, fingerprint):
    shipment.revision += 1
    if key:
        shipment.write_receipts = {**shipment.write_receipts, str(key): fingerprint}
    shipment._domain_save(update_fields=[*fields, "revision", "write_receipts", "updated_at"])


@transaction.atomic
def create_shipment(*, business, actor, idempotency_key=None, parcel=None, **fields):
    current = _locked_business(business, actor)
    _input_fields(fields)
    key = _key(idempotency_key)
    existing = (
        Shipment.objects.select_for_update().filter(business=current, idempotency_key=key).first()
        if key
        else None
    )
    item = _parcel(current, parcel) if parcel is not None else None
    shipment = Shipment(business=current, created_by=actor, idempotency_key=key, **fields)
    shipment.full_clean(exclude=["reference", "idempotency_key"])
    fingerprint = _fingerprint(
        "create",
        actor,
        {
            "fields": {name: getattr(shipment, name) for name in SHIPMENT_INPUT_FIELDS},
            "parcel": item.pk if item else None,
        },
    )
    if existing:
        if not _replayed(existing, key, fingerprint):
            raise ValidationError(
                "Shipment retry authorization is unavailable. Reload before retrying."
            )
        return existing
    if key:
        shipment.write_receipts = {str(key): fingerprint}
    shipment._domain_save(force_insert=True)
    if item:
        assign_parcel(business=current, shipment=shipment, parcel=item, actor=actor)
        shipment.refresh_from_db()
    return shipment


@transaction.atomic
def update_shipment(
    *,
    business,
    shipment,
    actor,
    expected_revision=None,
    idempotency_key=None,
    parcel=None,
    **fields,
):
    current = _locked_business(business, actor)
    locked = _shipment(current, shipment)
    _input_fields(fields)
    if expected_revision is None:
        expected_revision = getattr(shipment, "revision", None)
    if expected_revision is None:
        raise ValidationError("The loaded shipment revision is required. Reload before saving.")
    key = _key(idempotency_key)
    fields = {
        name: Shipment._meta.get_field(name).clean(value, locked) for name, value in fields.items()
    }
    item = _parcel(current, parcel) if parcel is not None else None
    fingerprint = _fingerprint(
        "edit",
        actor,
        {
            "fields": fields,
            "revision": expected_revision,
            "parcel": item.pk if item else None,
        },
    )
    if _replayed(locked, key, fingerprint):
        return locked
    _check_revision(locked, expected_revision)
    if locked.status != Shipment.Status.DRAFT:
        raise ValidationError("Only draft shipment details can be edited.")
    for name, value in fields.items():
        setattr(locked, name, value)
    _save_write(locked, fields=fields, key=key, fingerprint=fingerprint)
    if item:
        assign_parcel(business=current, shipment=locked, parcel=item, actor=actor)
        locked.refresh_from_db()
    return locked


@transaction.atomic
def assign_parcel(
    *, business, shipment, parcel, actor, idempotency_key=None, expected_revision=None
):
    current = _locked_business(business, actor)
    require_parcel_access(business=current, actor=actor, write=True)
    locked = _shipment(current, shipment)
    item = _parcel(current, parcel)
    key = _key(idempotency_key)
    fingerprint = _fingerprint("assign", actor, {"parcel": item.pk, "revision": expected_revision})
    if _replayed(locked, key, fingerprint):
        return item
    _check_revision(locked, expected_revision)
    _before_departure(locked)
    if item.current_status not in ASSIGNABLE_PARCEL_STATUSES:
        raise ValidationError("Only registered or received parcels can be assigned.")
    if item.shipment_id == locked.pk:
        return item  # A repeated assignment is a harmless no-op, never another membership.
    if item.shipment_id is not None:
        raise ValidationError("Remove the parcel from its current shipment before reassigning it.")
    if locked.charges.exclude(client_id=item.client_id).exists():
        raise ValidationError("A shipment with saved charges must retain a single billing client.")
    item.shipment = locked
    item._domain_save(update_fields=["shipment", "updated_at"])
    _save_write(locked, fields=[], key=key, fingerprint=fingerprint)
    return item


@transaction.atomic
def remove_parcel(
    *, business, shipment, parcel, actor, idempotency_key=None, expected_revision=None
):
    current = _locked_business(business, actor)
    require_parcel_access(business=current, actor=actor, write=True)
    locked = _shipment(current, shipment)
    item = _parcel(current, parcel)
    key = _key(idempotency_key)
    fingerprint = _fingerprint("remove", actor, {"parcel": item.pk, "revision": expected_revision})
    if _replayed(locked, key, fingerprint):
        return item
    _check_revision(locked, expected_revision)
    _before_departure(locked)
    if item.shipment_id != locked.pk:
        raise ValidationError("This parcel is not assigned to this shipment.")
    item.shipment = None
    item._domain_save(update_fields=["shipment", "updated_at"])
    _save_write(locked, fields=[], key=key, fingerprint=fingerprint)
    return item


@transaction.atomic
def change_shipment_status(
    *,
    business,
    shipment,
    actor,
    status,
    expected_status=None,
    expected_revision=None,
    idempotency_key=None,
):
    current = _locked_business(business, actor)
    locked = _shipment(current, shipment)
    key = _key(idempotency_key)
    fingerprint = _fingerprint(
        "status",
        actor,
        {
            "status": status,
            "expected_status": expected_status,
            "revision": expected_revision,
        },
    )
    if _replayed(locked, key, fingerprint):
        return locked
    _check_revision(locked, expected_revision)
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
        # Nested removals advance the same row's revision; preserve their writes.
        locked.refresh_from_db()
    locked.status = status
    _save_write(locked, fields=["status"], key=key, fingerprint=fingerprint)
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
