"""Offering policy shared by billing entry points, independent of HTTP and Stripe."""

from dataclasses import dataclass

from .plan_catalog import PUBLIC_PAID_PLAN_SLUGS, STANDARD_TRIAL_DAYS, normalize_plan_slug


@dataclass(frozen=True)
class BillingOffering:
    family: str
    intervals: tuple[str, ...]
    trial_days: int


BILLING_OFFERINGS = {
    **{
        slug: BillingOffering("SERVICE", ("monthly", "yearly"), STANDARD_TRIAL_DAYS)
        for slug in PUBLIC_PAID_PLAN_SLUGS
    },
    "logistics": BillingOffering("LOGISTICS", ("yearly",), 0),
}
BILLABLE_PLAN_SLUGS = tuple(BILLING_OFFERINGS)


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
    return offering is not None and offering.family == plan.family


def offering_allows_interval(plan_slug: object, interval: object) -> bool:
    offering = billing_offering(plan_slug)
    return offering is not None and str(interval or "").strip().lower() in offering.intervals
