"""Shared informational Logistics taxonomy; never an operational access policy."""

from django.core.exceptions import ValidationError
from django.db import models


class OperatingArea(models.TextChoices):
    TRANSPORTATION = "TRANSPORTATION", "Transportation"
    WAREHOUSING = "WAREHOUSING", "Warehousing"
    INVENTORY_MANAGEMENT = "INVENTORY_MANAGEMENT", "Inventory Management"
    ORDER_PROCESSING = "ORDER_PROCESSING", "Order Processing"


class TransportationMode(models.TextChoices):
    SEA = "SEA", "Sea"
    AIR = "AIR", "Air"
    ROAD = "ROAD", "Road / Truck"
    RAIL = "RAIL", "Rail"


def default_operating_areas():
    return [OperatingArea.TRANSPORTATION.value]


def _validate_selection(values, choices):
    if not isinstance(values, list) or any(
        not isinstance(value, str) or value not in choices.values for value in values
    ):
        raise ValidationError("Select only valid choices.")
    if len(values) != len(set(values)):
        raise ValidationError("Select each choice only once.")


def validate_operating_areas(values):
    _validate_selection(values, OperatingArea)


def validate_transportation_modes(values):
    _validate_selection(values, TransportationMode)


def validate_classification(areas, modes, *, require_areas=True, require_modes=False):
    errors = {}
    for name, value, validator in (
        ("operating_areas", areas, validate_operating_areas),
        ("transportation_modes", modes, validate_transportation_modes),
    ):
        try:
            validator(value)
        except ValidationError as exc:
            errors[name] = exc.messages
    if errors:
        raise ValidationError(errors)
    if require_areas and not areas:
        errors["operating_areas"] = "Select at least one operating area."
    if OperatingArea.TRANSPORTATION in areas:
        if require_modes and not modes:
            errors["transportation_modes"] = "Select at least one transportation mode."
    elif modes:
        errors["transportation_modes"] = "Select Transportation before choosing its modes."
    if errors:
        raise ValidationError(errors)


def normalize_classification(instance):
    # Stable taxonomy order keeps equivalent checkbox selections from revising approval.
    instance.operating_areas = [v for v in OperatingArea.values if v in instance.operating_areas]
    instance.transportation_modes = [
        v for v in TransportationMode.values if v in instance.transportation_modes
    ]


class ClassificationHelpers:
    def has_operating_area(self, area):
        return area in OperatingArea.values and area in self.operating_areas

    def has_transport_mode(self, mode):
        return (
            self.has_operating_area(OperatingArea.TRANSPORTATION)
            and mode in TransportationMode.values
            and mode in self.transportation_modes
        )

    @property
    def operating_area_labels(self):
        return [OperatingArea(value).label for value in self.operating_areas]

    @property
    def transportation_mode_labels(self):
        return [TransportationMode(value).label for value in self.transportation_modes]
