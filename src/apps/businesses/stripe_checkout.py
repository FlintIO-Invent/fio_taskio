from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser

from .models import Business, BusinessSubscription, ClarivoPlan
from .plan_catalog import (
    PUBLIC_PRICING_CURRENCIES,
    STANDARD_TRIAL_DAYS,
    normalize_public_billing_interval,
    normalize_public_paid_plan_slug,
)
from .stripe_config import (
    StripeConfigurationError,
    configure_stripe_sdk,
    get_stripe_price_id,
    is_stripe_enabled,
)


class StripeCheckoutError(Exception):
    """Raised when a Stripe-hosted Checkout Session cannot be prepared safely."""


class StripeCheckoutAlreadyCompleted(StripeCheckoutError):
    """Raised when Stripe already reports the checkout session as completed."""


def ensure_pending_checkout_subscription(
    *,
    business: Business,
    plan: ClarivoPlan,
    billing_interval: object,
    currency: object,
) -> BusinessSubscription:
    _require_stripe_checkout_ready()
    plan_slug, normalized_interval, normalized_currency = _validated_checkout_dimensions(
        plan=plan,
        billing_interval=billing_interval,
        currency=currency,
    )
    subscription, created = BusinessSubscription.objects.get_or_create(
        business=business,
        defaults={
            "plan": plan,
            "status": BusinessSubscription.Status.PENDING_CHECKOUT,
            "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
            "billing_interval": normalized_interval,
            "billing_currency": normalized_currency,
        },
    )
    if created:
        return subscription

    if subscription.status != BusinessSubscription.Status.PENDING_CHECKOUT:
        raise StripeCheckoutError("This workspace subscription is not pending checkout.")

    update_fields: list[str] = []
    desired_values = {
        "plan": plan,
        "payment_provider": BusinessSubscription.PaymentProvider.STRIPE,
        "billing_interval": normalized_interval,
        "billing_currency": normalized_currency,
    }
    for field_name, value in desired_values.items():
        current_value = getattr(subscription, field_name)
        if current_value != value:
            setattr(subscription, field_name, value)
            update_fields.append(field_name)

    if subscription.provider_price_id:
        try:
            configured_price_id = get_stripe_price_id(
                plan_slug=plan_slug,
                billing_interval=normalized_interval,
                currency=normalized_currency,
            )
        except StripeConfigurationError:
            configured_price_id = ""
        if subscription.provider_price_id != configured_price_id:
            subscription.provider_price_id = configured_price_id
            update_fields.append("provider_price_id")

    if update_fields:
        subscription.save(update_fields=[*update_fields, "updated_at"])

    return subscription


def create_trial_checkout_session(
    *,
    request: HttpRequest,
    subscription: BusinessSubscription,
    user: TaskIOUser,
) -> str:
    """
    Create a Stripe-hosted subscription Checkout Session for a pending local row.

    This performs the network call outside the registration transaction. Return
    URLs are informational only; Block 5 webhooks will activate access.
    """
    return _create_checkout_session(
        request=request,
        subscription=subscription,
        user=user,
        replacing_session_id="initial",
    )


def resume_trial_checkout_session(
    *,
    request: HttpRequest,
    subscription: BusinessSubscription,
    user: TaskIOUser,
) -> str:
    if subscription.status != BusinessSubscription.Status.PENDING_CHECKOUT:
        raise StripeCheckoutError("This workspace subscription is not pending checkout.")

    _require_stripe_checkout_ready()
    stripe_client = configure_stripe_sdk()
    existing_session_id = subscription.provider_checkout_session_id

    if existing_session_id:
        session = _retrieve_checkout_session(stripe_client, existing_session_id)
        _validate_session_belongs_to_subscription(session=session, subscription=subscription)
        session_status = str(_stripe_value(session, "status") or "").strip().lower()
        session_url = _stripe_value(session, "url")
        expires_at = _stripe_timestamp_to_datetime(_stripe_value(session, "expires_at"))

        if session_status == "complete":
            raise StripeCheckoutAlreadyCompleted("Checkout has already been completed.")

        if session_status == "open" and session_url and _session_still_usable(expires_at):
            if subscription.checkout_session_expires_at != expires_at:
                subscription.checkout_session_expires_at = expires_at
                subscription.save(update_fields=["checkout_session_expires_at", "updated_at"])
            return str(session_url)

        _expire_checkout_session_if_open(
            stripe_client=stripe_client,
            session_id=existing_session_id,
            session_status=session_status,
        )

    return _create_checkout_session(
        request=request,
        subscription=subscription,
        user=user,
        replacing_session_id=existing_session_id or "new",
    )


def _create_checkout_session(
    *,
    request: HttpRequest,
    subscription: BusinessSubscription,
    user: TaskIOUser,
    replacing_session_id: str,
) -> str:
    _require_stripe_checkout_ready()

    plan = subscription.plan
    plan_slug, billing_interval, currency = _validated_checkout_dimensions(
        plan=plan,
        billing_interval=subscription.billing_interval,
        currency=subscription.billing_currency,
    )
    price_id = get_stripe_price_id(
        plan_slug=plan_slug,
        billing_interval=billing_interval,
        currency=currency,
    )
    metadata = _checkout_metadata(
        subscription=subscription,
        user=user,
        plan_slug=plan_slug,
        billing_interval=billing_interval,
        currency=currency,
    )
    stripe_client = configure_stripe_sdk()
    checkout_session = _stripe_create_checkout_session(
        stripe_client=stripe_client,
        customer_email=user.email,
        price_id=price_id,
        success_url=(
            f"{request.build_absolute_uri(reverse('billing_checkout_success'))}"
            "?session_id={CHECKOUT_SESSION_ID}"
        ),
        cancel_url=request.build_absolute_uri(reverse("billing_checkout_cancelled")),
        client_reference_id=_client_reference_id(subscription),
        metadata=metadata,
        idempotency_key=_checkout_idempotency_key(
            subscription=subscription,
            replacing_session_id=replacing_session_id,
        ),
    )
    checkout_url = _stripe_value(checkout_session, "url")
    checkout_session_id = _stripe_value(checkout_session, "id")
    expires_at = _stripe_timestamp_to_datetime(_stripe_value(checkout_session, "expires_at"))
    if not checkout_url or not checkout_session_id:
        raise StripeCheckoutError("Stripe did not return a usable Checkout Session.")

    subscription.provider_price_id = price_id
    subscription.provider_checkout_session_id = str(checkout_session_id)
    subscription.checkout_session_expires_at = expires_at
    subscription.save(
        update_fields=[
            "provider_price_id",
            "provider_checkout_session_id",
            "checkout_session_expires_at",
            "updated_at",
        ]
    )
    return str(checkout_url)


def _require_stripe_checkout_ready() -> None:
    if not is_stripe_enabled():
        raise StripeConfigurationError("Stripe subscription billing is disabled.")


def _validated_checkout_dimensions(
    *,
    plan: ClarivoPlan | None,
    billing_interval: object,
    currency: object,
) -> tuple[str, str, str]:
    if plan is None or not plan.is_active:
        raise StripeCheckoutError("Select an active public Motionmate plan before checkout.")

    plan_slug = normalize_public_paid_plan_slug(plan.slug)
    if plan_slug is None:
        raise StripeCheckoutError("Only public Motionmate plans can use Stripe Checkout.")

    normalized_interval = normalize_public_billing_interval(billing_interval)
    if normalized_interval is None:
        raise StripeCheckoutError("Select monthly or yearly billing before checkout.")

    normalized_currency = str(currency or "").strip().lower()
    if normalized_currency not in PUBLIC_PRICING_CURRENCIES:
        raise StripeCheckoutError("Select a supported checkout currency.")

    return plan_slug, normalized_interval, normalized_currency


def _stripe_create_checkout_session(
    *,
    stripe_client: Any,
    customer_email: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    client_reference_id: str,
    metadata: dict[str, str],
    idempotency_key: str,
) -> Any:
    try:
        return stripe_client.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            subscription_data={
                "trial_period_days": STANDARD_TRIAL_DAYS,
                "metadata": metadata,
            },
            payment_method_collection="always",
            payment_method_types=["card"],
            customer_email=customer_email,
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=client_reference_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise StripeCheckoutError("Stripe Checkout Session could not be created.") from exc


def _retrieve_checkout_session(stripe_client: Any, session_id: str) -> Any:
    try:
        return stripe_client.checkout.Session.retrieve(session_id)
    except Exception as exc:
        raise StripeCheckoutError("Stripe Checkout Session could not be retrieved.") from exc


def _expire_checkout_session_if_open(
    *,
    stripe_client: Any,
    session_id: str,
    session_status: str,
) -> None:
    if session_status != "open":
        return

    try:
        stripe_client.checkout.Session.expire(session_id)
    except Exception as exc:
        raise StripeCheckoutError("Stripe Checkout Session could not be refreshed.") from exc


def _validate_session_belongs_to_subscription(
    *,
    session: Any,
    subscription: BusinessSubscription,
) -> None:
    metadata = _stripe_value(session, "metadata") or {}
    client_reference_id = str(_stripe_value(session, "client_reference_id") or "")
    expected_metadata = {
        "motionmate_business_id": str(subscription.business_id),
        "motionmate_subscription_id": str(subscription.pk),
        "plan_slug": subscription.plan.slug,
        "billing_interval": subscription.billing_interval,
        "billing_currency": subscription.billing_currency,
    }

    for key, expected_value in expected_metadata.items():
        if str(metadata.get(key, "")) != expected_value:
            raise StripeCheckoutError("Stored Checkout Session does not match this workspace.")

    if client_reference_id and client_reference_id != _client_reference_id(subscription):
        raise StripeCheckoutError("Stored Checkout Session does not match this workspace.")


def _checkout_metadata(
    *,
    subscription: BusinessSubscription,
    user: TaskIOUser,
    plan_slug: str,
    billing_interval: str,
    currency: str,
) -> dict[str, str]:
    return {
        "motionmate_business_id": str(subscription.business_id),
        "motionmate_subscription_id": str(subscription.pk),
        "motionmate_user_id": str(user.pk),
        "plan_slug": plan_slug,
        "billing_interval": billing_interval,
        "billing_currency": currency,
    }


def _client_reference_id(subscription: BusinessSubscription) -> str:
    return f"business:{subscription.business_id}:subscription:{subscription.pk}"


def _checkout_idempotency_key(
    *,
    subscription: BusinessSubscription,
    replacing_session_id: str,
) -> str:
    return (
        f"motionmate-checkout-{subscription.pk}-"
        f"{subscription.billing_interval}-{subscription.billing_currency}-{replacing_session_id}"
    )[:255]


def _stripe_value(stripe_object: Any, field_name: str) -> Any:
    if isinstance(stripe_object, dict):
        return stripe_object.get(field_name)
    return getattr(stripe_object, field_name, None)


def _stripe_timestamp_to_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _session_still_usable(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return True
    return expires_at > timezone.now()
