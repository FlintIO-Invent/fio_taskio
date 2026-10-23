"""Read-only staged tier Price validation; never authorizes checkout or provisioning."""

from collections.abc import Mapping

from django.conf import settings

from apps.businesses.stripe_config import StripeConfigurationError, get_stripe_mode

# Approved Block B annual amounts in EUR cents; no USD amount is approved.
TIER_YEARLY_EUR_CENTS = {
    "logistics-core": 170000,
    "logistics-growth": 230000,
    "logistics-scale": 300000,
}


def configured_tier_prices(*, plan_slug=None) -> dict[tuple[str, str, str], str]:
    """Check all tiers for the audit command, or one tier for a billing operation."""
    configured = getattr(settings, "STRIPE_LOGISTICS_TIER_PRICE_ID_MAP", {})
    expected_keys = {(slug, "yearly", "eur") for slug in TIER_YEARLY_EUR_CENTS}
    if (
        not isinstance(configured, Mapping)
        or not set(configured).issubset(expected_keys)
        or (plan_slug is None and set(configured) != expected_keys)
        or (plan_slug is not None and plan_slug not in TIER_YEARLY_EUR_CENTS)
    ):
        raise StripeConfigurationError("Configure exactly the three Logistics annual EUR Prices.")
    selected_keys = expected_keys if plan_slug is None else {(plan_slug, "yearly", "eur")}
    prices = {}
    legacy = getattr(settings, "STRIPE_PRICE_ID_MAP", {})
    if not isinstance(legacy, Mapping):
        raise StripeConfigurationError("The existing Stripe Price mapping is invalid.")
    used = {str(value).strip() for value in legacy.values() if value}
    tier_ids = [value.strip() for value in configured.values() if isinstance(value, str)]
    for key in sorted(selected_keys):
        value = configured.get(key)
        price_id = value.strip() if isinstance(value, str) else ""
        if not price_id.startswith("price_") or len(price_id) <= len("price_"):
            raise StripeConfigurationError(
                f"Configure a price_ ID for {key[0]} yearly EUR.",
                code="logistics_tier_price_missing",
            )
        if price_id in used or tier_ids.count(price_id) > 1:
            raise StripeConfigurationError(
                "Each Logistics tier requires a distinct Stripe Price, unused by other offerings.",
                code="logistics_tier_price_duplicate",
            )
        prices[key] = price_id
        used.add(price_id)
    return prices


def validate_tier_stripe_price(
    *, plan_slug, stripe_client, currency="eur", billing_interval="yearly"
) -> str:
    """Retrieve only; prove tier identity, mode and exact commercial dimensions."""
    if plan_slug not in TIER_YEARLY_EUR_CENTS or currency != "eur" or billing_interval != "yearly":
        raise StripeConfigurationError("Only Core/Growth/Scale annual EUR Prices are supported.")
    price_id = configured_tier_prices(plan_slug=plan_slug)[(plan_slug, billing_interval, currency)]
    mode = get_stripe_mode()
    if mode == "disabled":
        raise StripeConfigurationError("Stripe is disabled.", code="stripe_disabled")
    if mode == "live" and settings.MOTIONMATE_ENVIRONMENT != "production":
        raise StripeConfigurationError(
            "Logistics Price verification requires TEST keys outside Production.",
            code="logistics_test_mode_required",
        )
    try:
        price = stripe_client.Price.retrieve(price_id)
        if hasattr(price, "to_dict_recursive"):
            price = price.to_dict_recursive()
        elif hasattr(price, "to_dict"):
            price = price.to_dict()
    except Exception as exc:
        raise StripeConfigurationError(
            "The Logistics tier Stripe Price could not be verified.",
            code="stripe_price_verification_failed",
        ) from exc
    validate_tier_price_data(plan_slug=plan_slug, price=price, mode=mode)
    return price_id


def require_tier_test_mode():
    if get_stripe_mode() != "test":
        raise StripeConfigurationError(
            "Logistics tier billing requires Stripe TEST keys.", code="logistics_test_mode_required"
        )


def validate_tier_price_data(*, plan_slug, price, mode="test"):
    price_id = configured_tier_prices(plan_slug=plan_slug)[(plan_slug, "yearly", "eur")]
    if hasattr(price, "to_dict_recursive"):
        price = price.to_dict_recursive()
    elif hasattr(price, "to_dict"):
        price = price.to_dict()
    if not isinstance(price, Mapping):
        raise StripeConfigurationError("The Logistics tier Stripe Price is invalid.")
    recurring = price.get("recurring")
    if (
        price.get("id") != price_id
        or price.get("active") is not True
        or price.get("livemode") is not (mode == "live")
        or price.get("currency") != "eur"
        or price.get("type") != "recurring"
        or price.get("billing_scheme") != "per_unit"
        or type(price.get("unit_amount")) is not int
        or price.get("unit_amount") != TIER_YEARLY_EUR_CENTS[plan_slug]
        or not isinstance(recurring, Mapping)
        or recurring.get("interval") != "year"
        or type(recurring.get("interval_count")) is not int
        or recurring.get("interval_count") != 1
        or recurring.get("usage_type") != "licensed"
    ):
        raise StripeConfigurationError(
            "Logistics tier Price must match its configured ID, active mode, annual EUR amount and licensed per-unit billing.",
            code="logistics_tier_price_invalid",
        )
