from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from .models import Business, BusinessSubscription, BusinessUser
from .plan_catalog import normalize_public_paid_plan_slug
from .stripe_config import (
    StripeConfigurationError,
    configure_stripe_sdk,
    get_stripe_customer_portal_configuration_id_or_raise,
    is_stripe_enabled,
)

logger = logging.getLogger(__name__)

PORTAL_TEMPORARILY_UNAVAILABLE_MESSAGE = (
    "Billing management is temporarily unavailable. "
    "Please contact support if this does not resolve shortly."
)
PORTAL_OPEN_FAILED_MESSAGE = "We could not open the secure billing page. Please try again shortly."
PORTAL_NOT_AVAILABLE_MESSAGE = (
    "Billing management is not available for this subscription right now."
)
PAYMENT_RECOVERY_NOT_AVAILABLE_MESSAGE = (
    "Payment recovery is not available for this subscription right now."
)


@dataclass(frozen=True)
class CustomerPortalAvailability:
    can_open: bool
    reason: str = ""
    user_message: str = ""


class StripeCustomerPortalError(Exception):
    def __init__(self, message: str, *, user_message: str = PORTAL_NOT_AVAILABLE_MESSAGE):
        super().__init__(message)
        self.user_message = user_message


def get_customer_portal_availability(
    *,
    business: Business | None,
    user,
    subscription: BusinessSubscription | None,
    at_time=None,
) -> CustomerPortalAvailability:
    if business is None or subscription is None:
        return CustomerPortalAvailability(False, "missing_subscription")

    if subscription.business_id != business.pk:
        return CustomerPortalAvailability(False, "subscription_business_mismatch")

    if not business.is_active:
        return CustomerPortalAvailability(False, BusinessSubscription.AccessCode.BUSINESS_INACTIVE)

    if not _user_is_business_owner(business=business, user=user):
        return CustomerPortalAvailability(False, "owner_required")

    if not is_stripe_enabled():
        return CustomerPortalAvailability(False, "stripe_disabled")

    if subscription.status not in (
        BusinessSubscription.Status.TRIALING,
        BusinessSubscription.Status.ACTIVE,
    ):
        return CustomerPortalAvailability(False, "status_not_allowed")

    access_state = subscription.effective_access_state_at(at_time)
    if not access_state.has_access:
        return CustomerPortalAvailability(False, access_state.code)

    if normalize_public_paid_plan_slug(subscription.plan.slug) is None:
        return CustomerPortalAvailability(False, "non_public_plan")

    if subscription.payment_provider != BusinessSubscription.PaymentProvider.STRIPE:
        return CustomerPortalAvailability(False, "non_stripe_provider")

    if not _is_valid_provider_customer_id(subscription.provider_customer_id):
        return CustomerPortalAvailability(
            False,
            "invalid_provider_customer_id",
            PORTAL_TEMPORARILY_UNAVAILABLE_MESSAGE,
        )

    if not _is_valid_provider_subscription_id(subscription.provider_subscription_id):
        return CustomerPortalAvailability(
            False,
            "invalid_provider_subscription_id",
            PORTAL_TEMPORARILY_UNAVAILABLE_MESSAGE,
        )

    try:
        get_stripe_customer_portal_configuration_id_or_raise()
    except StripeConfigurationError:
        return CustomerPortalAvailability(
            False,
            "portal_configuration_unavailable",
            PORTAL_TEMPORARILY_UNAVAILABLE_MESSAGE,
        )

    return CustomerPortalAvailability(True, "eligible")


def get_payment_recovery_portal_availability(
    *,
    business: Business | None,
    user,
    subscription: BusinessSubscription | None,
) -> CustomerPortalAvailability:
    if business is None or subscription is None:
        return CustomerPortalAvailability(False, "missing_subscription")

    if subscription.business_id != business.pk:
        return CustomerPortalAvailability(False, "subscription_business_mismatch")

    if not _user_is_business_owner(business=business, user=user):
        return CustomerPortalAvailability(False, "owner_required")

    if not is_stripe_enabled():
        return CustomerPortalAvailability(False, "stripe_disabled")

    if not business.is_active:
        return CustomerPortalAvailability(False, BusinessSubscription.AccessCode.BUSINESS_INACTIVE)

    if not subscription.plan.is_active:
        return CustomerPortalAvailability(False, BusinessSubscription.AccessCode.PLAN_INACTIVE)

    if subscription.status != BusinessSubscription.Status.PAST_DUE:
        return CustomerPortalAvailability(False, "status_not_allowed")

    if normalize_public_paid_plan_slug(subscription.plan.slug) is None:
        return CustomerPortalAvailability(False, "non_public_plan")

    if subscription.payment_provider != BusinessSubscription.PaymentProvider.STRIPE:
        return CustomerPortalAvailability(False, "non_stripe_provider")

    if not _is_valid_provider_customer_id(subscription.provider_customer_id):
        return CustomerPortalAvailability(
            False,
            "invalid_provider_customer_id",
            PORTAL_TEMPORARILY_UNAVAILABLE_MESSAGE,
        )

    if not _is_valid_provider_subscription_id(subscription.provider_subscription_id):
        return CustomerPortalAvailability(
            False,
            "invalid_provider_subscription_id",
            PORTAL_TEMPORARILY_UNAVAILABLE_MESSAGE,
        )

    try:
        get_stripe_customer_portal_configuration_id_or_raise()
    except StripeConfigurationError:
        return CustomerPortalAvailability(
            False,
            "portal_configuration_unavailable",
            PORTAL_TEMPORARILY_UNAVAILABLE_MESSAGE,
        )

    return CustomerPortalAvailability(True, "eligible")


def create_customer_portal_session(
    *,
    request: HttpRequest,
    business: Business,
    user,
    subscription: BusinessSubscription,
) -> str:
    availability = get_customer_portal_availability(
        business=business,
        user=user,
        subscription=subscription,
    )
    logger.info(
        "stripe_customer_portal.session_requested",
        extra={
            "business_id": business.pk,
            "subscription_id": subscription.pk,
            "availability_reason": availability.reason,
        },
    )
    if not availability.can_open:
        log_method = logger.warning if availability.user_message else logger.info
        log_method(
            "stripe_customer_portal.session_rejected",
            extra={
                "business_id": business.pk,
                "subscription_id": subscription.pk,
                "availability_reason": availability.reason,
            },
        )
        raise StripeCustomerPortalError(
            "Stripe Customer Portal Session is not available.",
            user_message=availability.user_message or PORTAL_NOT_AVAILABLE_MESSAGE,
        )

    configuration_id = get_stripe_customer_portal_configuration_id_or_raise()
    return_url = _trusted_portal_return_url(request)
    stripe_client = configure_stripe_sdk()

    try:
        portal_session = stripe_client.billing_portal.Session.create(
            customer=subscription.provider_customer_id,
            configuration=configuration_id,
            return_url=return_url,
        )
    except Exception as exc:
        logger.warning(
            "stripe_customer_portal.session_failed",
            extra={
                "business_id": business.pk,
                "subscription_id": subscription.pk,
                "stripe_request_id": _stripe_request_id(exc),
            },
        )
        raise StripeCustomerPortalError(
            "Stripe Customer Portal Session could not be created.",
            user_message=PORTAL_OPEN_FAILED_MESSAGE,
        ) from exc

    portal_url = _stripe_value(portal_session, "url")
    if not _is_valid_portal_url(portal_url):
        logger.warning(
            "stripe_customer_portal.session_missing_url",
            extra={
                "business_id": business.pk,
                "subscription_id": subscription.pk,
            },
        )
        raise StripeCustomerPortalError(
            "Stripe Customer Portal Session did not return a usable URL.",
            user_message=PORTAL_OPEN_FAILED_MESSAGE,
        )

    logger.info(
        "stripe_customer_portal.session_created",
        extra={
            "business_id": business.pk,
            "subscription_id": subscription.pk,
        },
    )
    return str(portal_url)


def create_payment_recovery_portal_session(
    *,
    request: HttpRequest,
    business: Business,
    user,
    subscription: BusinessSubscription,
) -> str:
    availability = get_payment_recovery_portal_availability(
        business=business,
        user=user,
        subscription=subscription,
    )
    logger.info(
        "stripe_payment_recovery.session_requested",
        extra={
            "business_id": business.pk,
            "subscription_id": subscription.pk,
            "availability_reason": availability.reason,
        },
    )
    if not availability.can_open:
        log_method = logger.warning if availability.user_message else logger.info
        log_method(
            "stripe_payment_recovery.session_rejected",
            extra={
                "business_id": business.pk,
                "subscription_id": subscription.pk,
                "availability_reason": availability.reason,
            },
        )
        raise StripeCustomerPortalError(
            "Stripe payment recovery Portal Session is not available.",
            user_message=availability.user_message or PAYMENT_RECOVERY_NOT_AVAILABLE_MESSAGE,
        )

    configuration_id = get_stripe_customer_portal_configuration_id_or_raise()
    return_url = _trusted_portal_return_url(request)
    stripe_client = configure_stripe_sdk()

    try:
        portal_session = stripe_client.billing_portal.Session.create(
            customer=subscription.provider_customer_id,
            configuration=configuration_id,
            return_url=return_url,
        )
    except Exception as exc:
        logger.warning(
            "stripe_payment_recovery.session_failed",
            extra={
                "business_id": business.pk,
                "subscription_id": subscription.pk,
                "stripe_request_id": _stripe_request_id(exc),
            },
        )
        raise StripeCustomerPortalError(
            "Stripe payment recovery Portal Session could not be created.",
            user_message=PORTAL_OPEN_FAILED_MESSAGE,
        ) from exc

    portal_url = _stripe_value(portal_session, "url")
    if not _is_valid_portal_url(portal_url):
        logger.warning(
            "stripe_payment_recovery.session_missing_url",
            extra={
                "business_id": business.pk,
                "subscription_id": subscription.pk,
            },
        )
        raise StripeCustomerPortalError(
            "Stripe payment recovery Portal Session did not return a usable URL.",
            user_message=PORTAL_OPEN_FAILED_MESSAGE,
        )

    logger.info(
        "stripe_payment_recovery.session_created",
        extra={
            "business_id": business.pk,
            "subscription_id": subscription.pk,
        },
    )
    return str(portal_url)


def _user_is_business_owner(*, business: Business, user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False

    return BusinessUser.objects.filter(
        business=business,
        user=user,
        is_active=True,
        role=BusinessUser.Role.OWNER,
    ).exists()


def _is_valid_provider_customer_id(value: object) -> bool:
    return str(value or "").strip().startswith("cus_")


def _is_valid_provider_subscription_id(value: object) -> bool:
    return str(value or "").strip().startswith("sub_")


def _trusted_portal_return_url(request: HttpRequest) -> str:
    return f"{request.build_absolute_uri(reverse('business_subscription'))}?billing_return=1"


def _is_valid_portal_url(value: object) -> bool:
    return str(value or "").strip().startswith("https://")


def _stripe_value(stripe_object: Any, field_name: str) -> Any:
    if isinstance(stripe_object, dict):
        return stripe_object.get(field_name)
    return getattr(stripe_object, field_name, None)


def _stripe_request_id(exc: Exception) -> str:
    request_id = getattr(exc, "request_id", "")
    if request_id:
        return str(request_id)

    request = getattr(exc, "request", None)
    request_id = getattr(request, "id", "")
    return str(request_id or "")
