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

from .location_access import (
    require_creation_site,
    require_record_operation,
    require_route_edit,
    require_work_location,
    scope_records,
)
from .location_reference import ROUTE_LOCATION_FIELDS
from .models import LogisticsLocation, Parcel, Shipment
from .parcel_services import _key, change_parcel_status, require_parcel_access
from .shipment_policy import (
    ALLOWED_TRANSITIONS,
    ASSIGNABLE_PARCEL_STATUSES,
    ASSIGNABLE_SHIPMENT_STATUSES,
    SHIPMENT_MANAGE_ROLES,
    SHIPMENT_VIEW_ROLES,
)
from .shipment_references import (
    SHIPMENT_REFERENCE_FIELDS,
    normalize_reference,
    populated_transport_references,
    validate_shipment_references,
)
from .shipment_transport import validate_shipment_mode

SHIPMENT_INPUT_FIELDS = (
    (
        "origin",
        "destination",
        "transport_mode",
        "departure_at",
        "estimated_arrival_at",
        "notes",
    )
    + SHIPMENT_REFERENCE_FIELDS
    + ROUTE_LOCATION_FIELDS
)


class _ReceiptEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, LogisticsLocation):
            return value.pk
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
    if write:
        require_work_location(current, actor)
    return current


def shipments_for_business(*, business, actor):
    current = require_shipment_access(business=business, actor=actor)
    return scope_records(Shipment.objects.filter(business=current), business=current, actor=actor)


def _locked_business(business, actor, *, write=True, manifest=False):
    current = Business.objects.select_for_update().filter(pk=getattr(business, "pk", None)).first()
    return require_shipment_access(business=current, actor=actor, write=write, manifest=manifest)


def _shipment(current, shipment, actor, *, write=True):
    locked = (
        Shipment.objects.select_for_update()
        .filter(business=current, pk=getattr(shipment, "pk", shipment))
        .first()
    )
    if locked is None:
        raise ValidationError("Shipment is unavailable in this workspace.")
    if write:
        require_record_operation(locked, business=current, actor=actor)
    elif not scope_records(
        Shipment.objects.filter(pk=locked.pk, business=current), business=current, actor=actor
    ).exists():
        raise PermissionDenied("Shipment is unavailable in your assigned locations.")
    return locked


def _parcel(current, parcel, actor):
    locked = (
        Parcel.objects.select_for_update()
        .filter(business=current, client__business=current, pk=getattr(parcel, "pk", parcel))
        .first()
    )
    if locked is None:
        raise ValidationError("Parcel is unavailable in this workspace.")
    require_record_operation(locked, business=current, actor=actor)
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
    shipment._domain_save(
        update_fields=[
            *fields,
            "location_review_required",
            "revision",
            "write_receipts",
            "updated_at",
        ]
    )


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
    item = _parcel(current, parcel, actor) if parcel is not None else None
    shipment = Shipment(business=current, created_by=actor, idempotency_key=key, **fields)
    shipment._route_previous = existing
    if shipment.transport_mode == "":
        shipment.transport_mode = None
    for name in SHIPMENT_REFERENCE_FIELDS:
        setattr(shipment, name, normalize_reference(getattr(shipment, name)))
    require_creation_site(shipment, business=current, actor=actor)
    shipment.full_clean(exclude=["reference", "idempotency_key"])
    fingerprint = _fingerprint(
        "create",
        actor,
        {
            "fields": {
                name: getattr(shipment, name)
                for name in SHIPMENT_INPUT_FIELDS
                if (name not in ROUTE_LOCATION_FIELDS or getattr(shipment, name))
                and (
                    name not in ("transport_mode", *SHIPMENT_REFERENCE_FIELDS)
                    or getattr(shipment, name) is not None
                )
            },
            "parcel": item.pk if item else None,
        },
    )
    if existing:
        if not _replayed(existing, key, fingerprint):
            raise ValidationError(
                "Shipment retry authorization is unavailable. Reload before retrying."
            )
        require_record_operation(existing, business=current, actor=actor)
        return existing
    shipment.transport_mode = validate_shipment_mode(shipment.transport_mode, business=current)
    validate_shipment_references(
        shipment.transport_mode,
        {name: getattr(shipment, name) for name in SHIPMENT_REFERENCE_FIELDS},
    )
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
    locked = _shipment(current, shipment, actor)
    _input_fields(fields)
    if expected_revision is None:
        expected_revision = getattr(shipment, "revision", None)
    if expected_revision is None:
        raise ValidationError("The loaded shipment revision is required. Reload before saving.")
    key = _key(idempotency_key)
    if "transport_mode" in fields:
        if fields["transport_mode"] == "":
            fields["transport_mode"] = None
    for name in SHIPMENT_REFERENCE_FIELDS:
        if name in fields:
            fields[name] = normalize_reference(fields[name])
    cleaned = {}
    for name, value in fields.items():
        field = Shipment._meta.get_field(name)
        if name in ("origin_location", "destination_location"):
            pk = field.clean(getattr(value, "pk", value), locked)
            cleaned[name] = LogisticsLocation.objects.get(pk=pk) if pk else None
        else:
            cleaned[name] = field.clean(value, locked)
    fields = cleaned
    item = _parcel(current, parcel, actor) if parcel is not None else None
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
    if "transport_mode" in fields:
        fields["transport_mode"] = validate_shipment_mode(
            fields["transport_mode"],
            business=current,
            existing=True,
            previous_mode=locked.transport_mode,
        )
    previous = {name: getattr(locked, name) for name in SHIPMENT_REFERENCE_FIELDS}
    validate_shipment_references(
        fields.get("transport_mode", locked.transport_mode),
        {**previous, **fields},
        previous=previous,
    )
    require_route_edit(locked, fields, business=current, actor=actor)
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
    locked = _shipment(current, shipment, actor)
    item = _parcel(current, parcel, actor)
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
    locked = _shipment(current, shipment, actor)
    item = _parcel(current, parcel, actor)
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
    locked = _shipment(current, shipment, actor)
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
    for item in items:
        require_record_operation(item, business=current, actor=actor)
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
    locked = _shipment(current, shipment, actor, write=False)
    items = list(
        Parcel.objects.select_for_update()
        .filter(shipment=locked, business=current, client__business=current)
        .select_related("client")
        .order_by("tracking_code")
    )
    visible_ids = scope_records(
        Parcel.objects.filter(business=current), business=current, actor=actor
    ).values_list("pk", flat=True)
    if (
        Parcel.objects.filter(pk__in=[item.pk for item in items])
        .exclude(pk__in=visible_ids)
        .exists()
    ):
        raise PermissionDenied("A complete manifest requires access to every parcel.")
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
        "transport_mode": locked.transport_mode,
        "transport_mode_label": locked.get_transport_mode_display() or "Unknown",
        "transportation_details": populated_transport_references(locked),
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
