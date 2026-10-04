from django import forms

from .models import Parcel, Shipment
from .shipment_policy import ALLOWED_TRANSITIONS, ASSIGNABLE_PARCEL_STATUSES
from .shipment_services import SHIPMENT_INPUT_FIELDS


class ShipmentForm(forms.ModelForm):
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

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.business = business

    def save(self, commit=True):
        raise NotImplementedError("Use the shipment services with validated form data.")


class ShipmentAssignmentForm(forms.Form):
    parcel = forms.ModelChoiceField(queryset=Parcel.objects.none())

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parcel"].queryset = Parcel.objects.filter(
            business=business,
            client__business=business,
            shipment__isnull=True,
            current_status__in=ASSIGNABLE_PARCEL_STATUSES,
        ).order_by("tracking_code")


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
