from __future__ import annotations

import logging
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.businesses.models import BusinessSubscription, SubscriptionAccessMode

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Reconcile local Motionmate subscription access states without contacting Stripe."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report subscription access changes without writing them.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        now = timezone.now()
        counts: Counter[str] = Counter()

        queryset = BusinessSubscription.objects.select_related("business", "plan").order_by("pk")
        for subscription in queryset.iterator(chunk_size=500):
            access_state = subscription.effective_access_state_at(now)
            if access_state.mode == SubscriptionAccessMode.FULL:
                counts["access_mode_full"] += 1
            elif access_state.mode == SubscriptionAccessMode.RESTRICTED:
                counts["access_mode_restricted"] += 1
            else:
                counts["access_mode_none"] += 1

            self._reconcile_subscription(
                subscription=subscription,
                now=now,
                dry_run=dry_run,
                counts=counts,
            )

        if dry_run:
            self.stdout.write("Dry run only; no subscription records were changed.")

        summary = (
            ("Full access", "access_mode_full"),
            ("Restricted after grace", "access_mode_restricted"),
            ("No access", "access_mode_none"),
            ("Expired local trials", "expired_local_trials"),
            ("Completed scheduled cancellations", "completed_scheduled_cancellations"),
            (
                "Expired provider trials requiring reconciliation",
                "expired_provider_trials_requiring_reconciliation",
            ),
            (
                "Stale provider subscriptions requiring reconciliation",
                "stale_provider_subscriptions_requiring_reconciliation",
            ),
            ("Past due within grace", "past_due_within_grace"),
            ("Past due grace expired", "past_due_grace_expired"),
            ("Past due missing grace fields", "past_due_missing_grace_fields"),
            ("Past-due subscriptions unchanged", "past_due_subscriptions_unchanged"),
            ("Beta subscriptions unchanged", "beta_subscriptions_unchanged"),
            ("Future trials unchanged", "future_trials_unchanged"),
            ("Other subscriptions unchanged", "other_subscriptions_unchanged"),
        )
        for label, key in summary:
            self.stdout.write(f"{label}: {counts[key]}")

    def _reconcile_subscription(
        self,
        *,
        subscription: BusinessSubscription,
        now,
        dry_run: bool,
        counts: Counter[str],
    ) -> None:
        if subscription.is_beta_plan:
            counts["beta_subscriptions_unchanged"] += 1
            return

        if subscription.status == BusinessSubscription.Status.PAST_DUE:
            access_state = subscription.effective_access_state_at(now)
            if access_state.code == BusinessSubscription.AccessCode.PAST_DUE_GRACE:
                counts["past_due_within_grace"] += 1
                return
            if access_state.code == BusinessSubscription.AccessCode.PAST_DUE_GRACE_EXPIRED:
                counts["past_due_grace_expired"] += 1
                return
            if access_state.code == BusinessSubscription.AccessCode.PAST_DUE_MISSING_GRACE_STATE:
                counts["past_due_missing_grace_fields"] += 1
                return
            counts["past_due_subscriptions_unchanged"] += 1
            return

        if (
            subscription.cancel_at_period_end
            and subscription.status
            in (BusinessSubscription.Status.TRIALING, BusinessSubscription.Status.ACTIVE)
            and subscription.current_period_end is not None
            and subscription.current_period_end <= now
        ):
            if self._transition_subscription(
                subscription=subscription,
                target_status=BusinessSubscription.Status.CANCELLED,
                reason="completed_scheduled_cancellation",
                dry_run=dry_run,
            ):
                counts["completed_scheduled_cancellations"] += 1
            return

        if subscription.status == BusinessSubscription.Status.TRIALING:
            if subscription.trial_end is None:
                counts["other_subscriptions_unchanged"] += 1
                return

            if subscription.trial_end <= now:
                if subscription.is_provider_backed:
                    counts["expired_provider_trials_requiring_reconciliation"] += 1
                    return

                if self._transition_subscription(
                    subscription=subscription,
                    target_status=BusinessSubscription.Status.EXPIRED,
                    reason="local_trial_expired",
                    dry_run=dry_run,
                ):
                    counts["expired_local_trials"] += 1
                return

            counts["future_trials_unchanged"] += 1
            return

        if (
            subscription.status == BusinessSubscription.Status.ACTIVE
            and subscription.is_provider_backed
        ):
            if subscription.current_period_end is None or subscription.current_period_end <= now:
                counts["stale_provider_subscriptions_requiring_reconciliation"] += 1
                return

        counts["other_subscriptions_unchanged"] += 1

    def _transition_subscription(
        self,
        *,
        subscription: BusinessSubscription,
        target_status: str,
        reason: str,
        dry_run: bool,
    ) -> bool:
        if dry_run:
            return True

        with transaction.atomic():
            locked_subscription = BusinessSubscription.objects.select_for_update().get(
                pk=subscription.pk
            )
            if locked_subscription.status != subscription.status:
                return False

            locked_subscription.status = target_status
            locked_subscription.save(update_fields=["status", "updated_at"])

        logger.info(
            "subscription_access.reconciled",
            extra={
                "subscription_id": subscription.pk,
                "business_id": subscription.business_id,
                "prior_status": subscription.status,
                "resulting_status": target_status,
                "reason": reason,
            },
        )
        return True
