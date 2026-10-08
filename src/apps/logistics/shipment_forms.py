import uuid

from django import forms
from django.db.models import Q

from .classification import TransportationMode
from .dashboard_forms import style_dashboard_fields
from .models import Parcel, Shipment
from .shipment_policy import ALLOWED_TRANSITIONS, ASSIGNABLE_PARCEL_STATUSES
from .shipment_references import (
    ROAD_REFERENCE_FIELDS,
    SEA_REFERENCE_FIELDS,
    SHIPMENT_REFERENCE_FIELDS,
    normalize_reference,
    validate_shipment_references,
)
from .shipment_services import SHIPMENT_INPUT_FIELDS
from .shipment_transport import configured_shipment_modes, validate_shipment_mode


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
        self.business = business
        self.previous_mode = self.instance.transport_mode
        self.mode_existing = bool(self.instance.pk)
        self.mode_replay = False
        self.previous_references = {
            name: getattr(self.instance, name) for name in SHIPMENT_REFERENCE_FIELDS
        }
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
        if replay_shipment is not None:
            self.previous_mode = replay_shipment.transport_mode
            self.mode_existing = True
            try:
                key = self.fields["idempotency_key"].to_python(self.data.get("idempotency_key"))
            except forms.ValidationError:
                key = None
            self.mode_replay = str(key) in replay_shipment.write_receipts
        configured = configured_shipment_modes(business)
        modes = (
            TransportationMode.values
            if self.mode_replay
            else configured or TransportationMode.values
        )
        choices = [
            (value, label)
            for value, label in TransportationMode.choices
            if value in modes or value == self.previous_mode
        ]
        mode_field = self.fields["transport_mode"]
        mode_field.required = bool(configured) and not (
            self.mode_replay
            or self.mode_existing
            and (self.previous_mode is None or self.is_bound and "transport_mode" not in self.data)
        )
        mode_field.choices = [
            ("", "Select transportation mode" if mode_field.required else "Unknown")
        ] + choices
        if not self.mode_existing and len(configured) == 1:
            self.initial.setdefault("transport_mode", configured[0])
        mode_field.help_text = (
            "Choose a workspace transportation mode. Saved historical modes can be retained."
            if configured
            else "Optional. Workspace transportation modes are not configured; leave unknown if unsure."
        )
        if allow_assignment:
            self.fields["parcel"].queryset = eligible_parcels(business, replay_shipment)
            style_parcel_selection(self.fields["parcel"])
        else:
            self.fields.pop("parcel")
        style_dashboard_fields(self.fields)
        self.fields["origin"].widget.attrs.update({"placeholder": "e.g. Miami", "autofocus": True})
        self.fields["destination"].widget.attrs["placeholder"] = "e.g. Curaçao"

    def clean_transport_mode(self):
        if self.mode_replay:
            # The service verifies the exact receipt before applying current policy.
            return self.cleaned_data.get("transport_mode") or None
        if self.mode_existing and self.is_bound and "transport_mode" not in self.data:
            return self.previous_mode
        try:
            return validate_shipment_mode(
                self.cleaned_data.get("transport_mode"),
                business=self.business,
                existing=self.mode_existing,
                previous_mode=self.previous_mode,
            )
        except forms.ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc

    def clean(self):
        data = super().clean()
        for name in SHIPMENT_REFERENCE_FIELDS:
            if name in data:
                data[name] = normalize_reference(data[name])
        if not self.mode_replay and "transport_mode" in data:
            values = {
                **self.previous_references,
                **{
                    name: data[name]
                    for name in SHIPMENT_REFERENCE_FIELDS
                    if name in data and name in self.data
                },
            }
            try:
                validate_shipment_references(
                    data["transport_mode"],
                    values,
                    previous=self.previous_references if self.instance.pk else None,
                )
            except forms.ValidationError as exc:
                for name, errors in exc.message_dict.items():
                    self.add_error(name, errors)
        return data

    @property
    def sea_reference_fields(self):
        return [self[name] for name in SEA_REFERENCE_FIELDS]

    @property
    def road_reference_fields(self):
        return [self[name] for name in ROAD_REFERENCE_FIELDS]

    @property
    def sea_references_visible(self):
        return self["transport_mode"].value() == TransportationMode.SEA or any(
            self[name].errors for name in SEA_REFERENCE_FIELDS
        )

    @property
    def road_references_visible(self):
        return self["transport_mode"].value() == TransportationMode.ROAD or any(
            self[name].errors for name in ROAD_REFERENCE_FIELDS
        )

    def save(self, commit=True):
        raise NotImplementedError("Use the shipment services with validated form data.")


class ShipmentFilterForm(forms.Form):
    transport_mode = forms.ChoiceField(
        label="Transportation mode",
        required=False,
        choices=[("", "All modes"), *TransportationMode.choices, ("UNKNOWN", "Unknown")],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_dashboard_fields(self.fields)


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
        self.fields["status"].widget.choices = [
            (value, label)
            for value, label in Shipment.Status.choices
            if value in ALLOWED_TRANSITIONS[shipment.status]
        ]
