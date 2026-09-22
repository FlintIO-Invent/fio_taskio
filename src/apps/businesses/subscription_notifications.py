from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from apps.notifications.emails import send_templated_email
from helpers import build_public_url

from .models import (
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    SubscriptionAccessMode,
    SubscriptionNotification,
)

logger = logging.getLogger(__name__)

MAX_LAST_ERROR_LENGTH = 500
MISSING_OWNER_RECIPIENT_KEY = "missing-owner"
TRIAL_REMINDER_NOTIFICATION_TYPES = frozenset(
    {
        SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS,
        SubscriptionNotification.NotificationType.TRIAL_ENDING_1_DAY,
    }
)
GRACE_REMINDER_NOTIFICATION_TYPES = frozenset(
    {
        SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY,
        SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED,
    }
)
SUBSCRIPTION_REMINDER_NOTIFICATION_TYPES = (
    TRIAL_REMINDER_NOTIFICATION_TYPES | GRACE_REMINDER_NOTIFICATION_TYPES
)


@dataclass(frozen=True)
class SubscriptionNotificationDeliveryResult:
    notification_id: int
    status: str
    message: str = ""


@dataclass(frozen=True)
class SubscriptionNotificationEnqueueResult:
    notifications: list[SubscriptionNotification]
    created_count: int = 0
    duplicate_count: int = 0


def enqueue_subscription_notification(
    *,
    subscription: BusinessSubscription,
    notification_type: str,
    deduplication_context: dict[str, Any] | str,
    source_provider_event_id: str = "",
    available_at=None,
    context_summary: dict[str, Any] | None = None,
) -> list[SubscriptionNotification]:
    return enqueue_subscription_notification_with_result(
        subscription=subscription,
        notification_type=notification_type,
        deduplication_context=deduplication_context,
        source_provider_event_id=source_provider_event_id,
        available_at=available_at,
        context_summary=context_summary,
    ).notifications


def enqueue_subscription_notification_with_result(
    *,
    subscription: BusinessSubscription,
    notification_type: str,
    deduplication_context: dict[str, Any] | str,
    source_provider_event_id: str = "",
    available_at=None,
    context_summary: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> SubscriptionNotificationEnqueueResult:
    notification_type = _validate_notification_type(notification_type)
    subscription = _subscription_for_enqueue(subscription)

    if not _subscription_is_billable_for_notifications(subscription):
        return SubscriptionNotificationEnqueueResult([])

    available_at = available_at or timezone.now()
    context_key = _deduplication_context_key(deduplication_context)
    context_snapshot = _context_snapshot(
        subscription=subscription,
        notification_type=notification_type,
        extra_context=context_summary or {},
    )
    recipient_entries = _notification_recipient_entries(subscription.business)

    notifications: list[SubscriptionNotification] = []
    created_count = 0
    duplicate_count = 0
    for recipient in recipient_entries:
        deduplication_key = _deduplication_key(
            subscription_id=subscription.pk,
            notification_type=notification_type,
            context_key=context_key,
            recipient_key=recipient["recipient_key"],
        )
        if dry_run:
            if SubscriptionNotification.objects.filter(
                deduplication_key=deduplication_key,
            ).exists():
                duplicate_count += 1
            else:
                created_count += 1
            continue

        notification, created = _get_or_create_notification(
            subscription=subscription,
            notification_type=notification_type,
            recipient_email=recipient["email"],
            recipient_user=recipient["user"],
            recipient_key=recipient["recipient_key"],
            context_key=context_key,
            source_provider_event_id=source_provider_event_id,
            available_at=available_at,
            context_summary=context_snapshot,
            initial_status=recipient["initial_status"],
            initial_error=recipient["initial_error"],
        )
        notifications.append(notification)
        if created:
            created_count += 1
        else:
            duplicate_count += 1
    return SubscriptionNotificationEnqueueResult(
        notifications,
        created_count=created_count,
        duplicate_count=duplicate_count,
    )


def get_subscription_notification_recipients(business) -> list[dict[str, Any]]:
    recipients: list[dict[str, Any]] = []
    seen_emails: set[str] = set()
    memberships = getattr(
        business,
        "_subscription_notification_owner_memberships",
        None,
    )
    if memberships is None:
        memberships = (
            BusinessUser.objects.filter(
                business=business,
                role=BusinessUser.Role.OWNER,
                is_active=True,
                user__is_active=True,
            )
            .select_related("user")
            .order_by("created_at", "pk")
        )
    for membership in memberships:
        email = _normalize_email(getattr(membership.user, "email", ""))
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        recipients.append(
            {
                "email": email,
                "user": membership.user,
                "recipient_key": f"email:{_recipient_hash(email)}",
            }
        )
    return recipients


def is_subscription_reminder_notification_type(notification_type: str) -> bool:
    return notification_type in SUBSCRIPTION_REMINDER_NOTIFICATION_TYPES


def _notification_recipient_entries(business) -> list[dict[str, Any]]:
    recipients = get_subscription_notification_recipients(business)
    if recipients:
        return [
            {
                **recipient,
                "initial_status": SubscriptionNotification.Status.PENDING,
                "initial_error": "",
            }
            for recipient in recipients
        ]
    return [
        {
            "email": "",
            "user": None,
            "recipient_key": MISSING_OWNER_RECIPIENT_KEY,
            "initial_status": SubscriptionNotification.Status.FAILED,
            "initial_error": "No active owner recipient email is configured.",
        }
    ]


def deliver_subscription_notification(
    notification: SubscriptionNotification | int,
    *,
    retry_failed: bool = True,
) -> SubscriptionNotificationDeliveryResult:
    notification_id = notification.pk if isinstance(notification, SubscriptionNotification) else int(notification)
    claimed = _claim_notification(notification_id, retry_failed=retry_failed)
    if claimed is None:
        current_status = (
            SubscriptionNotification.objects.filter(pk=notification_id)
            .values_list("status", flat=True)
            .first()
        )
        return SubscriptionNotificationDeliveryResult(
            notification_id=notification_id,
            status="skipped",
            message=f"Notification is not eligible for delivery: {current_status or 'missing'}.",
        )

    if not claimed.business.is_active:
        return _mark_delivery_cancelled(
            claimed.pk,
            "Delivery cancelled because workspace is inactive.",
        )

    cancelled = _cancel_obsolete_reminder_before_delivery(claimed)
    if cancelled is not None:
        return cancelled

    if not _normalize_email(claimed.recipient_email):
        return _mark_delivery_failed(
            claimed.pk,
            "Recipient email is missing or invalid.",
        )

    try:
        context = build_subscription_notification_email_context(claimed)
        sent = send_templated_email(
            subject_template="emails/subscription_notification_subject.txt",
            body_template="emails/subscription_notification_body.txt",
            html_template="emails/subscription_notification_body.html",
            context=context,
            recipient_list=[claimed.recipient_email],
            log_label="subscription billing",
            fail_safely=False,
        )
    except Exception as exc:
        return _mark_delivery_failed(claimed.pk, _safe_error_summary(exc))

    if not sent:
        return _mark_delivery_failed(
            claimed.pk,
            "Email backend reported no delivered messages.",
        )

    now = timezone.now()
    with transaction.atomic():
        locked = SubscriptionNotification.objects.select_for_update().get(pk=claimed.pk)
        locked.status = SubscriptionNotification.Status.SENT
        locked.sent_at = now
        locked.last_error = ""
        locked.save(update_fields=["status", "sent_at", "last_error", "updated_at"])

    return SubscriptionNotificationDeliveryResult(
        notification_id=claimed.pk,
        status="sent",
        message="Notification sent.",
    )


def build_subscription_notification_email_context(
    notification: SubscriptionNotification,
) -> dict[str, Any]:
    notification = (
        SubscriptionNotification.objects.select_related("business", "subscription", "subscription__plan")
        .get(pk=notification.pk)
        if not hasattr(notification, "business")
        else notification
    )
    summary = dict(notification.context_summary or {})
    business = notification.business
    subscription = notification.subscription
    plan = subscription.plan
    display_timezone = _display_timezone(summary, business)
    action_path = summary.get("action_path") or reverse("business_subscription")
    action_url = build_public_url(action_path)
    plan_name = summary.get("plan_name") or getattr(plan, "name", "Motionmate")
    billing_interval = summary.get("billing_interval") or subscription.billing_interval
    billing_interval_label = _billing_interval_label(billing_interval)
    support_email = summary.get("support_email", "")
    if not support_email:
        support_email = getattr(settings, "MOTIONMATE_SUPPORT_EMAIL", "")

    base_context = {
        "notification": notification,
        "business": business,
        "business_name": summary.get("business_name") or business.name,
        "plan_name": plan_name,
        "billing_interval": billing_interval,
        "billing_interval_label": billing_interval_label,
        "billing_currency": summary.get("billing_currency") or subscription.billing_currency,
        "renewal_amount": summary.get("renewal_amount", ""),
        "action_url": action_url,
        "action_label": summary.get("action_label") or "Manage subscription",
        "support_email": support_email,
        "display_timezone": getattr(display_timezone, "key", str(display_timezone)),
    }
    type_context = _type_email_context(
        notification_type=notification.notification_type,
        summary=summary,
        subscription=subscription,
        plan_name=plan_name,
        billing_interval_label=billing_interval_label,
        display_timezone=display_timezone,
    )
    return {**base_context, **type_context}


def _type_email_context(
    *,
    notification_type: str,
    summary: dict[str, Any],
    subscription: BusinessSubscription,
    plan_name: str,
    billing_interval_label: str,
    display_timezone,
) -> dict[str, Any]:
    if notification_type == SubscriptionNotification.NotificationType.TRIAL_STARTED:
        trial_end = _display_datetime(summary.get("trial_end"), display_timezone)
        title = f"Your Motionmate {plan_name} trial has started"
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": f"Your Motionmate {plan_name} trial is now active.",
            "body_lines": [
                f"Trial end: {trial_end}",
                "No subscription charge is due until the trial ends.",
                _renewal_sentence(summary, billing_interval_label),
                "You can manage billing from your Motionmate subscription page.",
            ],
        }

    if notification_type == SubscriptionNotification.NotificationType.SUBSCRIPTION_ACTIVATED:
        current_period_end = _display_datetime(
            summary.get("current_period_end"),
            display_timezone,
        )
        title = "Your Motionmate subscription is active"
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": f"Your Motionmate {plan_name} subscription is active.",
            "body_lines": [
                f"Billing interval: {billing_interval_label}",
                f"Current period ends: {current_period_end}",
                "You can review or manage billing from your Motionmate subscription page.",
            ],
        }

    if notification_type == SubscriptionNotification.NotificationType.PAYMENT_GRACE_STARTED:
        grace_end = _display_datetime(summary.get("grace_period_ends_at"), display_timezone)
        title = "Action needed: update your Motionmate payment method"
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": "Motionmate could not confirm your subscription payment.",
            "body_lines": [
                f"Your workspace remains available temporarily until: {grace_end}",
                "Repeated payment attempts do not extend this grace period.",
                "Open the Motionmate subscription page to update your payment method.",
            ],
        }

    if notification_type == SubscriptionNotification.NotificationType.PAYMENT_RECOVERED:
        current_period_end = _display_datetime(
            summary.get("current_period_end"),
            display_timezone,
        )
        title = "Your Motionmate subscription payment is resolved"
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": "Your Motionmate subscription payment is resolved and normal access is restored.",
            "body_lines": [
                f"Plan: {plan_name}",
                "Your selected plan remains unchanged.",
                f"Current period ends: {current_period_end}",
            ],
        }

    if notification_type == SubscriptionNotification.NotificationType.CANCELLATION_SCHEDULED:
        effective_at = _display_datetime(summary.get("cancel_effective_at"), display_timezone)
        title = "Your Motionmate subscription is scheduled to end"
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": f"Your Motionmate {plan_name} subscription is scheduled to end.",
            "body_lines": [
                f"Scheduled end: {effective_at}",
                "Workspace access remains available until the scheduled end while the provider state stays active.",
                "Open the Motionmate subscription page to review billing management options.",
            ],
        }

    if notification_type == SubscriptionNotification.NotificationType.SUBSCRIPTION_CANCELLED:
        cancelled_at = _display_datetime(
            summary.get("cancelled_at") or subscription.cancelled_at,
            display_timezone,
        )
        title = "Your Motionmate subscription has ended"
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": "Your Motionmate subscription has ended.",
            "body_lines": [
                f"Effective cancellation: {cancelled_at}",
                "Your business data has not been immediately deleted.",
                "Cancelled subscriptions currently do not provide workspace access.",
                "Open the Motionmate subscription page or contact support for next steps.",
            ],
        }

    if notification_type == SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS:
        trial_end = _display_datetime(summary.get("trial_end"), display_timezone)
        title = "Your Motionmate trial ends in 3 days"
        body_lines = [
            f"Trial end: {trial_end}",
            _trial_renewal_sentence(summary, billing_interval_label),
            "You can manage billing from your Motionmate subscription page.",
        ]
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": f"Your Motionmate {plan_name} trial is nearing its end.",
            "body_lines": body_lines,
        }

    if notification_type == SubscriptionNotification.NotificationType.TRIAL_ENDING_1_DAY:
        trial_end = _display_datetime(summary.get("trial_end"), display_timezone)
        title = "Your Motionmate trial ends in 1 day"
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": f"Your Motionmate {plan_name} trial is in its final reminder window.",
            "body_lines": [
                f"Trial end: {trial_end}",
                _trial_renewal_sentence(summary, billing_interval_label),
                "Review billing before the trial end if you need to make changes.",
            ],
        }

    if notification_type == SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY:
        grace_end = _display_datetime(summary.get("grace_period_ends_at"), display_timezone)
        title = "Action required: your Motionmate payment grace period is ending"
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": "Your Motionmate payment grace period is in its final reminder window.",
            "body_lines": [
                f"Grace period ends: {grace_end}",
                "Full workspace access remains available until that boundary.",
                "After the boundary, the workspace becomes read-only until payment is verified.",
                "Updating a payment method does not restore access until Stripe confirms successful payment.",
                "Open the Motionmate subscription page to update payment.",
            ],
        }

    if notification_type == SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED:
        restricted_at = _display_datetime(
            summary.get("restricted_mode_started_at") or summary.get("grace_period_ends_at"),
            display_timezone,
        )
        title = "Your Motionmate workspace is now read-only"
        return {
            "email_title": title,
            "email_subject": title,
            "body_intro": f"Your Motionmate {plan_name} workspace is now in read-only mode.",
            "body_lines": [
                f"Read-only mode began: {restricted_at}",
                "Existing plan-permitted business data remains available for viewing.",
                "New business-data changes are blocked while the subscription remains past due.",
                "An account owner can still open the Motionmate subscription page to update payment.",
                "Full access returns only after Stripe confirms successful payment recovery.",
            ],
        }

    raise ValueError(f"Unsupported subscription notification type: {notification_type!r}")


def _get_or_create_notification(
    *,
    subscription: BusinessSubscription,
    notification_type: str,
    recipient_email: str,
    recipient_user,
    recipient_key: str,
    context_key: str,
    source_provider_event_id: str,
    available_at,
    context_summary: dict[str, Any],
    initial_status: str = SubscriptionNotification.Status.PENDING,
    initial_error: str = "",
) -> tuple[SubscriptionNotification, bool]:
    deduplication_key = _deduplication_key(
        subscription_id=subscription.pk,
        notification_type=notification_type,
        context_key=context_key,
        recipient_key=recipient_key,
    )
    defaults = {
        "business": subscription.business,
        "subscription": subscription,
        "recipient_email": recipient_email,
        "recipient_user": recipient_user,
        "notification_type": notification_type,
        "status": initial_status,
        "available_at": available_at,
        "last_error": _truncate_error(initial_error),
        "source_provider_event_id": str(source_provider_event_id or "")[:255],
        "context_summary": context_summary,
    }
    try:
        notification, created = SubscriptionNotification.objects.get_or_create(
            deduplication_key=deduplication_key,
            defaults=defaults,
        )
    except IntegrityError:
        notification = SubscriptionNotification.objects.get(deduplication_key=deduplication_key)
        created = False
    return notification, created


def _claim_notification(
    notification_id: int,
    *,
    retry_failed: bool,
) -> SubscriptionNotification | None:
    now = timezone.now()
    eligible_statuses = [SubscriptionNotification.Status.PENDING]
    if retry_failed:
        eligible_statuses.append(SubscriptionNotification.Status.FAILED)
    with transaction.atomic():
        updated = SubscriptionNotification.objects.filter(
            pk=notification_id,
            status__in=eligible_statuses,
            available_at__lte=now,
        ).update(
            status=SubscriptionNotification.Status.PROCESSING,
            attempt_count=F("attempt_count") + 1,
            last_attempt_at=now,
            last_error="",
            updated_at=now,
        )
        if not updated:
            return None
    return SubscriptionNotification.objects.select_related(
        "business",
        "subscription",
        "subscription__plan",
    ).get(pk=notification_id)


def _mark_delivery_failed(
    notification_id: int,
    error_summary: str,
) -> SubscriptionNotificationDeliveryResult:
    error_summary = _truncate_error(error_summary)
    with transaction.atomic():
        locked = SubscriptionNotification.objects.select_for_update().get(pk=notification_id)
        locked.status = SubscriptionNotification.Status.FAILED
        locked.last_error = error_summary
        locked.save(update_fields=["status", "last_error", "updated_at"])
    return SubscriptionNotificationDeliveryResult(
        notification_id=notification_id,
        status="failed",
        message=error_summary,
    )


def _mark_delivery_cancelled(
    notification_id: int,
    reason: str,
) -> SubscriptionNotificationDeliveryResult:
    reason = _truncate_error(reason)
    with transaction.atomic():
        locked = SubscriptionNotification.objects.select_for_update().get(pk=notification_id)
        locked.status = SubscriptionNotification.Status.CANCELLED
        locked.last_error = reason
        locked.save(update_fields=["status", "last_error", "updated_at"])
    logger.info(
        "subscription_reminder.cancelled_before_delivery",
        extra={"notification_id": notification_id, "reason": reason},
    )
    return SubscriptionNotificationDeliveryResult(
        notification_id=notification_id,
        status="cancelled",
        message=reason,
    )


def _cancel_obsolete_reminder_before_delivery(
    notification: SubscriptionNotification,
) -> SubscriptionNotificationDeliveryResult | None:
    if not is_subscription_reminder_notification_type(notification.notification_type):
        return None

    reason = _obsolete_reminder_reason(notification, evaluation_time=timezone.now())
    if not reason:
        return None
    return _mark_delivery_cancelled(notification.pk, reason)


def _obsolete_reminder_reason(
    notification: SubscriptionNotification,
    *,
    evaluation_time,
) -> str:
    subscription = notification.subscription
    summary = notification.context_summary or {}
    notification_type = notification.notification_type

    if not _subscription_has_valid_provider_identity(subscription):
        return "Reminder cancelled because subscription provider identity is no longer valid."

    if notification_type in TRIAL_REMINDER_NOTIFICATION_TYPES:
        return _obsolete_trial_reminder_reason(subscription, summary, evaluation_time)

    if notification_type == SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY:
        return _obsolete_grace_reminder_reason(subscription, summary, evaluation_time)

    if notification_type == SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED:
        return _obsolete_restricted_reminder_reason(subscription, summary, evaluation_time)

    return ""


def _obsolete_trial_reminder_reason(
    subscription: BusinessSubscription,
    summary: dict[str, Any],
    evaluation_time,
) -> str:
    if subscription.status != BusinessSubscription.Status.TRIALING:
        return "Reminder cancelled because the subscription is no longer trialing."
    if subscription.is_beta_plan:
        return "Reminder cancelled because beta subscriptions are excluded."
    trial_end = subscription.trial_end
    if not _is_aware_datetime(trial_end):
        return "Reminder cancelled because the trial end is missing or malformed."
    if evaluation_time >= trial_end:
        return "Reminder cancelled because the trial has ended."
    if _canonical_datetime(summary.get("trial_end")) != _canonical_datetime(trial_end):
        return "Reminder cancelled because the trial milestone changed."
    if _trial_cancellation_prevents_paid_renewal(subscription):
        return "Reminder cancelled because cancellation is scheduled before paid renewal."
    access_state = subscription.effective_access_state_at(evaluation_time)
    if access_state.mode != SubscriptionAccessMode.FULL:
        return "Reminder cancelled because trial access is no longer full."
    return ""


def _obsolete_grace_reminder_reason(
    subscription: BusinessSubscription,
    summary: dict[str, Any],
    evaluation_time,
) -> str:
    if subscription.status != BusinessSubscription.Status.PAST_DUE:
        return "Reminder cancelled because the subscription is no longer past due."
    if subscription.is_beta_plan:
        return "Reminder cancelled because beta subscriptions are excluded."
    if not _is_aware_datetime(subscription.past_due_since) or not _is_aware_datetime(
        subscription.grace_period_ends_at,
    ):
        return "Reminder cancelled because grace state is missing or malformed."
    if evaluation_time >= subscription.grace_period_ends_at:
        return "Reminder cancelled because grace has ended."
    if _canonical_datetime(summary.get("past_due_since")) != _canonical_datetime(
        subscription.past_due_since,
    ):
        return "Reminder cancelled because the payment-failure episode changed."
    if _canonical_datetime(summary.get("grace_period_ends_at")) != _canonical_datetime(
        subscription.grace_period_ends_at,
    ):
        return "Reminder cancelled because the grace boundary changed."
    access_state = subscription.effective_access_state_at(evaluation_time)
    if access_state.mode != SubscriptionAccessMode.FULL:
        return "Reminder cancelled because full grace access is no longer active."
    return ""


def _obsolete_restricted_reminder_reason(
    subscription: BusinessSubscription,
    summary: dict[str, Any],
    evaluation_time,
) -> str:
    if subscription.status != BusinessSubscription.Status.PAST_DUE:
        return "Reminder cancelled because the subscription is no longer past due."
    if subscription.is_beta_plan:
        return "Reminder cancelled because beta subscriptions are excluded."
    if not _is_aware_datetime(subscription.past_due_since) or not _is_aware_datetime(
        subscription.grace_period_ends_at,
    ):
        return "Reminder cancelled because grace state is missing or malformed."
    if evaluation_time < subscription.grace_period_ends_at:
        return "Reminder cancelled because restricted mode has not started."
    if _canonical_datetime(summary.get("past_due_since")) != _canonical_datetime(
        subscription.past_due_since,
    ):
        return "Reminder cancelled because the payment-failure episode changed."
    if _canonical_datetime(summary.get("grace_period_ends_at")) != _canonical_datetime(
        subscription.grace_period_ends_at,
    ):
        return "Reminder cancelled because the grace boundary changed."
    access_state = subscription.effective_access_state_at(evaluation_time)
    if access_state.mode != SubscriptionAccessMode.RESTRICTED:
        return "Reminder cancelled because the workspace is no longer restricted."
    return ""


def _subscription_for_enqueue(subscription: BusinessSubscription) -> BusinessSubscription:
    if not hasattr(subscription, "business") or not hasattr(subscription, "plan"):
        return BusinessSubscription.objects.select_related("business", "plan").get(pk=subscription.pk)
    return subscription


def _subscription_is_billable_for_notifications(subscription: BusinessSubscription) -> bool:
    return (
        subscription.payment_provider == BusinessSubscription.PaymentProvider.STRIPE
        and subscription.is_public_paid_plan
        and not subscription.is_beta_plan
        and subscription.business.is_active
        and subscription.plan.is_active
    )


def _subscription_has_valid_provider_identity(subscription: BusinessSubscription) -> bool:
    return (
        _subscription_is_billable_for_notifications(subscription)
        and subscription.business.is_active
        and subscription.plan.is_active
        and subscription.billing_interval
        in {
            BusinessSubscription.BillingInterval.MONTHLY,
            BusinessSubscription.BillingInterval.YEARLY,
        }
        and subscription.billing_currency
        in {
            BusinessSubscription.BillingCurrency.USD,
            BusinessSubscription.BillingCurrency.EUR,
        }
        and str(subscription.provider_customer_id or "").startswith("cus_")
        and str(subscription.provider_subscription_id or "").startswith("sub_")
        and str(subscription.provider_price_id or "").startswith("price_")
    )


def _validate_notification_type(notification_type: str) -> str:
    valid_types = {choice.value for choice in SubscriptionNotification.NotificationType}
    if notification_type not in valid_types:
        raise ValueError(f"Unsupported subscription notification type: {notification_type!r}")
    return notification_type


def _normalize_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if not email:
        return ""
    try:
        validate_email(email)
    except ValidationError:
        logger.warning("subscription_notification.invalid_owner_email")
        return ""
    return email


def _recipient_hash(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]


def _deduplication_context_key(deduplication_context: dict[str, Any] | str) -> str:
    if isinstance(deduplication_context, str):
        return deduplication_context.strip() or "default"
    parts = []
    for key in sorted(deduplication_context):
        parts.append(f"{key}={_context_value(deduplication_context[key])}")
    return "|".join(parts) or "default"


def _deduplication_key(
    *,
    subscription_id: int,
    notification_type: str,
    context_key: str,
    recipient_key: str,
) -> str:
    digest = hashlib.sha256(f"{context_key}|{recipient_key}".encode()).hexdigest()[:32]
    return f"subscription:{subscription_id}:{notification_type}:{digest}"


def _context_snapshot(
    *,
    subscription: BusinessSubscription,
    notification_type: str,
    extra_context: dict[str, Any],
) -> dict[str, Any]:
    snapshot = {
        "notification_type": notification_type,
        "business_name": subscription.business.name,
        "business_timezone": subscription.business.timezone or getattr(settings, "TIME_ZONE", "UTC"),
        "plan_name": subscription.plan.name,
        "plan_slug": subscription.plan.slug,
        "billing_interval": subscription.billing_interval,
        "billing_currency": subscription.billing_currency,
        "renewal_amount": _renewal_amount(subscription),
    }
    for key, value in extra_context.items():
        key = str(key)
        if _is_safe_context_key(key):
            snapshot[key] = _context_value(value)
    return snapshot


def _is_safe_context_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in {
        "provider_subscription_id",
        "provider_customer_id",
        "provider_price_id",
        "provider_checkout_session_id",
        "stripe_subscription_id",
        "stripe_customer_id",
        "stripe_price_id",
        "stripe_payload",
        "raw_payload",
        "payload",
    }:
        return False
    if normalized.startswith("provider_") and normalized.endswith("_id"):
        return False
    if any(term in normalized for term in ("secret", "card", "bank", "payment_method")):
        return False
    return True


def _renewal_amount(subscription: BusinessSubscription) -> str:
    interval = subscription.billing_interval
    currency = subscription.billing_currency
    if interval not in (
        BusinessSubscription.BillingInterval.MONTHLY,
        BusinessSubscription.BillingInterval.YEARLY,
    ):
        return ""

    region = (
        ClarivoPlan.EUR_PRICING_REGION
        if currency == BusinessSubscription.BillingCurrency.EUR
        else ClarivoPlan.USD_PRICING_REGION
    )
    pricing = subscription.plan.get_display_pricing(region=region)
    return (
        pricing["yearly_display"]
        if interval == BusinessSubscription.BillingInterval.YEARLY
        else pricing["monthly_display"]
    )


def _billing_interval_label(value: str) -> str:
    if value == BusinessSubscription.BillingInterval.YEARLY:
        return "yearly"
    if value == BusinessSubscription.BillingInterval.MONTHLY:
        return "monthly"
    return value or "not provided"


def _renewal_sentence(summary: dict[str, Any], billing_interval_label: str) -> str:
    renewal_amount = summary.get("renewal_amount") or ""
    if renewal_amount:
        return f"After the trial, the current plan renews at {renewal_amount} {billing_interval_label}."
    return f"After the trial, the current plan renews on the {billing_interval_label} billing interval."


def _trial_renewal_sentence(summary: dict[str, Any], billing_interval_label: str) -> str:
    if _summary_bool(summary.get("cancellation_scheduled")):
        return (
            "Cancellation is currently scheduled, so no automatic paid renewal is expected "
            "based on the local Stripe-synchronised state."
        )
    renewal_amount = summary.get("renewal_amount") or ""
    if renewal_amount:
        return (
            f"After the trial, this plan renews automatically at {renewal_amount} "
            f"{billing_interval_label} unless it is cancelled before the trial end."
        )
    return (
        f"After the trial, this plan renews automatically on the {billing_interval_label} "
        "billing interval unless it is cancelled before the trial end."
    )


def _summary_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _context_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _canonical_datetime(value)
    if value is None:
        return ""
    return str(value)


def _display_datetime(value: Any, display_timezone=None) -> str:
    if not value:
        return "Not provided"
    parsed = _parse_datetime(value)
    if parsed is None:
        return str(value)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    display_timezone = display_timezone or timezone.get_default_timezone()
    local_value = parsed.astimezone(display_timezone)
    hour = local_value.strftime("%I").lstrip("0") or "0"
    tz_label = local_value.tzname() or getattr(display_timezone, "key", "UTC")
    return (
        f"{local_value:%B} {local_value.day}, {local_value:%Y} "
        f"at {hour}:{local_value:%M} {local_value:%p} {tz_label}"
    )


def _display_timezone(summary: dict[str, Any], business) -> ZoneInfo:
    timezone_name = (
        str(summary.get("business_timezone") or getattr(business, "timezone", "") or "").strip()
        or getattr(settings, "TIME_ZONE", "UTC")
        or "UTC"
    )
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        try:
            return ZoneInfo(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _is_aware_datetime(value: Any) -> bool:
    return isinstance(value, datetime) and timezone.is_aware(value)


def _canonical_datetime(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return ""
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed.astimezone(UTC).isoformat()


def _trial_cancellation_prevents_paid_renewal(subscription: BusinessSubscription) -> bool:
    if not subscription.cancel_at_period_end:
        return False
    trial_end = subscription.trial_end
    if trial_end is None:
        return True
    scheduled_end = subscription._scheduled_access_end_at()
    return scheduled_end is None or scheduled_end <= trial_end


def _safe_error_summary(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: email delivery failed"


def _truncate_error(value: str) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned[:MAX_LAST_ERROR_LENGTH]
