from django import forms

from apps.businesses.models import BusinessUser

from .dashboard_forms import style_dashboard_fields
from .location_access import WIDE_ROLES
from .location_forms import searchable
from .models import LogisticsHandlingSite, LogisticsLocation, Parcel, Shipment


class LocationAssignmentForm(forms.Form):
    membership = forms.ModelChoiceField(
        queryset=BusinessUser.objects.none(), label="Workspace worker"
    )
    location = forms.ModelChoiceField(queryset=LogisticsLocation.objects.none())
    can_operate = forms.BooleanField(required=False, label="Allow operational writes (staff only)")
    revoke = forms.BooleanField(required=False, label="Revoke assignment")

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["membership"].queryset = (
            BusinessUser.objects.filter(business=business)
            .exclude(role__in=WIDE_ROLES)
            .select_related("user")
        )
        self.fields["membership"].label_from_instance = (
            lambda member: f"{member.user} · {member.get_role_display()}"
            + (" (inactive)" if not member.is_active or not member.user.is_active else "")
        )
        self.fields["location"].queryset = LogisticsLocation.objects.filter(business=business)
        for name in ("membership", "location"):
            searchable(self.fields[name], "Search workspace assignments")
        style_dashboard_fields(self.fields)
        for name in ("can_operate", "revoke"):
            self.fields[name].widget.attrs["class"] = "form-check-input"


class HandlingSiteForm(forms.Form):
    parcel = forms.ModelChoiceField(queryset=Parcel.objects.none(), required=False)
    shipment = forms.ModelChoiceField(queryset=Shipment.objects.none(), required=False)
    location = forms.ModelChoiceField(queryset=LogisticsLocation.objects.none())
    kind = forms.ChoiceField(choices=LogisticsHandlingSite.Kind.choices)
    remove = forms.BooleanField(required=False, label="Remove association")

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parcel"].queryset = Parcel.objects.filter(
            business=business, client__business=business
        )
        self.fields["parcel"].label_from_instance = lambda parcel: parcel.tracking_code
        self.fields["shipment"].queryset = Shipment.objects.filter(business=business)
        self.fields["location"].queryset = LogisticsLocation.objects.filter(business=business)
        for name in ("parcel", "shipment", "location"):
            searchable(self.fields[name], "Search records and facilities")
        style_dashboard_fields(self.fields)
        self.fields["remove"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        data = super().clean()
        if bool(data.get("parcel")) == bool(data.get("shipment")):
            raise forms.ValidationError("Select exactly one parcel or shipment.")
        return data
