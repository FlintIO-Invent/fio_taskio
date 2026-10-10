"""Source-independent authenticated tracking-code resolution and scan forms."""

from django import forms
from django.core.exceptions import ValidationError

from .forms import ParcelEventForm
from .parcel_services import parcels_for_business
from .tracking_codes import (
    TRACKING_CODE_BODY_PATTERN,
    TRACKING_CODE_INPUT_ERROR,
    TRACKING_CODE_PATTERN,
)


def normalize_scan_code(value):
    """Remove surrounding scanner CR/LF/tab suffixes; never remove interior data."""
    if not isinstance(value, str) or len(value) > 256:
        raise ValidationError(TRACKING_CODE_INPUT_ERROR)
    code = value.strip().upper()
    if not TRACKING_CODE_PATTERN.fullmatch(code):
        raise ValidationError(TRACKING_CODE_INPUT_ERROR)
    return code


def resolve_scanned_parcel(*, business, actor, code):
    """Exact resolution through the same persisted tenant/access boundary as Parcels."""
    normalized = normalize_scan_code(code)
    return (
        parcels_for_business(business=business, actor=actor)
        .select_related("client")
        .filter(tracking_code=normalized)
        .first()
    )


class ScanLookupForm(forms.Form):
    tracking_code = forms.CharField(
        label="Parcel tracking code",
        max_length=256,
        strip=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control form-control-lg font-monospace",
                "autocomplete": "off",
                "autocapitalize": "none",
                "spellcheck": "false",
                "enterkeyhint": "go",
                "aria-describedby": "scan-input-help scan-feedback",
                "data-scan-input": "",
                "data-tracking-code-pattern": "^" + TRACKING_CODE_BODY_PATTERN + "$",
                "data-tracking-code-error": TRACKING_CODE_INPUT_ERROR,
            }
        ),
    )

    def clean_tracking_code(self):
        return normalize_scan_code(self.cleaned_data["tracking_code"])


class ScanActionForm(ParcelEventForm):
    """Only a status action; all authorization and receipt handling stay in services."""

    def __init__(self, *args, parcel, **kwargs):
        super().__init__(*args, parcel=parcel, **kwargs)
        for name in ("location", "public_message", "internal_note", "location_override_reason"):
            self.fields.pop(name, None)
        self.fields["status"].required = True
