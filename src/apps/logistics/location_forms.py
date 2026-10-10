import uuid

from django import forms
from django.db.models import Q

from .dashboard_forms import style_dashboard_fields
from .location_reference import ROUTE_LOCATION_FIELDS, country_choices, exact_country_code
from .models import LogisticsLocation, Parcel, ParcelEvent, Shipment


def searchable(field, placeholder):
    field.widget.attrs.update(
        {"data-logistics-search-select": "", "data-search-placeholder": placeholder}
    )


def geographic_country_field(*, value="", required=False):
    """Keep an existing unmatched text value, without offering it on new forms."""
    choices = [("", "Select country / territory"), *[(name, name) for _, name in country_choices()]]
    if value and value not in dict(choices):
        choices.append((value, f"{value} (saved value)"))
    field = GeographicCountryChoiceField(
        choices=choices, required=required, label="Country / territory"
    )
    searchable(field, "Search countries and territories")
    return field


class GeographicCountryChoiceField(forms.ChoiceField):
    def to_python(self, value):
        value = super().to_python(value)
        if value and value not in dict(self.choices):
            code = exact_country_code(value)
            if code:
                return dict(country_choices())[code]
        return value


def configure_route_fields(form, business, actor=None):
    from .location_access import has_wide_access, locations_for, scope_records

    previous = form.instance if form.instance.pk else None
    if previous is None and form.is_bound and "idempotency_key" in form.fields:
        try:
            key = uuid.UUID(str(form.data.get(form.add_prefix("idempotency_key"))))
        except (ValueError, TypeError, AttributeError):
            key = None
        if key and isinstance(form.instance, Shipment):
            query = Shipment.objects.filter(business=business, idempotency_key=key)
            if actor is not None:
                query = scope_records(query, business=business, actor=actor)
            previous = query.first()
        elif key and isinstance(form.instance, Parcel):
            receipt = (
                ParcelEvent.objects.select_related("parcel")
                .filter(
                    business=business,
                    parcel__business=business,
                    idempotency_key=key,
                    event_type=ParcelEvent.Type.STATUS,
                    status=Parcel.Status.REGISTERED,
                )
                .first()
            )
            previous = receipt.parcel if receipt else None
        if (
            previous is not None
            and actor is not None
            and not scope_records(
                type(previous).objects.filter(pk=previous.pk, business=business),
                business=business,
                actor=actor,
            ).exists()
        ):
            previous = None
        form.instance._route_previous = previous
    if form.is_bound and form.instance.pk:
        data = form.data.copy()
        for name in ROUTE_LOCATION_FIELDS:
            key = form.add_prefix(name)
            if key not in data:
                value = getattr(form.instance, f"{name}_id" if name.endswith("_location") else name)
                data[key] = value if value is not None else ""
        form.data = data
    for side in ("origin", "destination"):
        searchable(form.fields[f"{side}_country_code"], "Search countries and territories")
        searchable(form.fields[f"{side}_reference_code"], "Search verified ports and airports")
        field = f"{side}_location"
        saved = getattr(previous, f"{field}_id", None)
        form.fields[field].queryset = LogisticsLocation.objects.filter(
            Q(is_active=True) | Q(pk=saved),
            business=business,
        )
        if actor is not None and not has_wide_access(business, actor):
            form.fields[field].queryset = locations_for(business, actor)
            if form.instance.pk:
                form.fields[field].disabled = True
                form.fields[field].queryset = LogisticsLocation.objects.filter(
                    Q(pk__in=locations_for(business, actor).values("pk")) | Q(pk=saved),
                    business=business,
                )
            else:
                selected = (
                    locations_for(business, actor)
                    .filter(
                        worker_assignments__membership__user=actor,
                        worker_assignments__is_current=True,
                    )
                    .first()
                )
                if side == "origin" and selected:
                    form.initial.setdefault(field, selected.pk)
        searchable(form.fields[field], "Search this workspace's facilities")
        form.fields[
            field
        ].help_text = "Optional. Destinations do not need a company facility. Saved inactive facilities can be retained."
        form.fields[side].label = f"{side.title()} geographic place"
        form.fields[
            side
        ].help_text = "Geographic place, separate from company facilities and street addresses."


class LogisticsLocationForm(forms.ModelForm):
    class Meta:
        model = LogisticsLocation
        fields = (
            "name",
            "code",
            "location_type",
            "country_code",
            "reference_code",
            "address_line_1",
            "address_line_2",
            "city",
            "region",
            "postal_code",
            "is_active",
        )

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.business = business
        for name in ("country_code", "reference_code"):
            searchable(
                self.fields[name],
                (
                    "Search countries and territories"
                    if name == "country_code"
                    else "Search verified ports and airports"
                ),
            )
        if self.instance.pk:
            self.fields["code"].disabled = True
            self.fields["country_code"].disabled = True
        self.fields[
            "reference_code"
        ].help_text = "Optional verified UN/LOCODE. Leave blank if the reference list does not cover this facility."
        style_dashboard_fields(self.fields)
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"

    def save(self, commit=True):
        raise NotImplementedError("Use location_services to save authorized facility changes.")
