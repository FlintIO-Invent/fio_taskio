"""Optional operational references, with historical retention and no capability gates."""

from django.core.exceptions import ValidationError

from .classification import TransportationMode

SHARED_REFERENCE_FIELDS = ("carrier_name",)
SEA_REFERENCE_FIELDS = (
    "vessel_name",
    "voyage_reference",
    "container_reference",
    "bill_of_lading_reference",
)
ROAD_REFERENCE_FIELDS = ("vehicle_reference", "driver_name", "dispatch_reference")
SHIPMENT_REFERENCE_FIELDS = SHARED_REFERENCE_FIELDS + SEA_REFERENCE_FIELDS + ROAD_REFERENCE_FIELDS


def reference_fields_for_mode(mode):
    specialized = {
        TransportationMode.SEA: SEA_REFERENCE_FIELDS,
        TransportationMode.ROAD: ROAD_REFERENCE_FIELDS,
    }.get(mode, ())
    return SHARED_REFERENCE_FIELDS + specialized


def normalize_reference(value):
    return (value.strip() or None) if isinstance(value, str) else value


def validate_shipment_references(mode, values, *, previous=None):
    allowed = reference_fields_for_mode(mode)
    errors = {}
    for name in SHIPMENT_REFERENCE_FIELDS:
        value = normalize_reference(values.get(name))
        if value is None or name in allowed:
            continue
        if previous is not None and value == normalize_reference(previous.get(name)):
            continue
        errors[name] = "This reference does not apply to the selected transportation mode."
    if errors:
        raise ValidationError(errors)


def populated_transport_references(shipment, *, include_historical=False):
    fields = (
        SHIPMENT_REFERENCE_FIELDS
        if include_historical
        else reference_fields_for_mode(shipment.transport_mode)
    )
    return [
        {"label": shipment._meta.get_field(name).verbose_name, "value": getattr(shipment, name)}
        for name in fields
        if getattr(shipment, name)
    ]
