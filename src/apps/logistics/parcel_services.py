"""UI-independent parcel operations. All mutations and history writes are atomic."""

import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.businesses.models import Business, BusinessSubscription, BusinessUser
from apps.crm.models import Client

from .models import Parcel, ParcelEvent, generate_tracking_code
from .parcel_policy import ALLOWED_TRANSITIONS, PARCEL_MANAGE_ROLES, PARCEL_VIEW_ROLES

PARCEL_INPUT_FIELDS = (
    "internal_reference",
    "origin",
    "destination",
    "package_description",
    "quantity",
    "weight_kg",
    "dimensions",
    "declared_value",
    "hs_code",
    "marks_numbers",
    "length_cm",
    "width_cm",
    "height_cm",
    "volume_m3",
    "sender_name",
    "sender_contact",
    "sender_address",
    "sender_country_code",
    "sender_tax_id",
    "recipient_name",
    "recipient_contact",
    "recipient_address",
    "mode_of_transport",
    "vessel_name",
    "voyage_no",
    "imo_no",
    "port_load_unlocode",
    "port_discharge_unlocode",
    "master_bl_no",
    "house_bl_no",
    "issue_date",
    "incoterms",
    "fragile_goods",
    "biodegradable_goods",
    "expiry_date",
    "internal_notes",
)


TRACKING_CODE_ATTEMPTS = 5


def _insert_registered_parcel(parcel):
    """Retry only code collisions, including concurrent inserts in other tenants."""
    for attempt in range(TRACKING_CODE_ATTEMPTS):
        try:
            # A savepoint keeps a database collision from poisoning registration.
            with transaction.atomic():
                parcel._domain_save(force_insert=True)
            return
        except ValidationError as exc:
            errors = getattr(exc, "error_dict", {})
            if set(errors) != {"tracking_code"} or any(
                error.code != "unique" for error in errors["tracking_code"]
            ):
                raise
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)
            if constraint and "tracking_code" not in constraint:
                raise
            if not Parcel.objects.filter(tracking_code=parcel.tracking_code).exists():
                raise
        if attempt + 1 < TRACKING_CODE_ATTEMPTS:
            parcel.tracking_code = generate_tracking_code()
    raise ValidationError("Unable to allocate a unique parcel tracking code. Please retry.")


def require_parcel_access(*, business, actor, write=False):
    """Recheck persisted access; callers cannot trust request/model caches."""
    business_id = getattr(business, "pk", None)
    current = Business.objects.filter(pk=business_id, is_active=True).first()
    if current is None or current.vertical != Business.Vertical.LOGISTICS:
        raise PermissionDenied("Parcel operations require an active Logistics workspace.")
    roles = PARCEL_MANAGE_ROLES if write else PARCEL_VIEW_ROLES
    if not BusinessUser.objects.filter(
        business=current,
        user_id=getattr(actor, "pk", None),
        is_active=True,
        user__is_active=True,
        role__in=roles,
    ).exists():
        raise PermissionDenied("Your workspace role does not permit this parcel operation.")
    subscription = (
        BusinessSubscription.objects.select_related("business", "plan")
        .filter(business=current)
        .first()
    )
    allowed = subscription and all(
        subscription.can_use_module(module) if write else subscription.can_view_module(module)
        for module in ("parcels", "tracking")
    )
    if not allowed:
        raise PermissionDenied("Your workspace subscription does not permit this parcel operation.")
    return current


def parcels_for_business(*, business, actor):
    current = require_parcel_access(business=business, actor=actor)
    return Parcel.objects.filter(business=current, client__business=current)


def _key(value):
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("Use a valid UUID retry key.") from exc


def _locked_business(business, actor):
    current = Business.objects.select_for_update().filter(pk=getattr(business, "pk", None)).first()
    return require_parcel_access(business=current, actor=actor, write=True)


@transaction.atomic
def register_parcel(*, business, client, actor, idempotency_key=None, **fields):
    current = _locked_business(business, actor)
    if set(fields) - set(PARCEL_INPUT_FIELDS):
        raise ValidationError("Unsupported parcel registration fields.")
    customer = (
        Client.objects.select_for_update()
        .filter(
            pk=getattr(client, "pk", None),
            business=current,
        )
        .first()
    )
    if customer is None:
        raise ValidationError({"client": "Select a client owned by this workspace."})
    key = _key(idempotency_key)
    parcel = Parcel(business=current, client=customer, created_by=actor, **fields)
    # Validation also normalizes decimal and integer values before comparing retries.
    parcel.full_clean(exclude=["tracking_code"])
    existing = (
        ParcelEvent.objects.filter(business=current, idempotency_key=key).first() if key else None
    )
    if existing:
        previous = Parcel.objects.filter(pk=existing.parcel_id, business=current).first()
        if (
            previous is None
            or existing.event_type != ParcelEvent.Type.STATUS
            or existing.status != Parcel.Status.REGISTERED
            or existing.actor_id != actor.pk
            or previous.client_id != customer.pk
            or any(getattr(previous, name) != getattr(parcel, name) for name in PARCEL_INPUT_FIELDS)
        ):
            raise ValidationError("This retry key was already used for a different operation.")
        return previous
    _insert_registered_parcel(parcel)
    ParcelEvent(
        business=current,
        parcel=parcel,
        actor=actor,
        event_type=ParcelEvent.Type.STATUS,
        status=Parcel.Status.REGISTERED,
        public_message="Parcel registered.",
        idempotency_key=key,
    )._domain_save(force_insert=True)
    return parcel


@transaction.atomic
def edit_parcel(*, business, parcel, actor, expected_updated_at=None, **fields):
    """Edit metadata with the same access, locking and history boundary as tracking."""
    current = _locked_business(business, actor)
    if set(fields) - set(PARCEL_INPUT_FIELDS):
        raise ValidationError("Unsupported parcel editing fields.")
    locked = (
        Parcel.objects.select_for_update()
        .filter(pk=getattr(parcel, "pk", parcel), business=current)
        .first()
    )
    if locked is None:
        raise ValidationError("Parcel is unavailable in this workspace.")
    if (
        not Client.objects.select_for_update()
        .filter(pk=locked.client_id, business=current)
        .exists()
    ):
        raise ValidationError("Parcel client is unavailable in this workspace.")
    previous = {name: getattr(locked, name) for name in fields}
    for name, value in fields.items():
        setattr(locked, name, value)
    locked.full_clean()
    changed = [name for name in fields if previous[name] != getattr(locked, name)]
    # An identical retry needs neither another write nor another history event.
    if not changed:
        return locked
    if expected_updated_at is not None and locked.updated_at != expected_updated_at:
        raise ValidationError("The parcel changed. Reload before saving your edits.")
    locked._domain_save(update_fields=[*changed, "updated_at"])
    ParcelEvent(
        business=current,
        parcel=locked,
        actor=actor,
        event_type=ParcelEvent.Type.NOTE,
        internal_note="Parcel details updated: "
        + ", ".join(str(Parcel._meta.get_field(name).verbose_name) for name in changed)
        + ".",
    )._domain_save(force_insert=True)
    return locked


@transaction.atomic
def record_parcel_event(
    *,
    business,
    parcel,
    actor,
    status=None,
    location="",
    public_message="",
    internal_note="",
    idempotency_key=None,
    expected_status=None,
):
    current = _locked_business(business, actor)
    locked = (
        Parcel.objects.select_for_update()
        .filter(pk=getattr(parcel, "pk", parcel), business=current)
        .first()
    )
    if locked is None:
        raise ValidationError("Parcel is unavailable in this workspace.")
    # Recheck the CRM relation too, including legacy/unowned or subsequently moved clients.
    if (
        not Client.objects.select_for_update()
        .filter(pk=locked.client_id, business=current)
        .exists()
    ):
        raise ValidationError("Parcel client is unavailable in this workspace.")
    if status is not None and status not in Parcel.Status.values:
        raise ValidationError({"status": "Select a valid parcel status."})
    key = _key(idempotency_key)
    event = ParcelEvent(
        business=current,
        parcel=locked,
        actor=actor,
        event_type=ParcelEvent.Type.STATUS if status else ParcelEvent.Type.NOTE,
        status=status or "",
        location=location,
        public_message=public_message,
        internal_note=internal_note,
        idempotency_key=key,
    )
    existing = (
        ParcelEvent.objects.filter(business=current, idempotency_key=key).first() if key else None
    )
    if existing:
        if any(
            getattr(existing, name) != getattr(event, name)
            for name in (
                "parcel_id",
                "actor_id",
                "event_type",
                "status",
                "location",
                "public_message",
                "internal_note",
            )
        ):
            raise ValidationError("This retry key was already used for a different operation.")
        return existing
    if expected_status is not None and locked.current_status != expected_status:
        raise ValidationError("The parcel status changed. Reload before recording this update.")
    if status:
        if status not in ALLOWED_TRANSITIONS[locked.current_status]:
            raise ValidationError({"status": "This status transition is not allowed."})
        locked.current_status = status
        locked._domain_save(update_fields=["current_status", "updated_at"])
    elif not (public_message.strip() or internal_note.strip()):
        raise ValidationError("Enter a tracking message or internal note.")
    event._domain_save(force_insert=True)
    return event


def change_parcel_status(*, business, parcel, actor, status, **kwargs):
    if not status:
        raise ValidationError({"status": "Select a parcel status."})
    return record_parcel_event(
        business=business, parcel=parcel, actor=actor, status=status, **kwargs
    )
