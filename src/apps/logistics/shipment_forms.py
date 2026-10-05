from django import forms

from .dashboard_forms import style_dashboard_fields
from .models import Parcel, Shipment
from .shipment_policy import ALLOWED_TRANSITIONS, ASSIGNABLE_PARCEL_STATUSES
from .shipment_services import SHIPMENT_INPUT_FIELDS


class EligibleParcelField(forms.ModelChoiceField):
    def label_from_instance(self, parcel):
        return f"{parcel.tracking_code} · {parcel.client} · {parcel.get_current_status_display()} · {parcel.origin} → {parcel.destination}"


def eligible_parcels(business):
    return (
        Parcel.objects.filter(
            business=business,
            client__business=business,
            shipment__isnull=True,
            current_status__in=ASSIGNABLE_PARCEL_STATUSES,
        )
        .select_related("client")
        .order_by("tracking_code")
    )


def style_parcel_selection(field):
    field.widget.attrs["data-logistics-search-select"] = ""
    field.widget.attrs["data-search-placeholder"] = "Search by tracking code, client or route"


class ShipmentForm(forms.ModelForm):
    parcel = EligibleParcelField(
        queryset=Parcel.objects.none(),
        required=False,
        label="Assign a parcel",
        help_text="Optional. Registered or received parcels without a shipment are available.",
    )

    class Meta:
        model = Shipment
        fields = SHIPMENT_INPUT_FIELDS
        widgets = {
            "departure_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "estimated_arrival_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "departure_at": "Departure time",
            "estimated_arrival_at": "Estimated arrival time",
        }
        help_texts = {
            "departure_at": "Optional. Enter the planned departure time.",
            "estimated_arrival_at": "Optional. Enter the expected arrival time.",
            "notes": "Optional internal notes for this shipment.",
        }

    def __init__(self, *args, business, allow_assignment=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.business = business
        if allow_assignment:
            self.fields["parcel"].queryset = eligible_parcels(business)
            style_parcel_selection(self.fields["parcel"])
        else:
            self.fields.pop("parcel")
        style_dashboard_fields(self.fields)
        self.fields["origin"].widget.attrs.update({"placeholder": "e.g. Miami", "autofocus": True})
        self.fields["destination"].widget.attrs["placeholder"] = "e.g. Curaçao"

    def save(self, commit=True):
        raise NotImplementedError("Use the shipment services with validated form data.")


class ShipmentAssignmentForm(forms.Form):
    parcel = EligibleParcelField(queryset=Parcel.objects.none(), label="Parcel")

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parcel"].queryset = eligible_parcels(business)
        style_parcel_selection(self.fields["parcel"])
        style_dashboard_fields(self.fields)


class ShipmentStatusForm(forms.Form):
    status = forms.ChoiceField()
    expected_status = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, shipment, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (value, label)
            for value, label in Shipment.Status.choices
            if value in ALLOWED_TRANSITIONS[shipment.status]
        ]
        self.fields["expected_status"].initial = shipment.status
        style_dashboard_fields(self.fields)
