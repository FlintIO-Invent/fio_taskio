from __future__ import annotations

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


def _normalized_locale(business) -> str:
    return (getattr(business, "default_locale", "") or "").strip().replace("-", "_").lower()


def _normalized_country(business) -> str:
    return (getattr(business, "country", "") or "").strip().lower()


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
