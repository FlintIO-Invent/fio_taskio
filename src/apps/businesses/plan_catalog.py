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
