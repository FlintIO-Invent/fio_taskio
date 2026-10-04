"""Logistics admission and commercial checks around the shared Stripe pipeline."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.stripe_checkout import StripeCheckoutError, resume_trial_checkout_session
from apps.businesses.stripe_config import (
    StripeConfigurationError,
    configure_stripe_sdk,
    get_stripe_price_id,
    is_stripe_enabled,
    resolve_stripe_price_id,
)

from .models import LogisticsApplication


def require_checkout_enrollment(subscription, user):
    application = LogisticsApplication.objects.filter(business_id=subscription.business_id).first()
    if (
        application is None
        or application.status != LogisticsApplication.Status.APPROVED
        or application.approved_revision != application.revision
        or application.evaluated_revision != application.revision
        or application.converted_revision != application.revision
        or application.converted_at is None
        or application.enrolled_user_id is None
    ):
        raise StripeCheckoutError("Checkout requires a current approved Logistics enrollment.")
    if (
        not user.is_authenticated
        or not user.is_active
        or user.pk != application.enrolled_user_id
        or not BusinessUser.objects.filter(
            user_id=user.pk,
            user__is_active=True,
            business_id=application.business_id,
            business__is_active=True,
            is_active=True,
            role=BusinessUser.Role.OWNER,
        ).exists()
    ):
        raise StripeCheckoutError("Only the enrolled account owner can start Logistics checkout.")
    if (
        subscription.business.vertical != Business.Vertical.LOGISTICS
        or subscription.plan.family != ClarivoPlan.Family.LOGISTICS
        or subscription.plan.slug != "logistics"
        or subscription.status != BusinessSubscription.Status.PENDING_CHECKOUT
        or subscription.payment_provider != BusinessSubscription.PaymentProvider.STRIPE
        or subscription.billing_interval != BusinessSubscription.BillingInterval.YEARLY
        or subscription.billing_currency != application.preferred_currency.lower()
        or subscription.trial_start is not None
        or subscription.trial_end is not None
    ):
        raise StripeCheckoutError(
            "The enrolled subscription is not ready for annual Logistics checkout."
        )
    if not subscription.plan.is_active:
        raise StripeConfigurationError(
            "The Logistics offering is inactive. Contact Motionmate for configuration."
        )
    return application


def configured_annual_price(plan, currency):
    """No zero or fallback commercial price; use the existing regional pricing pattern."""
    if plan.family != ClarivoPlan.Family.LOGISTICS or plan.slug != "logistics":
        raise StripeConfigurationError("Select the Logistics offering before activation.")
    if not is_stripe_enabled():
        raise StripeConfigurationError("Stripe subscription billing is disabled.")
    price_id = get_stripe_price_id(
        plan_slug="logistics", billing_interval="yearly", currency=currency
    )
    metadata = resolve_stripe_price_id(price_id)
    if (metadata.plan_slug, metadata.billing_interval, metadata.currency) != (
        "logistics",
        "yearly",
        currency,
    ):
        raise StripeConfigurationError("Logistics annual Price mapping is inconsistent.")
    try:
        pricing = plan.get_pricing_data(region=currency)
        amount = Decimal(pricing["yearly"])
        if (
            str(pricing["currency"]).lower() != currency
            or not amount.is_finite()
            or amount <= 0
            or amount * 100 != (amount * 100).to_integral_value()
        ):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise StripeConfigurationError(
            f"Configure a positive Logistics yearly display price in {currency.upper()} before checkout."
        ) from exc
    return price_id, int(amount * 100)


def validate_annual_stripe_price(*, plan, currency, stripe_client):
    price_id, expected_amount = configured_annual_price(plan, currency)
    try:
        price = stripe_client.Price.retrieve(price_id)
        # Stripe SDK objects are not necessarily dict/Mapping instances.
        if hasattr(price, "to_dict_recursive"):
            price = price.to_dict_recursive()
        elif hasattr(price, "to_dict"):
            price = price.to_dict()
    except Exception as exc:
        raise StripeConfigurationError(
            "The configured Logistics annual Stripe Price could not be verified."
        ) from exc
    if not isinstance(price, Mapping) or not isinstance(price.get("recurring"), Mapping):
        raise StripeConfigurationError("The configured Logistics annual Stripe Price is invalid.")
    recurring = price["recurring"]
    if (
        price.get("id") != price_id
        or price.get("active") is not True
        or price.get("type") != "recurring"
        or price.get("currency") != currency
        or recurring.get("interval") != "year"
        or recurring.get("interval_count") != 1
        or recurring.get("usage_type") != "licensed"
        or price.get("billing_scheme") != "per_unit"
        or type(price.get("unit_amount")) is not int
        or price.get("unit_amount") != expected_amount
    ):
        raise StripeConfigurationError(
            "Logistics Stripe Price must be active, annual, and match its configured currency and positive price."
        )
    return price_id


def validate_offering_activation(plan):
    """Admin activation requires at least one completely configured annual currency."""
    currencies = []
    for currency in ("usd", "eur"):
        try:
            get_stripe_price_id(plan_slug="logistics", billing_interval="yearly", currency=currency)
        except StripeConfigurationError as exc:
            # Missing optional currencies do not prevent a one-currency offering.
            if "not configured" in str(exc):
                continue
            raise
        configured_annual_price(plan, currency)
        currencies.append(currency)
    if not currencies:
        raise StripeConfigurationError(
            "Configure at least one Logistics annual Stripe Price before activation."
        )
    stripe_client = configure_stripe_sdk()
    for currency in currencies:
        validate_annual_stripe_price(plan=plan, currency=currency, stripe_client=stripe_client)


@transaction.atomic
def checkout_for_application(application_id, *, request, user):
    # Same application lock order as enrollment/review. Serialize clicks and approval
    # changes through the network call; Stripe's existing idempotency key handles
    # remote success followed by a local transaction failure.
    application = LogisticsApplication.objects.select_for_update().filter(pk=application_id).first()
    if application is None or application.business_id is None or application.converted_at is None:
        raise StripeCheckoutError("Checkout requires an existing Logistics enrollment.")
    subscription = (
        BusinessSubscription.objects.select_for_update(of=("self",))
        .select_related("business", "plan")
        .filter(business_id=application.business_id)
        .first()
    )
    if subscription is None:
        raise StripeCheckoutError("The enrolled subscription is unavailable.")
    require_checkout_enrollment(subscription, user)
    return resume_trial_checkout_session(request=request, subscription=subscription, user=user)
