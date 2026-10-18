import uuid

from django import forms
from django.db.models import Q

from .dashboard_forms import style_dashboard_fields
from .location_reference import (
    ROUTE_LOCATION_FIELDS,
    country_choices,
    exact_country_code,
    location_references,
    operating_country_codes,
    reference_choices,
    reference_matches,
)
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
    from .location_access import has_wide_access, scope_records

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
    from .location_access import assignments_for
    from .shipment_transport import parcel_mode

    current = assignments_for(business, actor).filter(is_current=True).first() if actor else None
    if current is None and actor is not None and has_wide_access(business, actor):
        from .models import LogisticsLocationAssignment

        current = (
            LogisticsLocationAssignment.objects.filter(
                business=business,
                membership__user=actor,
                membership__is_active=True,
                is_current=True,
                location__business=business,
                location__is_active=True,
            )
            .select_related("location")
            .first()
        )
    if previous is None and current:
        form.initial.setdefault("origin_location", current.location_id)
        form.initial.setdefault("origin_country_code", current.location.country_code)
    mode_name = "transport_mode" if "transport_mode" in form.fields else "mode_of_transport"
    mode = parcel_mode(form[mode_name].value())
    countries = operating_country_codes(business)
    form.route_options = {
        "references": [
            {"value": code, "label": label, **location_references()[code]}
            for code, label in reference_choices()
        ]
    }
    for side in ("origin", "destination"):
        country_name = f"{side}_country_code"
        field = f"{side}_location"
        saved = getattr(previous, f"{field}_id", None)
        saved_country = getattr(previous, country_name, None)
        choices = [
            (code, name)
            for code, name in country_choices()
            if code in countries or code == saved_country
        ]
        country_field = form.fields[country_name]
        country_field.choices = [("", "Select country / territory"), *choices]
        country_field.required = previous is None and bool(countries)
        searchable(country_field, "Search operating territories")
        country_field.widget.attrs["data-route-country"] = side
        country = form[country_name].value()
        queryset = LogisticsLocation.objects.filter(
            Q(is_active=True) | Q(pk=saved), business=business
        )
        if side == "origin" and actor is not None and not has_wide_access(business, actor):
            if form.instance.pk:
                form.fields[field].disabled = True
                queryset = queryset.filter(pk=saved)
            else:
                queryset = queryset.filter(pk=current.location_id if current else None)
        form.route_options[side] = [
            {"value": str(item.pk), "label": str(item), "country_code": item.country_code}
            for item in queryset
        ]
        if country:
            queryset = queryset.filter(country_code=country)
        elif side != "destination":
            queryset = queryset.filter(pk=saved)
        form.fields[field].queryset = queryset
        form.fields[field].label = f"{side.title()} company facility"
        form.fields[field].help_text = ""
        form.fields[field].widget.attrs["data-route-facility"] = side
        searchable(form.fields[field], "Search company facilities")
        reference_names = [f"{side}_reference_code"]
        if "mode_of_transport" in form.fields:
            reference_names.append(
                "port_load_unlocode" if side == "origin" else "port_discharge_unlocode"
            )
        for name in reference_names:
            saved_reference = getattr(previous, name, "")
            choices = [
                (code, label)
                for code, label in reference_choices()
                if reference_matches(code, country, mode) or code == saved_reference
            ]
            if saved_reference and saved_reference not in dict(choices):
                choices.append((saved_reference, f"{saved_reference} (saved value)"))
            form.fields[name] = forms.ChoiceField(
                required=False,
                label=form.fields[name].label,
                choices=[("", "None"), *choices],
            )
            form.fields[name].widget.attrs["data-route-reference"] = side
            if saved_reference:
                form.fields[name].widget.attrs["data-route-saved-reference"] = saved_reference
            searchable(form.fields[name], "Search ports and airports")
        form.fields[side].widget = forms.HiddenInput()
        form.fields[side].required = False
        form.fields[side].disabled = True
        if previous:
            form.initial[side] = getattr(previous, side)


def clean_route_fields(form, data):
    for side in ("origin", "destination"):
        if not data.get(side):
            facility = data.get(f"{side}_location")
            country = data.get(f"{side}_country_code")
            data[side] = facility.name if facility else dict(country_choices()).get(country, "")
        if not data.get(side):
            form.add_error(f"{side}_country_code", "Select a country or territory.")
    return data


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
        self.fields["reference_code"].help_text = (
            "Optional verified UN/LOCODE. Leave blank if the reference list does not cover this facility."
        )
        style_dashboard_fields(self.fields)
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"

    def save(self, commit=True):
        raise NotImplementedError("Use location_services to save authorized facility changes.")
