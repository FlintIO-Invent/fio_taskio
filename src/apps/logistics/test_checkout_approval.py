from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import mock, skipUnless

from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from apps.businesses.models import (
    BillingProviderWebhookEvent,
    BusinessSubscription,
    ClarivoPlan,
    SubscriptionNotification,
)
from apps.businesses.stripe_checkout import (
    StripeCheckoutError,
    create_trial_checkout_session,
    resume_trial_checkout_session,
)
from apps.businesses.test_logistics_billing import stripe_settings

from .services import review_application
from .test_checkout import LogisticsCheckoutFixture
from .test_enrollment import approve
from .tests import PILOT_POLICY


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, **stripe_settings())
class LogisticsCheckoutApprovalTests(LogisticsCheckoutFixture, TestCase):
    def review(self, result):
        self.application.refresh_from_db()
        return review_application(
            self.application.pk,
            result=result,
            actor=self.actor,
            reason="Approval checkout reconciliation test",
            expected_revision=self.application.revision,
        )

    def assert_held(self):
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.logistics_approval_review_required)
        self.assertFalse(self.subscription.has_access)
        self.assertFalse(self.subscription.has_restricted_access)
        self.assertFalse(self.subscription.effective_access_state.can_resume_checkout)

    def test_stale_revision_cannot_reuse_pending_session(self):
        self.checkout()
        with self.captureOnCommitCallbacks(execute=True):
            self.application.phone = "+31 20 000 2222"
            self.application.save()
        self.sessions.expire.assert_called_once_with("cs_logistics_1")
        self.assert_held()
        for checkout in (
            self.checkout,
            lambda: resume_trial_checkout_session(
                request=self.factory.post("/"), subscription=self.subscription, user=self.user
            ),
        ):
            with self.assertRaises(StripeCheckoutError):
                checkout()
        self.assertEqual(self.sessions.create.call_count, 1)

    def test_decline_and_withdraw_invalidate_pending_session_and_checkout(self):
        for result in ("DECLINED", "WITHDRAWN"):
            with self.subTest(result=result):
                # Separate application lifecycle for terminal withdrawal.
                if result == "WITHDRAWN":
                    approve(self.application, self.actor)
                self.checkout()
                self.sessions.expire.reset_mock()
                with self.captureOnCommitCallbacks(execute=True):
                    self.review(result)
                self.subscription.refresh_from_db()
                self.sessions.expire.assert_called_once_with(
                    self.subscription.provider_checkout_session_id
                )
                self.assert_held()
                with self.assertRaises(StripeCheckoutError):
                    self.checkout()

    def test_revocation_survives_provider_expiration_failure_and_retry_fails_closed(self):
        self.checkout()
        self.sessions.expire.side_effect = RuntimeError("private provider failure")
        with self.assertLogs("apps.logistics.checkout_approval", level="WARNING") as logs:
            with self.captureOnCommitCallbacks(execute=True):
                self.review("DECLINED")
        self.assertNotIn("private provider failure", " ".join(logs.output))
        self.assert_held()
        self.review("APPROVED")
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        self.assertEqual(self.sessions.create.call_count, 1)

    def test_same_revision_reapproval_requires_new_bound_session_and_retry_is_idempotent(self):
        self.checkout()
        original_metadata = self.remote_session()["metadata"]
        self.review("DECLINED")
        self.review("APPROVED")
        self.application.refresh_from_db()
        self.assertEqual(self.application.revision, 1)
        self.checkout()
        new_metadata = self.sessions.create.call_args.kwargs["metadata"]
        self.assertNotEqual(
            new_metadata["logistics_approval_decision_id"],
            original_metadata["logistics_approval_decision_id"],
        )
        self.assertEqual(new_metadata["logistics_application_revision"], "1")
        self.sessions.expire.assert_called_once_with("cs_logistics_1")
        self.checkout()
        self.assertEqual(self.sessions.create.call_count, 2)

    def test_legacy_session_without_approval_binding_is_expired_before_replacement(self):
        self.checkout()
        session = self.remote_session()
        session["metadata"] = {
            key: value
            for key, value in session["metadata"].items()
            if not key.startswith("logistics_")
        }
        self.sessions.retrieve.side_effect = None
        self.sessions.retrieve.return_value = session
        self.checkout()
        self.sessions.expire.assert_called_once_with("cs_logistics_1")
        self.assertEqual(self.sessions.create.call_count, 2)

    def test_replacement_provider_failure_retries_with_same_approval_idempotency_key(self):
        self.checkout()
        self.review("DECLINED")
        self.review("APPROVED")
        expired = self.remote_session(status="expired")
        self.sessions.retrieve.side_effect = None
        self.sessions.retrieve.return_value = expired
        create = self.sessions.create.side_effect
        self.sessions.create.side_effect = RuntimeError("Temporary provider failure")
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        key = self.sessions.create.call_args.kwargs["idempotency_key"]
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.provider_checkout_session_id, "cs_logistics_1")
        self.sessions.create.side_effect = create
        self.checkout()
        self.assertEqual(self.sessions.create.call_args.kwargs["idempotency_key"], key)

    def test_revocation_rollback_does_not_expire_provider_or_invalidate_locally(self):
        self.checkout()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    self.review("DECLINED")
                    raise RuntimeError("rollback review")
        self.sessions.expire.assert_not_called()
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "APPROVED")
        self.checkout()
        self.assertEqual(self.sessions.create.call_count, 1)

    def test_late_success_is_acknowledged_deduplicated_and_held_for_manual_review(self):
        self.checkout()
        self.review("DECLINED")
        for _ in range(2):
            self.assertEqual(self.webhook().status_code, 200)
        self.assert_held()
        self.assertEqual(self.subscription.status, "suspended")
        self.assertEqual(self.subscription.provider_subscription_id, "sub_logistics")
        self.assertEqual(self.subscription.provider_customer_id, "cus_logistics")
        ledger = BillingProviderWebhookEvent.objects.get(event_id="evt_logistics_paid")
        self.assertEqual(ledger.status, "processed")
        self.assertEqual(ledger.attempt_count, 1)
        self.assertIn("admin review", ledger.payload_summary["result"])
        self.assertFalse(SubscriptionNotification.objects.exists())
        self.review("APPROVED")
        self.assertEqual(
            self.webhook(
                event_type="customer.subscription.updated", event_id="evt_later", offset=10
            ).status_code,
            200,
        )
        self.assert_held()
        self.assertEqual(self.subscription.status, "suspended")

    def test_late_payment_after_material_change_cannot_activate_even_with_local_bypass(self):
        self.checkout()
        self.application.phone = "+31 20 000 3333"
        self.application.save()
        with override_settings(
            DEBUG=True, MOTIONMATE_ENVIRONMENT="local", LOGISTICS_LOCAL_BILLING_BYPASS=True
        ):
            self.assertEqual(self.webhook().status_code, 200)
            self.assert_held()
        self.assertFalse(SubscriptionNotification.objects.exists())

    def test_session_and_subscription_must_both_carry_current_approval_binding(self):
        self.checkout()
        session = self.remote_session(status="complete")
        session["metadata"]["logistics_application_revision"] = "0"
        with mock.patch.object(self, "remote_session", return_value=session):
            self.assertEqual(self.webhook().status_code, 200)
        self.assert_held()

    def test_approval_revocation_after_activation_denies_access_and_future_paid_events(self):
        self.checkout()
        self.assertEqual(self.webhook().status_code, 200)
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.has_access)
        self.review("DECLINED")
        self.assert_held()
        self.assertEqual(
            self.webhook(
                event_type="invoice.paid", event_id="evt_paid_after_revocation", offset=10
            ).status_code,
            200,
        )
        self.assert_held()
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.SUSPENDED)

    def test_old_approval_payment_after_reapproval_is_still_held(self):
        self.checkout()
        self.review("DECLINED")
        self.review("APPROVED")
        self.assertEqual(self.webhook().status_code, 200)
        self.assert_held()

    def test_withdrawn_enrollment_late_success_is_held(self):
        self.checkout()
        self.review("WITHDRAWN")
        self.assertEqual(self.webhook().status_code, 200)
        self.assert_held()
        self.assertFalse(SubscriptionNotification.objects.exists())

    def test_legacy_paid_subscription_without_binding_requires_manual_review(self):
        self.checkout()
        remote = self.remote_subscription()
        remote["metadata"] = {
            key: value
            for key, value in remote["metadata"].items()
            if not key.startswith("logistics_")
        }
        self.assertEqual(self.webhook(remote=remote).status_code, 200)
        self.assert_held()

    def test_business_snapshot_mismatch_cannot_reuse_checkout(self):
        from .models import LogisticsApplication

        self.checkout()
        LogisticsApplication.objects.filter(pk=self.application.pk).update(
            business_id_snapshot=self.business.pk + 1
        )
        with self.assertRaises(StripeCheckoutError):
            self.checkout()
        self.assertEqual(self.sessions.create.call_count, 1)

    def test_invalid_billing_dimensions_do_not_prevent_approval_revocation(self):
        self.checkout()
        BusinessSubscription.objects.filter(pk=self.subscription.pk).update(
            billing_interval="monthly"
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.review("DECLINED")
        self.assert_held()
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "DECLINED")
        self.sessions.expire.assert_called_once_with("cs_logistics_1")

    def test_direct_creation_entry_point_expires_old_approval_and_reuses_valid_retry(self):
        self.checkout()
        self.review("DECLINED")
        self.review("APPROVED")
        for _ in range(2):
            create_trial_checkout_session(
                request=self.factory.post("/"), subscription=self.subscription, user=self.user
            )
        self.sessions.expire.assert_called_once_with("cs_logistics_1")
        self.assertEqual(self.sessions.create.call_count, 2)

    def test_review_hold_denies_access_even_when_status_is_active(self):
        self.checkout()
        self.review("DECLINED")
        self.webhook()
        BusinessSubscription.objects.filter(pk=self.subscription.pk).update(status="active")
        with override_settings(
            DEBUG=True, MOTIONMATE_ENVIRONMENT="local", LOGISTICS_LOCAL_BILLING_BYPASS=True
        ):
            self.assert_held()


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency requires PostgreSQL")
@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, **stripe_settings())
class LogisticsCheckoutApprovalConcurrencyTests(LogisticsCheckoutFixture, TransactionTestCase):
    def setUp(self):
        # TransactionTestCase flushes data-migration catalog rows between tests.
        ClarivoPlan.objects.get_or_create(
            slug="logistics", defaults={"name": "Logistics", "family": ClarivoPlan.Family.LOGISTICS}
        )
        super().setUp()

    def worker(self, function):
        close_old_connections()
        try:
            return function()
        finally:
            connection.close()

    def revoke(self):
        return review_application(
            self.application.pk,
            result="DECLINED",
            actor=self.actor,
            reason="Concurrent revocation",
            expected_revision=1,
        )

    def test_checkout_creation_serializes_with_revocation_and_expires_session(self):
        provider_entered, provider_release, review_started, review_finished = (
            Event(),
            Event(),
            Event(),
            Event(),
        )

        def create(**kwargs):
            provider_entered.set()
            if not provider_release.wait(5):
                raise RuntimeError("Timed out waiting for test release")
            return {"id": "cs_logistics_1", "url": "https://checkout.stripe.test/logistics"}

        def review():
            review_started.set()
            result = self.revoke()
            review_finished.set()
            return result

        self.sessions.create.side_effect = create
        with ThreadPoolExecutor(max_workers=2) as pool:
            checkout = pool.submit(self.worker, self.checkout)
            try:
                self.assertTrue(provider_entered.wait(5))
                revocation = pool.submit(self.worker, review)
                self.assertTrue(review_started.wait(5))
                self.assertFalse(review_finished.wait(0.1))
            finally:
                provider_release.set()
            self.assertEqual(checkout.result(timeout=10), "https://checkout.stripe.test/logistics")
            revocation.result(timeout=10)
        self.subscription.refresh_from_db()
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "DECLINED")
        self.assertTrue(self.subscription.logistics_approval_review_required)
        self.assertFalse(self.subscription.has_access)
        self.sessions.expire.assert_called_once_with("cs_logistics_1")

    def test_webhook_activation_serializes_with_revocation_and_finishes_suspended(self):
        from apps.businesses import stripe_webhooks

        self.checkout()
        remote = self.remote_subscription()
        webhook_entered, webhook_release, review_started, review_finished = (
            Event(),
            Event(),
            Event(),
            Event(),
        )
        original = stripe_webhooks._update_provider_identity_fields

        def update_identity(**kwargs):
            webhook_entered.set()
            if not webhook_release.wait(5):
                raise RuntimeError("Timed out waiting for test release")
            return original(**kwargs)

        def webhook():
            return stripe_webhooks._sync_subscription_object(
                provider_subscription=remote,
                provider_event_at=self.now,
                source="customer.subscription.created",
                source_provider_event_id="evt_race",
            )

        def review():
            review_started.set()
            result = self.revoke()
            review_finished.set()
            return result

        with (
            mock.patch.object(
                stripe_webhooks, "_update_provider_identity_fields", side_effect=update_identity
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            payment = pool.submit(self.worker, webhook)
            try:
                self.assertTrue(webhook_entered.wait(5))
                revocation = pool.submit(self.worker, review)
                self.assertTrue(review_started.wait(5))
                self.assertFalse(review_finished.wait(0.1))
            finally:
                webhook_release.set()
            payment.result(timeout=10)
            revocation.result(timeout=10)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "suspended")
        self.assertEqual(self.subscription.provider_subscription_id, "sub_logistics")
        self.assertTrue(self.subscription.logistics_approval_review_required)
        self.assertFalse(self.subscription.has_access)
