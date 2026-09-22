from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from .models import (
    BusinessSubscription,
    BusinessUser,
    SubscriptionAccessMode,
    SubscriptionNotification,
)
from .plan_catalog import (
    PUBLIC_BILLING_INTERVALS,
    PUBLIC_PAID_PLAN_SLUGS,
    PUBLIC_PRICING_CURRENCIES,
)
from .subscription_notifications import (
    enqueue_subscription_notification_with_result,
    is_subscription_reminder_notification_type,
)

logger = logging.getLogger(__name__)

TRIAL_THREE_DAY_MIN_REMAINING = timedelta(hours=24)
TRIAL_THREE_DAY_MAX_REMAINING = timedelta(hours=72)
TRIAL_ONE_DAY_MAX_REMAINING = timedelta(hours=24)
GRACE_ONE_DAY_MAX_REMAINING = timedelta(hours=24)

REMINDER_NOTIFICATION_TYPES = frozenset(
    {
        SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS,
        SubscriptionNotification.NotificationType.TRIAL_ENDING_1_DAY,
        SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY,
        SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED,
    }
)


@dataclass(frozen=True)
class DueSubscriptionReminder:
    notification_type: str
    deduplication_context: dict[str, Any]
    context_summary: dict[str, Any]


@dataclass
class SubscriptionReminderEnqueueSummary:
    evaluation_time: datetime
    candidate_count: int = 0
    evaluated_count: int = 0
    created_counts: Counter = field(default_factory=Counter)
    duplicate_count: int = 0
    ineligible_or_stale_count: int = 0
    malformed_state_count: int = 0

    @property
    def created_total(self) -> int:
        return sum(self.created_counts.values())


def enqueue_due_subscription_reminders(
    *,
    evaluation_time=None,
    limit: int | None = None,
    dry_run: bool = False,
    notification_type: str | None = None,
) -> SubscriptionReminderEnqueueSummary:
    evaluation_time = _normalize_evaluation_time(evaluation_time)
    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than zero.")
    if notification_type:
        notification_type = _validate_reminder_type(notification_type)

    logger.info(
        "subscription_reminders.command_started",
        extra={
            "evaluation_time": evaluation_time.isoformat(),
            "limit": limit,
            "dry_run": dry_run,
            "notification_type": notification_type or "",
        },
    )
    candidates = _candidate_subscriptions(
        evaluation_time=evaluation_time,
        notification_type=notification_type,
    )
    candidate_count = candidates.count()
    if limit is not None:
        candidates = candidates[:limit]

    summary = SubscriptionReminderEnqueueSummary(
        evaluation_time=evaluation_time,
        candidate_count=candidate_count,
    )
    logger.info(
        "subscription_reminders.candidates_loaded",
        extra={"candidate_count": candidate_count},
    )

    for subscription in candidates.iterator(chunk_size=200):
        summary.evaluated_count += 1
        try:
            due_reminders = _due_reminders_for_subscription(
                subscription=subscription,
                evaluation_time=evaluation_time,
                notification_type=notification_type,
            )
        except Exception:
            summary.malformed_state_count += 1
            logger.exception(
                "subscription_reminders.malformed_state_skipped",
                extra={"subscription_id": subscription.pk},
            )
            continue

        if not due_reminders:
            summary.ineligible_or_stale_count += 1
            logger.info(
                "subscription_reminders.stale_state_skipped",
                extra={"subscription_id": subscription.pk},
            )
            continue

        for reminder in due_reminders:
            enqueue_result = enqueue_subscription_notification_with_result(
                subscription=subscription,
                notification_type=reminder.notification_type,
                deduplication_context=reminder.deduplication_context,
                context_summary=reminder.context_summary,
                available_at=evaluation_time,
                dry_run=dry_run,
            )
            summary.created_counts[reminder.notification_type] += enqueue_result.created_count
            summary.duplicate_count += enqueue_result.duplicate_count
            if enqueue_result.created_count:
                logger.info(
                    "subscription_reminders.reminder_enqueued",
                    extra={
                        "subscription_id": subscription.pk,
                        "notification_type": reminder.notification_type,
                        "created_count": enqueue_result.created_count,
                        "dry_run": dry_run,
                    },
                )
            if enqueue_result.duplicate_count:
                logger.info(
                    "subscription_reminders.duplicate_skipped",
                    extra={
                        "subscription_id": subscription.pk,
                        "notification_type": reminder.notification_type,
                        "duplicate_count": enqueue_result.duplicate_count,
                    },
                )

    logger.info(
        "subscription_reminders.command_summary",
        extra={
            "evaluated_count": summary.evaluated_count,
            "created_total": summary.created_total,
            "duplicate_count": summary.duplicate_count,
            "ineligible_or_stale_count": summary.ineligible_or_stale_count,
            "malformed_state_count": summary.malformed_state_count,
        },
    )
    return summary


def _candidate_subscriptions(*, evaluation_time, notification_type: str | None):
    trial_three_day_end = evaluation_time + TRIAL_THREE_DAY_MAX_REMAINING
    trial_one_day_end = evaluation_time + TRIAL_ONE_DAY_MAX_REMAINING
    grace_one_day_end = evaluation_time + GRACE_ONE_DAY_MAX_REMAINING
    query = Q()

    if notification_type in (None, SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS):
        query |= Q(
            status=BusinessSubscription.Status.TRIALING,
            cancel_at_period_end=False,
            trial_end__gt=evaluation_time + TRIAL_THREE_DAY_MIN_REMAINING,
            trial_end__lte=trial_three_day_end,
        )
    if notification_type in (None, SubscriptionNotification.NotificationType.TRIAL_ENDING_1_DAY):
        query |= Q(
            status=BusinessSubscription.Status.TRIALING,
            cancel_at_period_end=False,
            trial_end__gt=evaluation_time,
            trial_end__lte=trial_one_day_end,
        )
    if notification_type in (
        None,
        SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY,
    ):
        query |= Q(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since__isnull=False,
            grace_period_ends_at__gt=evaluation_time,
            grace_period_ends_at__lte=grace_one_day_end,
        )
    if notification_type in (
        None,
        SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED,
    ):
        query |= Q(
            status=BusinessSubscription.Status.PAST_DUE,
            past_due_since__isnull=False,
            grace_period_ends_at__lte=evaluation_time,
        )

    owner_memberships = BusinessUser.objects.filter(
        role=BusinessUser.Role.OWNER,
        is_active=True,
        user__is_active=True,
    ).select_related("user").order_by("created_at", "pk")

    return (
        BusinessSubscription.objects.filter(
            query,
            business__is_active=True,
            plan__is_active=True,
            plan__slug__in=PUBLIC_PAID_PLAN_SLUGS,
            payment_provider=BusinessSubscription.PaymentProvider.STRIPE,
            billing_interval__in=PUBLIC_BILLING_INTERVALS,
            billing_currency__in=PUBLIC_PRICING_CURRENCIES,
            provider_customer_id__startswith="cus_",
            provider_subscription_id__startswith="sub_",
            provider_price_id__startswith="price_",
        )
        .select_related("business", "plan")
        .prefetch_related(
            Prefetch(
                "business__memberships",
                queryset=owner_memberships,
                to_attr="_subscription_notification_owner_memberships",
            )
        )
        .order_by("pk")
    )


def _due_reminders_for_subscription(
    *,
    subscription: BusinessSubscription,
    evaluation_time,
    notification_type: str | None,
) -> list[DueSubscriptionReminder]:
    if subscription.status == BusinessSubscription.Status.TRIALING:
        reminder = _due_trial_reminder(subscription, evaluation_time)
        if reminder and _matches_type_filter(reminder, notification_type):
            return [reminder]
        return []

    if subscription.status == BusinessSubscription.Status.PAST_DUE:
        reminder = _due_past_due_reminder(subscription, evaluation_time)
        if reminder and _matches_type_filter(reminder, notification_type):
            return [reminder]
        return []

    return []


def _due_trial_reminder(
    subscription: BusinessSubscription,
    evaluation_time,
) -> DueSubscriptionReminder | None:
    if not _trial_reminder_base_eligible(subscription, evaluation_time):
        return None

    remaining = subscription.trial_end - evaluation_time
    if TRIAL_THREE_DAY_MIN_REMAINING < remaining <= TRIAL_THREE_DAY_MAX_REMAINING:
        notification_type = SubscriptionNotification.NotificationType.TRIAL_ENDING_3_DAYS
    elif timedelta(0) < remaining <= TRIAL_ONE_DAY_MAX_REMAINING:
        notification_type = SubscriptionNotification.NotificationType.TRIAL_ENDING_1_DAY
    else:
        return None

    return DueSubscriptionReminder(
        notification_type=notification_type,
        deduplication_context={notification_type: subscription.trial_end},
        context_summary={
            "trial_end": subscription.trial_end,
            "cancellation_scheduled": False,
            "action_path": reverse("business_subscription"),
            "action_label": "Manage subscription",
        },
    )


def _due_past_due_reminder(
    subscription: BusinessSubscription,
    evaluation_time,
) -> DueSubscriptionReminder | None:
    if not _past_due_base_eligible(subscription):
        return None

    access_state = subscription.effective_access_state_at(evaluation_time)
    grace_remaining = subscription.grace_period_ends_at - evaluation_time

    if timedelta(0) < grace_remaining <= GRACE_ONE_DAY_MAX_REMAINING:
        if access_state.mode != SubscriptionAccessMode.FULL:
            return None
        notification_type = SubscriptionNotification.NotificationType.PAYMENT_GRACE_ENDING_1_DAY
        return DueSubscriptionReminder(
            notification_type=notification_type,
            deduplication_context={
                notification_type: subscription.grace_period_ends_at,
                "past_due_since": subscription.past_due_since,
            },
            context_summary={
                "past_due_since": subscription.past_due_since,
                "grace_period_ends_at": subscription.grace_period_ends_at,
                "access_mode": access_state.mode,
                "action_path": reverse("business_subscription"),
                "action_label": "Review payment recovery",
            },
        )

    if evaluation_time >= subscription.grace_period_ends_at:
        if access_state.mode != SubscriptionAccessMode.RESTRICTED:
            return None
        notification_type = SubscriptionNotification.NotificationType.RESTRICTED_MODE_STARTED
        return DueSubscriptionReminder(
            notification_type=notification_type,
            deduplication_context={
                notification_type: subscription.grace_period_ends_at,
                "past_due_since": subscription.past_due_since,
            },
            context_summary={
                "past_due_since": subscription.past_due_since,
                "grace_period_ends_at": subscription.grace_period_ends_at,
                "restricted_mode_started_at": subscription.grace_period_ends_at,
                "access_mode": access_state.mode,
                "action_path": reverse("business_subscription"),
                "action_label": "Review payment recovery",
            },
        )

    return None


def _trial_reminder_base_eligible(
    subscription: BusinessSubscription,
    evaluation_time,
) -> bool:
    if not _provider_identity_is_internally_consistent(subscription):
        return False
    if subscription.status != BusinessSubscription.Status.TRIALING:
        return False
    if not _is_aware_datetime(subscription.trial_end):
        return False
    if evaluation_time >= subscription.trial_end:
        return False
    if _trial_cancellation_prevents_paid_renewal(subscription):
        return False
    access_state = subscription.effective_access_state_at(evaluation_time)
    return access_state.mode == SubscriptionAccessMode.FULL


def _past_due_base_eligible(subscription: BusinessSubscription) -> bool:
    return (
        _provider_identity_is_internally_consistent(subscription)
        and subscription.status == BusinessSubscription.Status.PAST_DUE
        and _is_aware_datetime(subscription.past_due_since)
        and _is_aware_datetime(subscription.grace_period_ends_at)
        and subscription.grace_period_ends_at >= subscription.past_due_since
    )


def _provider_identity_is_internally_consistent(subscription: BusinessSubscription) -> bool:
    return (
        subscription.business.is_active
        and subscription.plan.is_active
        and subscription.payment_provider == BusinessSubscription.PaymentProvider.STRIPE
        and subscription.plan.slug in PUBLIC_PAID_PLAN_SLUGS
        and subscription.billing_interval in PUBLIC_BILLING_INTERVALS
        and subscription.billing_currency in PUBLIC_PRICING_CURRENCIES
        and not subscription.is_beta_plan
        and str(subscription.provider_customer_id or "").startswith("cus_")
        and str(subscription.provider_subscription_id or "").startswith("sub_")
        and str(subscription.provider_price_id or "").startswith("price_")
    )


def _trial_cancellation_prevents_paid_renewal(subscription: BusinessSubscription) -> bool:
    if not subscription.cancel_at_period_end:
        return False
    trial_end = subscription.trial_end
    if trial_end is None:
        return True
    scheduled_end = subscription._scheduled_access_end_at()
    return scheduled_end is None or scheduled_end <= trial_end


def _matches_type_filter(
    reminder: DueSubscriptionReminder,
    notification_type: str | None,
) -> bool:
    return notification_type in (None, reminder.notification_type)


def _validate_reminder_type(notification_type: str) -> str:
    if not is_subscription_reminder_notification_type(notification_type):
        raise ValueError(f"Unsupported subscription reminder type: {notification_type!r}")
    return notification_type


def _normalize_evaluation_time(evaluation_time) -> datetime:
    evaluation_time = evaluation_time or timezone.now()
    if timezone.is_naive(evaluation_time):
        raise ValueError("evaluation_time must be timezone-aware.")
    return evaluation_time


def _is_aware_datetime(value) -> bool:
    return isinstance(value, datetime) and timezone.is_aware(value)
