"""Profile defaults for shipment writes, without restricting historical data or routes."""

from django.core.exceptions import ValidationError

from .classification import TransportationMode
from .models import LogisticsProfile


def configured_shipment_modes(business):
    # Query current persisted configuration rather than a cached reverse relation.
    modes = (
        LogisticsProfile.objects.filter(business_id=business.pk)
        .values_list("transportation_modes", flat=True)
        .first()
    )
    return [mode for mode in TransportationMode.values if mode in (modes or [])]


def validate_shipment_mode(mode, *, business, existing=False, previous_mode=None):
    mode = None if mode == "" else mode
    if mode is not None and mode not in TransportationMode.values:
        raise ValidationError({"transport_mode": "Select a valid transportation mode."})
    # Unchanged historical modes (including unknown) remain editable.
    if existing and mode == previous_mode:
        return mode
    configured = configured_shipment_modes(business)
    if mode not in configured and (mode is not None or configured):
        raise ValidationError(
            {"transport_mode": "Select a transportation mode configured for this workspace."}
        )
    return mode


def parcel_mode(value):
    """Read historical display labels without rewriting their stored value."""
    labels = {label.casefold(): mode for mode, label in TransportationMode.choices}
    text = (value or "").strip()
    return labels.get(text.casefold(), text.upper()) or None


PARCEL_SEA_FIELDS = ("vessel_name", "voyage_no", "imo_no", "master_bl_no", "house_bl_no")


def validate_parcel_transport(instance, previous=None):
    value = instance.mode_of_transport
    if previous is None or value != previous.mode_of_transport:
        try:
            validate_shipment_mode(parcel_mode(value), business=instance.business)
        except ValidationError as exc:
            raise ValidationError({"mode_of_transport": exc.messages}) from exc
    mode = parcel_mode(value)
    if instance.shipment_id:
        shipment_mode = instance.shipment.transport_mode
        changed = previous is None or value != previous.mode_of_transport
        if changed and mode and shipment_mode and mode != shipment_mode:
            raise ValidationError(
                {"mode_of_transport": "Select the assigned shipment's transport mode."}
            )
    errors = {}
    for name in PARCEL_SEA_FIELDS:
        value = getattr(instance, name)
        if (
            mode != TransportationMode.SEA
            and value
            and (previous is None or value != getattr(previous, name))
        ):
            errors[name] = "This reference requires Sea transport."
    if errors:
        raise ValidationError(errors)


def validate_parcel_shipment_modes(parcel, shipment):
    mode = parcel_mode(parcel.mode_of_transport)
    if (
        mode in TransportationMode.values
        and shipment.transport_mode
        and mode != shipment.transport_mode
    ):
        raise ValidationError("The parcel and shipment transport modes must match.")
