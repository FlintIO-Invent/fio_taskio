"""Application tier selection, independent of disabled tier payment configuration."""

from django.core.exceptions import ValidationError

from apps.businesses.billing_policy import billing_offering
from apps.businesses.models import ClarivoPlan
from apps.businesses.plan_catalog import LOGISTICS_TIER_SLUGS

LEGACY_PLAN_SLUG = "logistics"


def selected_plan(slug, *, lock=False):
    if slug not in (LEGACY_PLAN_SLUG, *LOGISTICS_TIER_SLUGS):
        raise ValidationError({"selected_plan_slug": "Select a valid Logistics annual tier."})
    plans = ClarivoPlan.objects
    if lock:
        plans = plans.select_for_update()
    plan = plans.filter(slug=slug, family=ClarivoPlan.Family.LOGISTICS).first()
    offering = billing_offering(slug)
    if plan is None or offering is None or offering.intervals != ("yearly",):
        raise ValidationError({"selected_plan_slug": "The Logistics offering is unavailable."})
    # Legacy enrollment has always allowed staging an inactive offering.
    if slug != LEGACY_PLAN_SLUG and (
        not plan.is_active or not plan.has_complete_logistics_capacity
    ):
        raise ValidationError({"selected_plan_slug": "This Logistics tier is unavailable."})
    return plan
