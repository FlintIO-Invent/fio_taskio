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
    if configured and mode not in configured:
        raise ValidationError(
            {"transport_mode": "Select a transportation mode configured for this workspace."}
        )
    return mode
