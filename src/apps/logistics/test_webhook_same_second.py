"""Same-second tier events reconcile current provider state without losing ID deduplication."""

from unittest import mock, skipUnless

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings

from apps.businesses.models import (
    BillingProviderWebhookEvent,
    BusinessSubscription,
    SubscriptionNotification,
)

from . import test_tier_checkout as tier_tests
from .test_tier_checkout import TIER_SETTINGS, TierCheckoutFixture


class SameSecondFixture(TierCheckoutFixture):
    def start(self):
        self.checkout()
        self.deliver("active", "evt_start", source="customer.subscription.created")
        self.sdk.Subscription.retrieve.reset_mock()

    def deliver(
        self, status, event_id, *, offset=0, client=None, source="customer.subscription.updated"
    ):
        return self.signed_event(
            obj=self.remote_subscription(status=status),
            source=source,
            event_id=event_id,
            offset=offset,
            client=client,
        )

    def provider_now(self, status):
        self.sdk.Subscription.retrieve.side_effect = (
            lambda *args, **kwargs: self.remote_subscription(status=status)
        )

    def subscription_values(self):
        return BusinessSubscription.objects.values().get(pk=self.subscription.pk)

    def assert_status(self, expected):
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, expected)


@override_settings(**TIER_SETTINGS)
class SameSecondWebhookTests(SameSecondFixture, TestCase):
    def test_distinct_events_in_same_second_apply_current_payment_failure(self):
        self.start()
        self.provider_now("past_due")
        self.assertEqual(self.deliver("past_due", "evt_failure").status_code, 200)
        self.assert_status("past_due")
        self.assertIsNotNone(self.subscription.grace_period_ends_at)
        self.assertEqual(BillingProviderWebhookEvent.objects.count(), 2)
        self.assertEqual(self.sdk.Subscription.retrieve.call_count, 1)
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type="payment_grace_started"
            ).count(),
            1,
        )

    def test_reversed_same_second_snapshots_cannot_reverse_current_state(self):
        self.start()
        for current in ("past_due", "active", "canceled"):
            self.provider_now(current)
            for index, status in enumerate(("past_due", "active", "active", "past_due")):
                event_id = f"evt_{current}_{index}"
                self.assertEqual(self.deliver(status, event_id).status_code, 200)
                self.assert_status("cancelled" if current == "canceled" else current)
                self.assertEqual(
                    BillingProviderWebhookEvent.objects.get(event_id=event_id).status, "processed"
                )

    def test_duplicate_id_after_recovery_cannot_replay_failure_or_extend_grace(self):
        self.start()
        self.provider_now("past_due")
        self.deliver("past_due", "evt_failure")
        self.provider_now("active")
        self.deliver("active", "evt_recovery")
        before = self.subscription_values()
        count = self.sdk.Subscription.retrieve.call_count
        self.provider_now("past_due")
        self.deliver("past_due", "evt_failure")
        self.assertEqual(self.subscription_values(), before)
        self.assertEqual(self.sdk.Subscription.retrieve.call_count, count)
        self.assertEqual(
            BillingProviderWebhookEvent.objects.get(event_id="evt_failure").attempt_count, 1
        )

    def test_older_payment_snapshot_does_not_reverse_newer_cancellation(self):
        self.start()
        self.deliver("canceled", "evt_cancel", offset=2)
        self.assert_status("cancelled")
        before = self.subscription_values()
        self.sdk.Subscription.retrieve.side_effect = AssertionError(
            "Stale events must not reconcile"
        )
        self.deliver("active", "evt_old_paid", offset=1)
        self.assertEqual(self.subscription_values(), before)
        self.sdk.Subscription.retrieve.assert_not_called()

    def test_same_second_paid_invoice_cannot_undo_current_cancellation(self):
        self.start()
        self.provider_now("canceled")
        self.deliver("canceled", "evt_cancel")
        before = self.subscription_values()
        invoice = {
            "id": "in_old_payment",
            "subscription": f"sub_tier_{self.business.pk}",
            "customer": f"cus_tier_{self.business.pk}",
            "livemode": False,
            "currency": "eur",
        }
        self.assertEqual(
            self.signed_event(
                obj=invoice, source="invoice.paid", event_id="evt_old_paid"
            ).status_code,
            200,
        )
        self.assertEqual(self.subscription_values(), before)
        self.assertEqual(
            BillingProviderWebhookEvent.objects.get(event_id="evt_old_paid").status, "processed"
        )

    def test_same_second_nonstatus_changes_are_reconciled(self):
        self.start()
        self.sdk.Subscription.retrieve.side_effect = (
            lambda *args, **kwargs: self.remote_subscription(cancel_at_period_end=True)
        )
        remote = self.remote_subscription(cancel_at_period_end=True)
        self.signed_event(
            obj=remote, source="customer.subscription.updated", event_id="evt_cancel_scheduled"
        )
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.cancel_at_period_end)
        self.assertEqual(self.subscription.status, "active")

    def test_failed_provider_read_is_retryable_without_partial_state(self):
        self.start()
        before = self.subscription_values()
        self.sdk.Subscription.retrieve.side_effect = RuntimeError("private provider detail")
        self.assertEqual(self.deliver("past_due", "evt_retry").status_code, 500)
        self.assertEqual(self.subscription_values(), before)
        event = BillingProviderWebhookEvent.objects.get(event_id="evt_retry")
        self.assertEqual(event.status, "failed")
        self.assertNotIn("private provider detail", event.last_error)
        self.provider_now("past_due")
        self.assertEqual(self.deliver("past_due", "evt_retry").status_code, 200)
        self.assert_status("past_due")
        event.refresh_from_db()
        self.assertEqual(event.attempt_count, 2)
        self.assertEqual(event.status, "processed")

    def test_retrieved_state_repeats_identity_price_and_approval_validation(self):
        self.start()
        original = self.subscription_values()
        for index, changes in enumerate(
            (
                {"id": "sub_foreign"},
                {"customer": "cus_foreign"},
                {"metadata": {}},
                {"livemode": True},
                {"currency": "usd"},
                {
                    "items": {
                        "data": [
                            {
                                "quantity": 1,
                                "price": {"id": "price_wrong", "recurring": {"interval": "year"}},
                            }
                        ]
                    }
                },
            )
        ):
            self.sdk.Subscription.retrieve.side_effect = None
            self.sdk.Subscription.retrieve.return_value = self.remote_subscription(**changes)
            self.deliver("past_due", f"evt_invalid_current_{index}")
            self.assertEqual(self.subscription_values(), original)
            self.assertEqual(
                BillingProviderWebhookEvent.objects.get(
                    event_id=f"evt_invalid_current_{index}"
                ).status,
                "failed",
            )

    def test_event_completion_and_state_roll_back_together(self):
        self.start()
        self.provider_now("past_due")
        before = self.subscription_values()
        with mock.patch(
            "apps.businesses.stripe_webhooks.mark_stripe_webhook_processed",
            side_effect=RuntimeError("commit failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.deliver("past_due", "evt_commit_retry")
        self.assertEqual(self.subscription_values(), before)
        self.assertFalse(
            SubscriptionNotification.objects.filter(
                notification_type="payment_grace_started"
            ).exists()
        )
        self.deliver("past_due", "evt_commit_retry")
        self.assert_status("past_due")
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type="payment_grace_started"
            ).count(),
            1,
        )


@skipUnless(connection.vendor == "postgresql", "Row-lock verification requires PostgreSQL")
@override_settings(**TIER_SETTINGS)
class SameSecondConcurrencyTests(SameSecondFixture, TransactionTestCase):
    parallel = tier_tests.TierCheckoutConcurrencyTests.parallel

    def test_distinct_same_second_events_converge_with_one_grace_transition(self):
        self.start()
        self.provider_now("past_due")
        responses = self.parallel(
            [
                lambda: self.deliver("active", "evt_old_snapshot", client=Client()).status_code,
                lambda: self.deliver("past_due", "evt_new_snapshot", client=Client()).status_code,
            ]
        )
        self.assertEqual(responses, [200, 200])
        self.assert_status("past_due")
        self.assertEqual(self.sdk.Subscription.retrieve.call_count, 2)
        self.assertEqual(BillingProviderWebhookEvent.objects.filter(status="processed").count(), 3)
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type="payment_grace_started"
            ).count(),
            1,
        )

    def test_concurrent_duplicate_id_reconciles_and_transitions_once(self):
        self.start()
        self.provider_now("past_due")
        self.assertEqual(
            self.parallel(
                [
                    lambda: self.deliver("past_due", "evt_duplicate", client=Client()).status_code
                    for _ in range(2)
                ]
            ),
            [200, 200],
        )
        self.assert_status("past_due")
        self.assertEqual(self.sdk.Subscription.retrieve.call_count, 1)
        self.assertEqual(BillingProviderWebhookEvent.objects.count(), 2)
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type="payment_grace_started"
            ).count(),
            1,
        )

    def test_newer_cancellation_wins_racing_older_payment_snapshot(self):
        self.start()
        self.provider_now("canceled")
        self.parallel(
            [
                lambda: self.deliver("active", "evt_old_payment", client=Client()).status_code,
                lambda: self.deliver(
                    "canceled", "evt_new_cancel", offset=1, client=Client()
                ).status_code,
            ]
        )
        self.assert_status("cancelled")
