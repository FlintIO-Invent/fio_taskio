"""Offline ISO countries and a deliberately bounded, verified UNECE reference."""

import json
from functools import lru_cache
from pathlib import Path

import pycountry
from django.core.exceptions import ValidationError

COUNTRY_NAME_ALIASES = {"Sint Maarten": "SX", "Curacao": "CW"}


def country_choices():
    return sorted(
        ((c.alpha_2, getattr(c, "common_name", c.name)) for c in pycountry.countries),
        key=lambda item: item[1],
    )


def exact_country_code(value):
    """No fuzzy matching: a city, abbreviation or misspelling needs review."""
    value = (value or "").strip().casefold()
    aliases = {name.casefold(): code for name, code in COUNTRY_NAME_ALIASES.items()}
    if value in aliases:
        return aliases[value]
    matches = {
        c.alpha_2
        for c in pycountry.countries
        if value
        in {
            c.alpha_2.casefold(),
            c.alpha_3.casefold(),
            c.name.casefold(),
            getattr(c, "common_name", "").casefold(),
            getattr(c, "official_name", "").casefold(),
        }
        and value
    }
    return next(iter(matches)) if len(matches) == 1 else None


def country_policy_identities(value):
    """Equivalent ISO names/codes for the same configured territory, no fuzzy matching."""
    from .policy import normalized_identity

    identities = {normalized_identity(value)}
    code = exact_country_code(value)
    if code:
        country = pycountry.countries.get(alpha_2=code)
        identities.update(
            normalized_identity(name)
            for name in (
                code,
                country.alpha_3,
                country.name,
                getattr(country, "common_name", ""),
                getattr(country, "official_name", ""),
                *(name for name, alias_code in COUNTRY_NAME_ALIASES.items() if alias_code == code),
            )
            if name
        )
    return identities


def validate_country_code(value):
    if value and pycountry.countries.get(alpha_2=value) is None:
        raise ValidationError("Select a valid ISO country or territory.")


@lru_cache(maxsize=1)
def location_references():
    data = json.loads(
        Path(__file__).with_name("data").joinpath("location_references.json").read_text()
    )
    return {row["code"]: row for row in data["locations"]}


def reference_choices():
    return [
        (
            code,
            f"{row['name']} · {row['country_code']} · UN/LOCODE {code} ({'/'.join(row['types'])})",
        )
        for code, row in location_references().items()
    ]


def validate_reference_code(value):
    if value and value not in location_references():
        raise ValidationError("Select a verified port or airport reference.")


ROUTE_LOCATION_FIELDS = (
    "origin_country_code",
    "destination_country_code",
    "origin_location",
    "destination_location",
    "origin_reference_code",
    "destination_reference_code",
)


def validate_route_locations(instance):
    from .models import LogisticsLocation

    errors = {}
    previous = getattr(instance, "_route_previous", None)
    if instance.pk and not instance._state.adding:
        previous = type(instance).objects.filter(pk=instance.pk).first()
    for side in ("origin", "destination"):
        country = getattr(instance, f"{side}_country_code")
        facility_country = None
        field = f"{side}_location"
        location_id = getattr(instance, f"{field}_id")
        if location_id:
            location = LogisticsLocation.objects.filter(
                pk=location_id, business_id=instance.business_id
            ).first()
            if location is None:
                errors[field] = "Select a location owned by this workspace."
            elif not location.is_active and (
                previous is None or getattr(previous, f"{field}_id") != location_id
            ):
                errors[field] = "Inactive locations cannot be newly assigned."
            elif country and country != location.country_code:
                errors[field] = "The facility must be in the selected country or territory."
            if location is not None:
                facility_country = location.country_code
        reference_field = f"{side}_reference_code"
        reference = location_references().get(getattr(instance, reference_field))
        if (
            reference
            and (country or facility_country)
            and (country or facility_country) != reference["country_code"]
        ):
            errors[reference_field] = "The reference must be in the selected country or territory."
    instance.location_review_required = any(
        getattr(instance, side)
        and not any(
            getattr(instance, f"{side}_{suffix}")
            for suffix in ("country_code", "location_id", "reference_code")
        )
        for side in ("origin", "destination")
    )
    if errors:
        raise ValidationError(errors)
