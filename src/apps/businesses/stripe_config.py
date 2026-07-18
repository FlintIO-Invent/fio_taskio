from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import stripe
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .plan_catalog import (
    PUBLIC_BILLING_INTERVALS,
    PUBLIC_PAID_PLAN_SLUGS,
    PUBLIC_PRICING_CURRENCIES,
    normalize_plan_slug,
    normalize_public_paid_plan_slug,
)

StripeMode = Literal["disabled", "test", "live"]
StripePriceKey = tuple[str, str, str]

STRIPE_CHECK_MISSING_PUBLISHABLE_KEY = "motionmate_stripe.E001"
STRIPE_CHECK_MISSING_SECRET_KEY = "motionmate_stripe.E002"
STRIPE_CHECK_MISSING_WEBHOOK_SECRET = "motionmate_stripe.E003"
STRIPE_CHECK_INVALID_PUBLISHABLE_KEY = "motionmate_stripe.E004"
STRIPE_CHECK_INVALID_SECRET_KEY = "motionmate_stripe.E005"
STRIPE_CHECK_MIXED_KEY_MODES = "motionmate_stripe.E006"
STRIPE_CHECK_INVALID_WEBHOOK_SECRET = "motionmate_stripe.E007"
STRIPE_CHECK_MISSING_PRICE_ID = "motionmate_stripe.E008"
STRIPE_CHECK_INVALID_PRICE_ID = "motionmate_stripe.E009"
STRIPE_CHECK_UNKNOWN_PLAN = "motionmate_stripe.E010"
STRIPE_CHECK_UNSUPPORTED_INTERVAL = "motionmate_stripe.E011"
STRIPE_CHECK_UNSUPPORTED_CURRENCY = "motionmate_stripe.E012"
STRIPE_CHECK_BETA_PLAN = "motionmate_stripe.E013"
STRIPE_CHECK_INVALID_PRICE_MAPPING_KEY = "motionmate_stripe.E014"

_BETA_PLAN_SLUG = "beta"
_PRICE_ID_PREFIX = "price_"


@dataclass(frozen=True)
class StripeConfigurationIssue:
    id: str
    message: str


class StripeConfigurationError(ImproperlyConfigured):
    """Raised when Stripe subscription configuration is missing or inconsistent."""


def _clean_setting(value: object | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def is_stripe_enabled() -> bool:
    return bool(getattr(settings, "STRIPE_ENABLED", False))


def get_stripe_publishable_key() -> str | None:
    return _clean_setting(getattr(settings, "STRIPE_PUBLISHABLE_KEY", ""))


def get_stripe_secret_key() -> str | None:
    return _clean_setting(getattr(settings, "STRIPE_SECRET_KEY", ""))


def get_stripe_webhook_secret() -> str | None:
    return _clean_setting(getattr(settings, "STRIPE_WEBHOOK_SECRET", ""))


def _mode_for_publishable_key(value: str) -> Literal["test", "live"] | None:
    if value.startswith("pk_test_"):
        return "test"
    if value.startswith("pk_live_"):
        return "live"
    return None


def _mode_for_secret_key(value: str) -> Literal["test", "live"] | None:
    if value.startswith("sk_test_"):
        return "test"
    if value.startswith("sk_live_"):
        return "live"
    return None


def get_stripe_mode() -> StripeMode:
    if not is_stripe_enabled():
        return "disabled"

    publishable_key = get_stripe_publishable_key()
    secret_key = get_stripe_secret_key()
    if publishable_key is None or secret_key is None:
        raise StripeConfigurationError(
            "Stripe publishable and secret keys are required when Stripe is enabled."
        )

    publishable_mode = _mode_for_publishable_key(publishable_key)
    if publishable_mode is None:
        raise StripeConfigurationError("Stripe publishable key must start with pk_test_ or pk_live_.")

    secret_mode = _mode_for_secret_key(secret_key)
    if secret_mode is None:
        raise StripeConfigurationError("Stripe secret key must start with sk_test_ or sk_live_.")

    if publishable_mode != secret_mode:
        raise StripeConfigurationError("Stripe publishable and secret keys use different modes.")

    return publishable_mode


def _raw_price_id_map() -> Mapping[Any, Any]:
    configured_map = getattr(settings, "STRIPE_PRICE_ID_MAP", {}) or {}
    if isinstance(configured_map, Mapping):
        return configured_map
    return {}


def _coerce_price_key(raw_key: object) -> tuple[object, object, object] | None:
    if isinstance(raw_key, tuple | list) and len(raw_key) == 3:
        return raw_key[0], raw_key[1], raw_key[2]
    return None


def _normalize_interval(value: object) -> str:
    return str(value).strip().lower()


def _normalize_currency(value: object) -> str:
    return str(value).strip().lower()


def _normalize_price_dimensions(
    *,
    plan_slug: object,
    billing_interval: object,
    currency: object,
) -> StripePriceKey:
    normalized_plan = normalize_plan_slug(plan_slug)
    if normalized_plan == _BETA_PLAN_SLUG:
        raise StripeConfigurationError("Beta is not a public Stripe subscription plan.")

    public_plan = normalize_public_paid_plan_slug(normalized_plan)
    if public_plan is None:
        raise StripeConfigurationError("Unsupported Motionmate public plan for Stripe Price mapping.")

    normalized_interval = _normalize_interval(billing_interval)
    if normalized_interval not in PUBLIC_BILLING_INTERVALS:
        raise StripeConfigurationError("Unsupported Stripe billing interval.")

    normalized_currency = _normalize_currency(currency)
    if normalized_currency not in PUBLIC_PRICING_CURRENCIES:
        raise StripeConfigurationError("Unsupported Stripe Price currency.")

    return public_plan, normalized_interval, normalized_currency


def _configured_price_lookup() -> dict[StripePriceKey, str]:
    price_lookup: dict[StripePriceKey, str] = {}
    for raw_key, raw_price_id in _raw_price_id_map().items():
        key_parts = _coerce_price_key(raw_key)
        if key_parts is None:
            continue

        try:
            normalized_key = _normalize_price_dimensions(
                plan_slug=key_parts[0],
                billing_interval=key_parts[1],
                currency=key_parts[2],
            )
        except StripeConfigurationError:
            continue

        price_id = _clean_setting(raw_price_id)
        if price_id is not None:
            price_lookup[normalized_key] = price_id
    return price_lookup


def _is_valid_price_id(value: str) -> bool:
    return value.startswith(_PRICE_ID_PREFIX)


def get_stripe_price_id(
    *,
    plan_slug: object,
    billing_interval: object,
    currency: object,
) -> str:
    price_key = _normalize_price_dimensions(
        plan_slug=plan_slug,
        billing_interval=billing_interval,
        currency=currency,
    )
    price_id = _configured_price_lookup().get(price_key)
    if price_id is None:
        plan, interval, normalized_currency = price_key
        raise StripeConfigurationError(
            f"Stripe Price ID is not configured for {plan} {interval} {normalized_currency}."
        )
    if not _is_valid_price_id(price_id):
        raise StripeConfigurationError("Configured Stripe Price ID must start with price_.")
    return price_id


def _iter_supported_price_keys() -> tuple[StripePriceKey, ...]:
    return tuple(
        (plan_slug, billing_interval, currency)
        for plan_slug in PUBLIC_PAID_PLAN_SLUGS
        for billing_interval in PUBLIC_BILLING_INTERVALS
        for currency in PUBLIC_PRICING_CURRENCIES
    )


def _validate_price_mapping(*, require_all_supported: bool) -> list[StripeConfigurationIssue]:
    issues: list[StripeConfigurationIssue] = []
    raw_map = getattr(settings, "STRIPE_PRICE_ID_MAP", {}) or {}
    if not isinstance(raw_map, Mapping):
        issues.append(
            StripeConfigurationIssue(
                STRIPE_CHECK_INVALID_PRICE_MAPPING_KEY,
                "Stripe Price mapping must be a dictionary keyed by plan, billing interval, and currency.",
            )
        )
        raw_map = {}

    valid_price_lookup: dict[StripePriceKey, str] = {}
    for raw_key, raw_price_id in raw_map.items():
        key_parts = _coerce_price_key(raw_key)
        if key_parts is None:
            issues.append(
                StripeConfigurationIssue(
                    STRIPE_CHECK_INVALID_PRICE_MAPPING_KEY,
                    "Stripe Price mapping keys must use plan, billing interval, and currency.",
                )
            )
            continue

        raw_plan, raw_interval, raw_currency = key_parts
        normalized_plan = normalize_plan_slug(raw_plan)
        normalized_interval = _normalize_interval(raw_interval)
        normalized_currency = _normalize_currency(raw_currency)
        key_is_supported = True

        if normalized_plan == _BETA_PLAN_SLUG:
            issues.append(
                StripeConfigurationIssue(
                    STRIPE_CHECK_BETA_PLAN,
                    "Beta cannot be configured as a public Stripe subscription plan.",
                )
            )
            key_is_supported = False
        elif normalized_plan not in PUBLIC_PAID_PLAN_SLUGS:
            issues.append(
                StripeConfigurationIssue(
                    STRIPE_CHECK_UNKNOWN_PLAN,
                    "Stripe Price mapping contains an unknown public plan slug.",
                )
            )
            key_is_supported = False

        if normalized_interval not in PUBLIC_BILLING_INTERVALS:
            issues.append(
                StripeConfigurationIssue(
                    STRIPE_CHECK_UNSUPPORTED_INTERVAL,
                    "Stripe Price mapping contains an unsupported billing interval.",
                )
            )
            key_is_supported = False

        if normalized_currency not in PUBLIC_PRICING_CURRENCIES:
            issues.append(
                StripeConfigurationIssue(
                    STRIPE_CHECK_UNSUPPORTED_CURRENCY,
                    "Stripe Price mapping contains an unsupported currency.",
                )
            )
            key_is_supported = False

        price_id = _clean_setting(raw_price_id)
        if price_id is not None and not _is_valid_price_id(price_id):
            issues.append(
                StripeConfigurationIssue(
                    STRIPE_CHECK_INVALID_PRICE_ID,
                    "Configured Stripe Price IDs must start with price_.",
                )
            )
            key_is_supported = False

        if key_is_supported and price_id is not None:
            valid_price_lookup[(normalized_plan, normalized_interval, normalized_currency)] = price_id

    if require_all_supported:
        for plan_slug, billing_interval, currency in _iter_supported_price_keys():
            if (plan_slug, billing_interval, currency) not in valid_price_lookup:
                issues.append(
                    StripeConfigurationIssue(
                        STRIPE_CHECK_MISSING_PRICE_ID,
                        f"Stripe Price ID is not configured for {plan_slug} {billing_interval} {currency}.",
                    )
                )

    return issues


def validate_stripe_configuration() -> list[StripeConfigurationIssue]:
    if not is_stripe_enabled():
        return []

    issues: list[StripeConfigurationIssue] = []
    publishable_key = get_stripe_publishable_key()
    secret_key = get_stripe_secret_key()
    webhook_secret = get_stripe_webhook_secret()
    publishable_mode = None
    secret_mode = None

    if publishable_key is None:
        issues.append(
            StripeConfigurationIssue(
                STRIPE_CHECK_MISSING_PUBLISHABLE_KEY,
                "STRIPE_PUBLISHABLE_KEY is required when Stripe is enabled.",
            )
        )
    else:
        publishable_mode = _mode_for_publishable_key(publishable_key)
        if publishable_mode is None:
            issues.append(
                StripeConfigurationIssue(
                    STRIPE_CHECK_INVALID_PUBLISHABLE_KEY,
                    "Stripe publishable key must start with pk_test_ or pk_live_.",
                )
            )

    if secret_key is None:
        issues.append(
            StripeConfigurationIssue(
                STRIPE_CHECK_MISSING_SECRET_KEY,
                "STRIPE_SECRET_KEY is required when Stripe is enabled.",
            )
        )
    else:
        secret_mode = _mode_for_secret_key(secret_key)
        if secret_mode is None:
            issues.append(
                StripeConfigurationIssue(
                    STRIPE_CHECK_INVALID_SECRET_KEY,
                    "Stripe secret key must start with sk_test_ or sk_live_.",
                )
            )

    if publishable_mode is not None and secret_mode is not None and publishable_mode != secret_mode:
        issues.append(
            StripeConfigurationIssue(
                STRIPE_CHECK_MIXED_KEY_MODES,
                "Stripe publishable and secret keys use different modes.",
            )
        )

    if webhook_secret is None:
        issues.append(
            StripeConfigurationIssue(
                STRIPE_CHECK_MISSING_WEBHOOK_SECRET,
                "STRIPE_WEBHOOK_SECRET is required when Stripe is enabled.",
            )
        )
    elif not webhook_secret.startswith("whsec_"):
        issues.append(
            StripeConfigurationIssue(
                STRIPE_CHECK_INVALID_WEBHOOK_SECRET,
                "Stripe webhook secret must start with whsec_.",
            )
        )

    issues.extend(_validate_price_mapping(require_all_supported=True))
    return issues


def configure_stripe_sdk():
    if not is_stripe_enabled():
        raise StripeConfigurationError("Stripe subscription billing is disabled.")

    issues = validate_stripe_configuration()
    if issues:
        raise StripeConfigurationError(issues[0].message)

    secret_key = get_stripe_secret_key()
    if secret_key is None:
        raise StripeConfigurationError("STRIPE_SECRET_KEY is required when Stripe is enabled.")

    stripe.api_key = secret_key
    return stripe
