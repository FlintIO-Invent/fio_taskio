from __future__ import annotations

PUBLIC_PAID_PLAN_SLUGS: tuple[str, ...] = ("starter", "pro", "business")
PUBLIC_PAID_PLAN_ORDERING: tuple[str, ...] = PUBLIC_PAID_PLAN_SLUGS
PUBLIC_PAID_PLAN_SLUG_SET = frozenset(PUBLIC_PAID_PLAN_SLUGS)
DEFAULT_PUBLIC_PAID_PLAN_SLUG = "pro"
STANDARD_TRIAL_DAYS = 14
PUBLIC_BILLING_INTERVALS: tuple[str, ...] = ("monthly", "yearly")
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
