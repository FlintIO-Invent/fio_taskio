from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

EUROPEAN_DECIMAL_LOCALE_PREFIXES = (
    "nl",
    "de",
    "fr",
    "it",
    "es",
    "pt",
    "be",
)
EUROPEAN_DECIMAL_COUNTRIES = {
    "netherlands",
    "the netherlands",
    "nl",
    "nederland",
    "belgium",
    "be",
    "germany",
    "de",
    "france",
    "fr",
    "spain",
    "es",
    "italy",
    "it",
    "portugal",
    "pt",
}
CURRENCY_SYMBOLS = {
    "USD": "$",
    "XCD": "$",
    "EUR": "€",
    "ANG": "ƒ",
}
NETHERLANDS_ADDRESS_COUNTRIES = {
    "netherlands",
    "the netherlands",
    "nl",
    "nederland",
}
EUROPE_PRICING_COUNTRIES = {
    "albania",
    "al",
    "andorra",
    "ad",
    "armenia",
    "am",
    "austria",
    "at",
    "azerbaijan",
    "az",
    "belarus",
    "by",
    "belgium",
    "be",
    "bosnia",
    "bosnia and herzegovina",
    "ba",
    "bulgaria",
    "bg",
    "croatia",
    "hr",
    "cyprus",
    "cy",
    "czech republic",
    "czechia",
    "cz",
    "denmark",
    "dk",
    "estonia",
    "ee",
    "finland",
    "fi",
    "france",
    "fr",
    "georgia",
    "ge",
    "germany",
    "de",
    "greece",
    "gr",
    "hungary",
    "hu",
    "iceland",
    "is",
    "ireland",
    "ie",
    "italy",
    "it",
    "kosovo",
    "xk",
    "latvia",
    "lv",
    "liechtenstein",
    "li",
    "lithuania",
    "lt",
    "luxembourg",
    "lu",
    "malta",
    "mt",
    "moldova",
    "md",
    "monaco",
    "mc",
    "montenegro",
    "me",
    "netherlands",
    "the netherlands",
    "nederland",
    "nl",
    "north macedonia",
    "macedonia",
    "mk",
    "norway",
    "no",
    "poland",
    "pl",
    "portugal",
    "pt",
    "romania",
    "ro",
    "san marino",
    "sm",
    "serbia",
    "rs",
    "slovakia",
    "sk",
    "slovenia",
    "si",
    "spain",
    "es",
    "sweden",
    "se",
    "switzerland",
    "ch",
    "turkey",
    "turkiye",
    "tr",
    "ukraine",
    "ua",
    "united kingdom",
    "uk",
    "great britain",
    "gb",
    "england",
    "scotland",
    "wales",
    "northern ireland",
    "vatican city",
    "va",
    "europe",
    "eu",
    "european union",
}
SINT_MAARTEN_ADDRESS_COUNTRIES = {
    "sint maarten",
    "saint maarten",
    "st maarten",
    "st martin",
    "saint martin",
    "sxm",
}
CARIBBEAN_ADDRESS_COUNTRIES = {
    *SINT_MAARTEN_ADDRESS_COUNTRIES,
    "anguilla",
    "antigua and barbuda",
    "aruba",
    "bahamas",
    "barbados",
    "bonaire",
    "british virgin islands",
    "caribbean netherlands",
    "cayman islands",
    "curacao",
    "dominica",
    "dominican republic",
    "grenada",
    "guadeloupe",
    "haiti",
    "jamaica",
    "martinique",
    "montserrat",
    "puerto rico",
    "saba",
    "saint barthelemy",
    "saint eustatius",
    "saint kitts and nevis",
    "saint lucia",
    "saint vincent and the grenadines",
    "st barthelemy",
    "st eustatius",
    "st kitts and nevis",
    "st lucia",
    "st vincent and the grenadines",
    "trinidad and tobago",
    "turks and caicos",
    "u s virgin islands",
    "us virgin islands",
    "virgin islands",
}
EMPTY_POSTAL_VALUES = {"", "-", "n/a", "na", "none", "not applicable"}
PUBLIC_ADDRESS_COUNTRY_CHOICES = (
    ("", "Select country"),
    ("Sint Maarten", "Sint Maarten"),
    ("Saint Martin", "Saint Martin"),
    ("Netherlands", "Netherlands"),
    ("Anguilla", "Anguilla"),
    ("Antigua and Barbuda", "Antigua and Barbuda"),
    ("Aruba", "Aruba"),
    ("Bahamas", "Bahamas"),
    ("Barbados", "Barbados"),
    ("Bonaire", "Bonaire"),
    ("British Virgin Islands", "British Virgin Islands"),
    ("Caribbean Netherlands", "Caribbean Netherlands"),
    ("Cayman Islands", "Cayman Islands"),
    ("Curacao", "Curacao"),
    ("Dominica", "Dominica"),
    ("Dominican Republic", "Dominican Republic"),
    ("Grenada", "Grenada"),
    ("Guadeloupe", "Guadeloupe"),
    ("Haiti", "Haiti"),
    ("Jamaica", "Jamaica"),
    ("Martinique", "Martinique"),
    ("Montserrat", "Montserrat"),
    ("Puerto Rico", "Puerto Rico"),
    ("Saba", "Saba"),
    ("Saint Barthelemy", "Saint Barthelemy"),
    ("Saint Eustatius", "Saint Eustatius"),
    ("Saint Kitts and Nevis", "Saint Kitts and Nevis"),
    ("Saint Lucia", "Saint Lucia"),
    ("Saint Vincent and the Grenadines", "Saint Vincent and the Grenadines"),
    ("Trinidad and Tobago", "Trinidad and Tobago"),
    ("Turks and Caicos", "Turks and Caicos"),
    ("U.S. Virgin Islands", "U.S. Virgin Islands"),
)


def _normalized_locale(business) -> str:
    return (getattr(business, "default_locale", "") or "").strip().replace("-", "_").lower()


def _normalized_country(business) -> str:
    return (getattr(business, "country", "") or "").strip().lower()


def normalize_country_key(value_or_business) -> str:
    raw_country = (getattr(value_or_business, "country", value_or_business) or "").strip()
    normalized = (
        unicodedata.normalize("NFKD", raw_country).encode("ascii", "ignore").decode("ascii").lower()
    )
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return normalized


def uses_netherlands_address_format(value_or_business) -> bool:
    return normalize_country_key(value_or_business) in NETHERLANDS_ADDRESS_COUNTRIES


def uses_europe_pricing_region(value_or_business) -> bool:
    return normalize_country_key(value_or_business) in EUROPE_PRICING_COUNTRIES


def uses_caribbean_address_format(value_or_business) -> bool:
    return normalize_country_key(value_or_business) in CARIBBEAN_ADDRESS_COUNTRIES


def uses_sint_maarten_districts(value_or_business) -> bool:
    return normalize_country_key(value_or_business) in SINT_MAARTEN_ADDRESS_COUNTRIES


def normalize_postal_code_for_country(value: str | None, country_or_business=None) -> str:
    postal_code = (value or "").strip()
    if postal_code.lower() in EMPTY_POSTAL_VALUES:
        return ""

    if uses_netherlands_address_format(country_or_business):
        normalized = re.sub(r"\s+", "", postal_code).upper()
        match = re.fullmatch(r"(\d{4})([A-Z]{2})", normalized)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return postal_code.upper()

    return postal_code


def _clean_address_part(value: str | None) -> str:
    return (value or "").strip()


def _clean_postal_for_display(value: str | None, country_or_business=None) -> str:
    return normalize_postal_code_for_country(value, country_or_business)


def _append_country_line(lines: list[str], country: str) -> None:
    if country and (lines or country):
        lines.append(country)


def format_business_address_lines(
    *,
    address_line_1: str | None = "",
    address_line_2: str | None = "",
    city: str | None = "",
    region: str | None = "",
    postal_code: str | None = "",
    country: str | None = "",
    legacy_address: str | None = "",
) -> list[str]:
    country_value = _clean_address_part(country)
    postal_value = _clean_postal_for_display(postal_code, country_value)
    line_1 = _clean_address_part(address_line_1)
    line_2 = _clean_address_part(address_line_2)
    city_value = _clean_address_part(city)
    region_value = _clean_address_part(region)

    lines = [part for part in [line_1, line_2] if part]

    if uses_netherlands_address_format(country_value):
        locality = " ".join(part for part in [postal_value, city_value] if part)
        if not locality:
            locality = region_value
        if locality:
            lines.append(locality)
        _append_country_line(lines, country_value)
    elif uses_caribbean_address_format(country_value):
        locality_parts = []
        for part in [city_value, region_value]:
            if not part:
                continue
            existing_parts = {item.lower() for item in locality_parts}
            if part.lower() == country_value.lower() or part.lower() in existing_parts:
                continue
            else:
                locality_parts.append(part)
        if locality_parts:
            lines.append(", ".join(locality_parts))
        _append_country_line(lines, country_value)
        if postal_value:
            lines.append(postal_value)
    else:
        locality = ", ".join(part for part in [city_value, region_value] if part)
        if locality:
            lines.append(locality)
        postal_country = " ".join(part for part in [postal_value, country_value] if part)
        if postal_country and (lines or postal_value):
            lines.append(postal_country)

    if lines:
        return lines

    return [line.strip() for line in (legacy_address or "").splitlines() if line.strip()]


def format_crm_address_lines(
    *,
    street_address: str | None = "",
    locality: str | None = "",
    country: str | None = "",
    postal_code: str | None = "",
) -> list[str]:
    country_value = _clean_address_part(country)
    postal_value = _clean_postal_for_display(postal_code, country_value)
    street_value = _clean_address_part(street_address)
    locality_value = _clean_address_part(locality)

    lines = []
    if street_value:
        lines.append(street_value)

    if uses_netherlands_address_format(country_value):
        postal_locality = " ".join(part for part in [postal_value, locality_value] if part)
        if postal_locality:
            lines.append(postal_locality)
        _append_country_line(lines, country_value)
    elif uses_caribbean_address_format(country_value):
        if locality_value:
            lines.append(locality_value)
        _append_country_line(lines, country_value)
        if postal_value:
            lines.append(postal_value)
    else:
        locality_line = ", ".join(part for part in [locality_value, country_value] if part)
        if locality_line:
            lines.append(locality_line)
        if postal_value:
            lines.append(postal_value)

    return lines


def format_crm_address(
    *,
    street_address: str | None = "",
    locality: str | None = "",
    country: str | None = "",
    postal_code: str | None = "",
) -> str:
    return ", ".join(
        format_crm_address_lines(
            street_address=street_address,
            locality=locality,
            country=country,
            postal_code=postal_code,
        )
    )


def uses_comma_decimal_format(business) -> bool:
    locale = _normalized_locale(business)
    if locale:
        language = locale.split("_", 1)[0]
        if language in EUROPEAN_DECIMAL_LOCALE_PREFIXES:
            return True
        if language == "en":
            return False

    return _normalized_country(business) in EUROPEAN_DECIMAL_COUNTRIES


def currency_symbol_or_code(business) -> str:
    currency_code = (getattr(business, "currency", "") or "USD").strip().upper()
    return CURRENCY_SYMBOLS.get(currency_code, currency_code)


def localized_price_input_example(business) -> str:
    if uses_comma_decimal_format(business):
        return "1.234,56"
    return "1,234.56"


def format_decimal_for_business(value: Decimal | int | str, business) -> str:
    try:
        amount = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError):
        amount = Decimal("0.00")

    standard = f"{amount:,.2f}"
    if uses_comma_decimal_format(business):
        return standard.replace(",", "_").replace(".", ",").replace("_", ".")
    return standard


def format_money_for_business(value: Decimal | int | str, business) -> str:
    return f"{currency_symbol_or_code(business)}{format_decimal_for_business(value, business)}"


def parse_localized_decimal(value, business=None) -> Decimal:
    raw_value = str(value or "").strip()
    if not raw_value:
        raise InvalidOperation

    normalized_value = raw_value.replace(" ", "")
    comma_count = normalized_value.count(",")
    dot_count = normalized_value.count(".")

    if comma_count and dot_count:
        if uses_comma_decimal_format(business):
            normalized_value = normalized_value.replace(".", "").replace(",", ".")
        else:
            normalized_value = normalized_value.replace(",", "")
    elif comma_count:
        last_group = normalized_value.rsplit(",", 1)[-1]
        if uses_comma_decimal_format(business) or len(last_group) in {1, 2}:
            normalized_value = normalized_value.replace(".", "").replace(",", ".")
        else:
            normalized_value = normalized_value.replace(",", "")
    elif dot_count > 1 and uses_comma_decimal_format(business):
        normalized_value = normalized_value.replace(".", "")

    return Decimal(normalized_value)
