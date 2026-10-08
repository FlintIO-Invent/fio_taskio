"""Approval binding and fail-closed reconciliation for Logistics Stripe checkout."""

import logging

from django.db import transaction
from django.utils import timezone

from apps.businesses.models import BusinessSubscription, BusinessUser

from .models import LogisticsApplication

logger = logging.getLogger(__name__)


def current_checkout_application(subscription):
    application = LogisticsApplication.objects.filter(business_id=subscription.business_id).first()
    if (
        application is None
        or application.status != LogisticsApplication.Status.APPROVED
        or application.approved_revision != application.revision
        or application.evaluated_revision != application.revision
        or application.converted_revision != application.revision
        or application.converted_at is None
        or application.business_id_snapshot != subscription.business_id
        or application.enrolled_user_id is None
        or subscription.billing_currency != application.preferred_currency.lower()
        or not BusinessUser.objects.filter(
            user_id=application.enrolled_user_id,
            user__is_active=True,
            business_id=subscription.business_id,
            business__is_active=True,
            is_active=True,
            role=BusinessUser.Role.OWNER,
        ).exists()
    ):
        return None
    return application


def approval_metadata(application):
    # A decision identity prevents revocation followed by approval of the same
    # revision from reviving a previously issued provider authorization.
    decision = application.decisions.order_by("-pk").first()
    if (
        decision is None
        or decision.result != LogisticsApplication.Status.APPROVED
        or decision.application_revision != application.revision
    ):
        return None
    return {
        "logistics_application_id": str(application.pk),
        "logistics_application_revision": str(application.revision),
        "logistics_approval_decision_id": str(decision.pk),
    }


def matches_current_approval(subscription, metadata):
    from apps.businesses.stripe_checkout import _stripe_value

    application = current_checkout_application(subscription)
    expected = approval_metadata(application) if application else None
    return bool(expected) and all(
        str(_stripe_value(metadata, key) or "") == value for key, value in expected.items()
    )


def invalidate_checkout(application):
    """Called under the application lock after recording a new decision.

    Keep the old session identity for expiration retries and payment correlation.
    Local eligibility changes commit before the best-effort provider operation.
    A paid subscription's review hold is only released explicitly by an admin.
    """
    if application.business_id is None:
        return
    from apps.businesses.stripe_checkout import _is_logistics_subscription

    subscription = (
        BusinessSubscription.objects.select_for_update(of=("self",))
        .select_related("business", "plan")
        .filter(business_id=application.business_id)
        .first()
    )
    if subscription is None or not _is_logistics_subscription(subscription):
        return
    valid = current_checkout_application(subscription) is not None
    needs_review = bool(subscription.provider_subscription_id) or (
        subscription.status != BusinessSubscription.Status.PENDING_CHECKOUT
    )
    subscription.logistics_approval_review_required = (
        subscription.logistics_approval_review_required if needs_review else not valid
    )
    if needs_review:
        subscription.logistics_approval_review_required = True
        subscription.status = BusinessSubscription.Status.SUSPENDED
    subscription.checkout_session_expires_at = timezone.now()
    # Revocation must also work for a linked row whose billing dimensions have
    # become invalid. Only tighten eligibility; do not repair billing dimensions.
    BusinessSubscription.objects.filter(pk=subscription.pk).update(
        logistics_approval_review_required=subscription.logistics_approval_review_required,
        status=subscription.status,
        checkout_session_expires_at=subscription.checkout_session_expires_at,
        updated_at=timezone.now(),
    )
    session_id = subscription.provider_checkout_session_id
    if session_id:
        transaction.on_commit(lambda: _expire_invalidated_session(subscription.pk, session_id))


def _expire_invalidated_session(subscription_id, session_id):
    from apps.businesses.stripe_checkout import (
        _expire_checkout_session_if_open,
        _retrieve_checkout_session,
        _stripe_value,
        configure_stripe_sdk,
    )

    try:
        stripe_client = configure_stripe_sdk()
        session = _retrieve_checkout_session(stripe_client, session_id)
        # Never expire a provider object belonging to another local subscription.
        metadata = _stripe_value(session, "metadata") or {}
        if str(_stripe_value(metadata, "motionmate_subscription_id") or "") != str(subscription_id):
            raise ValueError("Session identity mismatch")
        _expire_checkout_session_if_open(
            stripe_client=stripe_client,
            session_id=session_id,
            session_status=str(_stripe_value(session, "status") or "").lower(),
        )
    except Exception:
        # Provider failure must not roll back the locally revoked authorization,
        # nor expose provider response details/credentials in operator logs.
        logger.warning(
            "Logistics checkout expiration requires review: subscription=%s session=%s",
            subscription_id,
            session_id,
        )
