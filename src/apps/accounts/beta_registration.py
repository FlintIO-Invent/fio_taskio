import secrets

from django.conf import settings

BETA_PLAN_SLUG = "beta"
BETA_PLAN_DISPLAY_NAME = "Beta — Free Early Access (Limited Availability)"


def get_configured_beta_registration_token() -> str:
    return (getattr(settings, "BETA_REGISTRATION_TOKEN", "") or "").strip()


def beta_registration_token_is_configured() -> bool:
    return bool(get_configured_beta_registration_token())


def is_valid_beta_registration_token(supplied_token: str) -> bool:
    configured_token = get_configured_beta_registration_token()
    supplied_token = (supplied_token or "").strip()
    if not configured_token or not supplied_token:
        return False

    return secrets.compare_digest(supplied_token, configured_token)
