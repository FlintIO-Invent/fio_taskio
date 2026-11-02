import secrets

from django.conf import settings
from django.db.models import Q

from apps.businesses.models import ClarivoPlan
from apps.businesses.plan_catalog import LOGISTICS_TIER_CAPACITY_FIELDS, LOGISTICS_TIER_SLUGS

FREE_TEST_TOKEN_SETTING_BY_PLAN = {
    "starter": "FREE_TEST_STARTER_TOKEN",
    "pro": "FREE_TEST_PRO_TOKEN",
    "business": "FREE_TEST_BUSINESS_TOKEN",
    "logistics-core": "FREE_TEST_LOGISTICS_CORE_TOKEN",
    "logistics-growth": "FREE_TEST_LOGISTICS_GROWTH_TOKEN",
    "logistics-scale": "FREE_TEST_LOGISTICS_SCALE_TOKEN",
}


def is_allowed_free_test_plan_slug(plan_slug: str) -> bool:
    return plan_slug in FREE_TEST_TOKEN_SETTING_BY_PLAN


def free_test_plan_queryset(plan_slug: str):
    """Use the same tier eligibility for link admission and form validation."""
    if not is_allowed_free_test_plan_slug(plan_slug):
        return ClarivoPlan.objects.none()
    plans = ClarivoPlan.objects.filter(slug=plan_slug)
    if plan_slug in LOGISTICS_TIER_SLUGS:
        plans = plans.filter(
            Q(is_active=True) | Q(logistics_free_test_enabled=True),
            family=ClarivoPlan.Family.LOGISTICS,
            **{f"{field}__isnull": False for field in LOGISTICS_TIER_CAPACITY_FIELDS},
        )
        return plans
    return plans.filter(is_active=True)


def get_configured_free_test_registration_token(plan_slug: str) -> str:
    setting_name = FREE_TEST_TOKEN_SETTING_BY_PLAN.get(plan_slug)
    if setting_name is None:
        return ""
    return (getattr(settings, setting_name, "") or "").strip()


def is_valid_free_test_registration_token(plan_slug: str, supplied_token: str) -> bool:
    configured_token = get_configured_free_test_registration_token(plan_slug)
    supplied_token = (supplied_token or "").strip()
    if not configured_token or not supplied_token:
        return False

    return secrets.compare_digest(supplied_token, configured_token)
