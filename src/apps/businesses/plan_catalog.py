from __future__ import annotations

PUBLIC_PAID_PLAN_SLUGS: tuple[str, ...] = ("starter", "pro", "business")
PUBLIC_PAID_PLAN_ORDERING: tuple[str, ...] = PUBLIC_PAID_PLAN_SLUGS
PUBLIC_PAID_PLAN_SLUG_SET = frozenset(PUBLIC_PAID_PLAN_SLUGS)
DEFAULT_PUBLIC_PAID_PLAN_SLUG = "pro"
STANDARD_TRIAL_DAYS = 14
PUBLIC_BILLING_INTERVALS: tuple[str, ...] = ("monthly", "yearly")
PUBLIC_BILLING_INTERVAL_LABELS: dict[str, str] = {
    "monthly": "month",
    "yearly": "year",
}
DEFAULT_PUBLIC_BILLING_INTERVAL = "monthly"
PUBLIC_PRICING_CURRENCIES: tuple[str, ...] = ("usd", "eur")
DEFAULT_PUBLIC_PRICING_CURRENCY = "usd"
PUBLIC_PRICING_CURRENCY_SESSION_KEY = "motionmate_pricing_currency"
PUBLIC_PRICING_CURRENCY_QUERY_PARAM = "currency"
PUBLIC_PRICING_CURRENCY_FORM_FIELD = "pricing_currency"
PUBLIC_PRICING_CURRENCY_LABELS: dict[str, str] = {
    "usd": "International",
    "eur": "Europe",
}
PUBLIC_PRICING_CURRENCY_DISPLAY: dict[str, str] = {
    "usd": "International/USD",
    "eur": "Europe/EUR",
}


def normalize_plan_slug(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def normalize_public_paid_plan_slug(value: object | None) -> str | None:
    normalized_slug = normalize_plan_slug(value)
    if normalized_slug in PUBLIC_PAID_PLAN_SLUG_SET:
        return normalized_slug
    return None


def is_public_paid_plan_slug(value: object | None) -> bool:
    return normalize_public_paid_plan_slug(value) is not None


def public_paid_plan_slug_or_default(value: object | None) -> str:
    return normalize_public_paid_plan_slug(value) or DEFAULT_PUBLIC_PAID_PLAN_SLUG


def normalize_billing_interval(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def normalize_public_billing_interval(value: object | None) -> str | None:
    normalized_interval = normalize_billing_interval(value)
    if normalized_interval in PUBLIC_BILLING_INTERVALS:
        return normalized_interval
    return None


def is_public_billing_interval(value: object | None) -> bool:
    return normalize_public_billing_interval(value) is not None


def public_billing_interval_or_default(value: object | None) -> str:
    return normalize_public_billing_interval(value) or DEFAULT_PUBLIC_BILLING_INTERVAL


def normalize_public_pricing_currency(value: object | None) -> str | None:
    if value is None:
        return None
    normalized_currency = str(value).strip().lower()
    if normalized_currency in PUBLIC_PRICING_CURRENCIES:
        return normalized_currency
    return None


def public_pricing_currency_or_default(value: object | None) -> str:
    return normalize_public_pricing_currency(value) or DEFAULT_PUBLIC_PRICING_CURRENCY


def public_pricing_currency_label(value: object | None) -> str:
    currency = public_pricing_currency_or_default(value)
    return PUBLIC_PRICING_CURRENCY_LABELS[currency]


def public_pricing_currency_display(value: object | None) -> str:
    currency = public_pricing_currency_or_default(value)
    return PUBLIC_PRICING_CURRENCY_DISPLAY[currency]
