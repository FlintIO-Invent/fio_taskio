"""Offering policy shared by billing entry points, independent of HTTP and Stripe."""

from dataclasses import dataclass

from django.conf import settings

from .plan_catalog import (
    LOGISTICS_TIER_SLUGS,
    PUBLIC_PAID_PLAN_SLUGS,
    STANDARD_TRIAL_DAYS,
    normalize_plan_slug,
)


@dataclass(frozen=True)
class BillingOffering:
    family: str
    intervals: tuple[str, ...]
    trial_days: int
    checkout_enabled: bool = True
    test_checkout_enabled: bool = False
    historical_only: bool = False


BILLING_OFFERINGS = {
    **{
        slug: BillingOffering("SERVICE", ("monthly", "yearly"), STANDARD_TRIAL_DAYS)
        for slug in PUBLIC_PAID_PLAN_SLUGS
    },
    # Historical billing/entitlements only. Checkout rejects this retired slug;
    # keep it recognized here for existing contracts, grace and old webhooks.
    "logistics": BillingOffering(
        "LOGISTICS", ("yearly",), 0, checkout_enabled=False, historical_only=True
    ),
    **{
        slug: BillingOffering(
            "LOGISTICS", ("yearly",), 0, checkout_enabled=False, test_checkout_enabled=True
        )
        for slug in LOGISTICS_TIER_SLUGS
    },
}
BILLABLE_PLAN_SLUGS = tuple(
    slug
    for slug, offering in BILLING_OFFERINGS.items()
    if offering.checkout_enabled or offering.historical_only
)


def logistics_local_billing_bypass_enabled() -> bool:
    """Environment-only permission; never accepts request or persisted tenant inputs."""
    return bool(
        getattr(settings, "LOGISTICS_LOCAL_BILLING_BYPASS", False)
        and settings.DEBUG
        and getattr(settings, "MOTIONMATE_ENVIRONMENT", "") == "local"
    )


def billing_offering(plan_slug: object) -> BillingOffering | None:
    return BILLING_OFFERINGS.get(normalize_plan_slug(plan_slug))


def plan_matches_business(business, plan) -> bool:
    return (
        business is not None
        and plan is not None
        and plan.family in {"SERVICE", "LOGISTICS"}
        and business.vertical == plan.family
    )


def is_stripe_billable_plan(plan) -> bool:
    offering = billing_offering(plan.slug) if plan is not None else None
    return bool(
        offering
        and (
            offering.checkout_enabled or offering.test_checkout_enabled or offering.historical_only
        )
        and offering.family == plan.family
    )


def offering_allows_interval(plan_slug: object, interval: object) -> bool:
    offering = billing_offering(plan_slug)
    return offering is not None and str(interval or "").strip().lower() in offering.intervals
