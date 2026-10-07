import uuid

from django import forms
from django.db.models import Q

from .dashboard_forms import style_dashboard_fields
from .models import Parcel, Shipment
from .shipment_policy import ALLOWED_TRANSITIONS, ASSIGNABLE_PARCEL_STATUSES
from .shipment_services import SHIPMENT_INPUT_FIELDS


class EligibleParcelField(forms.ModelChoiceField):
    def label_from_instance(self, parcel):
        return f"{parcel.tracking_code} · {parcel.client} · {parcel.get_current_status_display()} · {parcel.origin} → {parcel.destination}"


def eligible_parcels(business, replay_shipment=None):
    eligible = Q(shipment__isnull=True, current_status__in=ASSIGNABLE_PARCEL_STATUSES)
    if replay_shipment is not None:
        eligible |= Q(shipment=replay_shipment)
    return (
        Parcel.objects.filter(
            eligible,
            business=business,
            client__business=business,
        )
        .select_related("client")
        .order_by("tracking_code")
    )


def style_parcel_selection(field):
    field.widget.attrs["data-logistics-search-select"] = ""
    field.widget.attrs["data-search-placeholder"] = "Search by tracking code, client or route"


class ShipmentForm(forms.ModelForm):
    idempotency_key = forms.UUIDField(
        widget=forms.HiddenInput,
        error_messages={
            "required": "The shipment retry token is missing. Reload before saving.",
        },
    )
    expected_revision = forms.IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
        error_messages={
            "required": "The loaded shipment revision is missing. Reload before saving.",
        },
    )
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
        self.fields["idempotency_key"].initial = uuid.uuid4()
        if self.instance.pk:
            self.fields["expected_revision"].initial = self.instance.revision
        else:
            self.fields.pop("expected_revision")
        replay_shipment = self.instance if self.is_bound and self.instance.pk else None
        if self.is_bound and not self.instance.pk:
            try:
                key = self.fields["idempotency_key"].to_python(self.data.get("idempotency_key"))
            except forms.ValidationError:
                key = None
            if key:
                replay_shipment = Shipment.objects.filter(
                    business=business, idempotency_key=key
                ).first()
        if allow_assignment:
            self.fields["parcel"].queryset = eligible_parcels(business, replay_shipment)
            style_parcel_selection(self.fields["parcel"])
        else:
            self.fields.pop("parcel")
        style_dashboard_fields(self.fields)
        self.fields["origin"].widget.attrs.update({"placeholder": "e.g. Miami", "autofocus": True})
        self.fields["destination"].widget.attrs["placeholder"] = "e.g. Curaçao"

    def save(self, commit=True):
        raise NotImplementedError("Use the shipment services with validated form data.")


class ShipmentWriteForm(forms.Form):
    idempotency_key = forms.UUIDField(
        widget=forms.HiddenInput,
        error_messages={
            "required": "The shipment retry token is missing. Reload before saving.",
        },
    )
    expected_revision = forms.IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
        error_messages={
            "required": "The loaded shipment revision is missing. Reload before saving.",
        },
    )

    def __init__(self, *args, shipment=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["idempotency_key"].initial = uuid.uuid4()
        if shipment:
            self.fields["expected_revision"].initial = shipment.revision


class ShipmentAssignmentForm(ShipmentWriteForm):
    parcel = EligibleParcelField(queryset=Parcel.objects.none(), label="Parcel")

    def __init__(self, *args, business, shipment=None, **kwargs):
        super().__init__(*args, shipment=shipment, **kwargs)
        self.fields["parcel"].queryset = eligible_parcels(
            business, shipment if self.is_bound else None
        )
        style_parcel_selection(self.fields["parcel"])
        style_dashboard_fields(self.fields)


class ShipmentStatusForm(ShipmentWriteForm):
    status = forms.ChoiceField()
    expected_status = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, shipment, **kwargs):
        super().__init__(*args, shipment=shipment, **kwargs)
        self.fields["status"].choices = [
            (value, label)
            for value, label in Shipment.Status.choices
            if value in ALLOWED_TRANSITIONS[shipment.status]
        ]
        # A replay's target may now be the current status or a historical status.
        # Services recognize its receipt before checking a new transition.
        submitted = self.data.get("status") if self.is_bound else None
        if submitted in Shipment.Status.values and submitted not in dict(
            self.fields["status"].choices
        ):
            self.fields["status"].choices.append((submitted, Shipment.Status(submitted).label))
        self.fields["expected_status"].initial = shipment.status
        style_dashboard_fields(self.fields)
