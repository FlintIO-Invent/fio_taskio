import secrets

from django.conf import settings

from apps.businesses.plan_catalog import PUBLIC_PAID_PLAN_SLUG_SET

FREE_TEST_TOKEN_SETTING_BY_PLAN = {
    "starter": "FREE_TEST_STARTER_TOKEN",
    "pro": "FREE_TEST_PRO_TOKEN",
    "business": "FREE_TEST_BUSINESS_TOKEN",
}


def is_allowed_free_test_plan_slug(plan_slug: str) -> bool:
    return plan_slug in PUBLIC_PAID_PLAN_SLUG_SET


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
