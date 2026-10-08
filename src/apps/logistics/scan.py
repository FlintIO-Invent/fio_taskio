"""Source-independent authenticated tracking-code resolution and scan forms."""

import re

from django import forms
from django.core.exceptions import ValidationError

from .forms import ParcelEventForm
from .parcel_services import parcels_for_business


def normalize_scan_code(value):
    """Remove surrounding scanner CR/LF/tab suffixes; never remove interior data."""
    if not isinstance(value, str) or len(value) > 256:
        raise ValidationError("Enter a complete 48-character tracking code.")
    code = value.strip().upper()
    if not re.fullmatch(r"[A-F0-9]{48}", code):
        raise ValidationError("Enter a complete 48-character tracking code.")
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
            }
        ),
    )

    def clean_tracking_code(self):
        return normalize_scan_code(self.cleaned_data["tracking_code"])


class ScanActionForm(ParcelEventForm):
    """Only a status action; all authorization and receipt handling stay in services."""

    def __init__(self, *args, parcel, **kwargs):
        super().__init__(*args, parcel=parcel, **kwargs)
        for name in ("location", "public_message", "internal_note"):
            self.fields.pop(name)
        self.fields["status"].required = True
