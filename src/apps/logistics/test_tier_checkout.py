"""E4 TEST-only Checkout and signed event integrity; no real provider requests."""

import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier
from unittest import mock, skipUnless

from django.db import close_old_connections, connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.businesses.models import (
    BillingProviderWebhookEvent,
    BusinessSubscription,
    ClarivoPlan,
    SubscriptionNotification,
)
from apps.businesses.stripe_checkout import (
    StripeCheckoutError,
    ensure_pending_checkout_subscription,
)
from apps.businesses.stripe_config import StripeConfigurationError
from apps.businesses.test_logistics_billing import stripe_settings

from .checkout_approval import approval_metadata
from .enrollment import enroll_application, issue_enrollment_link
from .models import LogisticsApplication
from .services import review_application
from .test_checkout import LogisticsCheckoutFixture
from .test_enrollment import PASSWORD
from .test_stripe_prices import provider_price, tier_map
from .tests import PILOT_POLICY, application_data


class TierCheckoutFixture(LogisticsCheckoutFixture):
    def create_application(self):
        seed = import_module("apps.businesses.migrations.0029_logistics_capacity_plans")
        for slug, name, amount, capacity in seed.TIERS:
            ClarivoPlan.objects.get_or_create(
                slug=slug, defaults=seed.tier_defaults(name, amount, capacity)
            )
        ClarivoPlan.objects.filter(slug__in=tier_map_slug()).update(is_active=True)
        return LogisticsApplication.objects.create(
            **application_data(selected_plan_slug="logistics-core")
        )

    def setUp(self):
        super().setUp()
        self.plan.regional_prices = {"eur": {"currency": "EUR", "yearly": "1700.00"}}
        self.plan.save(update_fields=["regional_prices"])
        self.sdk.Price.retrieve.side_effect = lambda price_id: provider_price(
            price_id.removeprefix("price_")
        )

    def metadata(self, subscription=None):
        result = super().metadata(subscription)
        result["logistics_price_id"] = tier_map()[(self.subscription.plan.slug, "yearly", "eur")]
        return result

    def remote_session(self, **changes):
        value = super().remote_session()
        value.update(livemode=False, currency="eur", payment_status="paid")
        value.update(
            subscription=f"sub_tier_{self.business.pk}", customer=f"cus_tier_{self.business.pk}"
        )
        value["line_items"] = {
            "data": [{"quantity": 1, "price": provider_price(self.subscription.plan.slug)}]
        }
        value.update(changes)
        return value

    def remote_subscription(self, **changes):
        value = super().remote_subscription()
        value.update(livemode=False, currency="eur")
        value.update(id=f"sub_tier_{self.business.pk}", customer=f"cus_tier_{self.business.pk}")
        value["items"] = {
            "data": [{"quantity": 1, "price": provider_price(self.subscription.plan.slug)}]
        }
        value.update(changes)
        return value

    def signed_event(
        self,
        *,
        obj=None,
        source="checkout.session.completed",
        event_id="evt_tier",
        offset=0,
        livemode=False,
        client=None,
    ):
        obj = obj if obj is not None else self.remote_session(status="complete")
        body = json.dumps(
            {
                "id": event_id,
                "object": "event",
                "type": source,
                "created": int(self.now.timestamp()) + offset,
                "livemode": livemode,
                "data": {"object": obj},
            },
            sort_keys=True,
        )
        timestamp = int(timezone.now().timestamp())
        signature = hmac.new(
            b"whsec_logistics", f"{timestamp}.{body}".encode(), hashlib.sha256
        ).hexdigest()
        return (client or self.client).post(
            reverse("stripe_billing_webhook"),
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=f"t={timestamp},v1={signature}",
        )


def tier_map_slug():
    return [key[0] for key in tier_map()]


TIER_SETTINGS = {
    **stripe_settings(),
    "STRIPE_LOGISTICS_TIER_PRICE_ID_MAP": tier_map(),
    "LOGISTICS_ELIGIBILITY_POLICY": PILOT_POLICY,
    "LOGISTICS_AUTO_APPROVE_ALL": True,
    "MOTIONMATE_ENVIRONMENT": "local",
}


@override_settings(**TIER_SETTINGS)
class TierCheckoutTests(TierCheckoutFixture, TestCase):
    def test_all_three_tiers_checkout_activate_and_replay_without_duplicates(self):
        for index, slug in enumerate(tier_map_slug()):
            if index:
                self.application = LogisticsApplication.objects.create(
                    **application_data(selected_plan_slug=slug, email=f"{slug}@example.com")
                )
                token = issue_enrollment_link(
                    self.application.pk, actor=self.actor, expected_revision=1
                )
                result = enroll_application(token, password=PASSWORD)
                self.user, self.business, self.subscription = (
                    result.user,
                    result.business,
                    result.subscription,
                )
                self.application.refresh_from_db()
                self.initial_approval_metadata = approval_metadata(self.application)
            self.checkout()
            params = self.sessions.create.call_args.kwargs
            self.assertEqual(params["line_items"], [{"price": f"price_{slug}", "quantity": 1}])
            self.assertEqual(params["metadata"]["logistics_plan_slug"], slug)
            self.assertEqual(params["metadata"]["logistics_price_id"], f"price_{slug}")
            self.assertEqual(params["subscription_data"], {"metadata": params["metadata"]})
            self.assertNotIn("trial_period_days", params["subscription_data"])
            self.subscription.refresh_from_db()
            self.assertEqual(self.subscription.status, "pending_checkout")
            for _ in range(2):
                self.assertEqual(self.signed_event(event_id=f"evt_{slug}").status_code, 200)
            self.subscription.refresh_from_db()
            self.assertEqual(self.subscription.status, "active")
            self.assertTrue(self.subscription.has_access)
        self.assertEqual(BusinessSubscription.objects.count(), 3)
        self.assertEqual(BillingProviderWebhookEvent.objects.count(), 3)
        self.assertEqual(SubscriptionNotification.objects.count(), 3)

    def test_open_session_retry_reuses_provider_session(self):
        self.checkout()
        self.checkout()
        self.assertEqual(self.sessions.create.call_count, 1)

    def test_reapproval_changes_retry_key_and_expires_old_authorization(self):
        self.checkout()
        key = self.sessions.create.call_args.kwargs["idempotency_key"]
        review_application(
            self.application.pk,
            result="APPROVED",
            actor=self.actor,
            reason="Approval renewed",
            expected_revision=1,
        )
        self.checkout()
        self.assertNotEqual(key, self.sessions.create.call_args.kwargs["idempotency_key"])
        self.sessions.expire.assert_called_once()

    def test_failed_event_retries_after_configuration_recovery(self):
        self.checkout()
        remote = self.remote_subscription()
        with override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP={}):
            response = self.signed_event(obj=remote, source="customer.subscription.created")
        self.assertEqual(response.status_code, 500)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "pending_checkout")
        self.assertEqual(
            self.signed_event(obj=remote, source="customer.subscription.created").status_code, 200
        )
        event = BillingProviderWebhookEvent.objects.get()
        self.assertEqual(event.status, "processed", event.last_error)
        self.assertEqual(event.attempt_count, 2)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "active")

    def test_initial_failed_payment_stays_pending_without_operational_access(self):
        self.checkout()
        remote = self.remote_subscription(status="incomplete")
        self.signed_event(obj=remote, source="customer.subscription.created")
        self.assertEqual(BillingProviderWebhookEvent.objects.get().status, "processed")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "pending_checkout")
        self.assertFalse(self.subscription.has_access)
        self.assertIsNone(self.subscription.grace_period_ends_at)

    def test_remote_success_local_failure_retries_same_bound_key(self):
        with mock.patch.object(
            BusinessSubscription, "save", side_effect=RuntimeError("commit failed")
        ):
            with self.assertRaises(RuntimeError):
                self.checkout()
        first_key = self.sessions.create.call_args.kwargs["idempotency_key"]
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.provider_checkout_session_id, "")
        self.checkout()
        self.assertEqual(first_key, self.sessions.create.call_args.kwargs["idempotency_key"])

    def test_changed_price_or_approval_changes_retry_key(self):
        self.checkout()
        key = self.sessions.create.call_args.kwargs["idempotency_key"]
        self.sdk.Price.retrieve.side_effect = lambda price_id: {**provider_price(), "id": price_id}
        prices = tier_map()
        prices[("logistics-core", "yearly", "eur")] = "price_replacement"
        with override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=prices):
            self.checkout()
            self.assertNotEqual(key, self.sessions.create.call_args.kwargs["idempotency_key"])
        self.sessions.expire.assert_called_once()

    def test_missing_invalid_inactive_configuration_and_live_mode_fail_before_payment(self):
        for overrides in (
            {"STRIPE_LOGISTICS_TIER_PRICE_ID_MAP": {}},
            {"STRIPE_ENABLED": False},
            {"STRIPE_SECRET_KEY": ""},
            {
                "MOTIONMATE_ENVIRONMENT": "production",
                "STRIPE_PUBLISHABLE_KEY": "pk_live_e4",
                "STRIPE_SECRET_KEY": "sk_live_e4",
            },
        ):
            with (
                override_settings(**overrides),
                self.assertRaises((StripeConfigurationError, StripeCheckoutError)),
            ):
                self.checkout()
        self.sdk.Price.retrieve.side_effect = lambda price_id: provider_price(active=False)
        with self.assertRaises(StripeConfigurationError):
            self.checkout()
        self.sessions.create.assert_not_called()

    def test_usd_and_tier_switching_are_rejected(self):
        with self.assertRaises(StripeCheckoutError):
            ensure_pending_checkout_subscription(
                business=self.business,
                plan=ClarivoPlan.objects.get(slug="logistics-growth"),
                billing_interval="yearly",
                currency="eur",
            )
        LogisticsApplication.objects.filter(pk=self.application.pk).update(preferred_currency="USD")
        BusinessSubscription.objects.filter(pk=self.subscription.pk).update(billing_currency="usd")
        with self.assertRaises(StripeConfigurationError):
            self.checkout()
        self.sessions.create.assert_not_called()

    def test_missing_or_malformed_display_prices_and_capacity_fail_closed(self):
        for prices in (
            {},
            {"eur": {"currency": "EUR", "yearly": "invalid"}},
            {"eur": {"currency": "EUR", "yearly": "1701"}},
        ):
            ClarivoPlan.objects.filter(pk=self.plan.pk).update(regional_prices=prices)
            with self.assertRaises(StripeConfigurationError):
                self.checkout()
        ClarivoPlan.objects.filter(pk=self.plan.pk).update(max_clients=None)
        with self.assertRaises(StripeConfigurationError):
            self.checkout()
        self.sessions.create.assert_not_called()

    def assert_rejected_unchanged(
        self, *, obj=None, source="checkout.session.completed", event_id="evt_bad", **kwargs
    ):
        before = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        self.signed_event(obj=obj, source=source, event_id=event_id, **kwargs)
        self.assertEqual(BusinessSubscription.objects.values().get(pk=self.subscription.pk), before)
        self.assertEqual(
            BillingProviderWebhookEvent.objects.get(event_id=event_id).status, "failed"
        )

    def test_forged_signature_and_mismatched_metadata_are_rejected(self):
        self.checkout()
        self.assertEqual(
            self.client.post(
                reverse("stripe_billing_webhook"),
                data="{}",
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="t=1,v1=bad",
            ).status_code,
            400,
        )
        for index, key in enumerate(self.metadata()):
            metadata = {**self.metadata(), key: "wrong"}
            remote = self.remote_subscription(metadata=metadata)
            self.assert_rejected_unchanged(
                obj=remote, source="customer.subscription.updated", event_id=f"evt_meta_{index}"
            )

    def test_price_amount_quantity_mode_currency_interval_and_period_mismatches_reject(self):
        self.checkout()
        cases = []
        for changes in (
            {"id": "price_logistics-growth"},
            {"unit_amount": 1},
            {"currency": "usd"},
            {"active": False},
            {"recurring": {"interval": "month", "interval_count": 1, "usage_type": "licensed"}},
        ):
            remote = self.remote_subscription()
            remote["items"]["data"][0]["price"].update(changes)
            cases.append(remote)
        remote = self.remote_subscription()
        remote["items"]["data"][0]["quantity"] = 2
        cases.extend(
            [
                remote,
                self.remote_subscription(livemode=True),
                self.remote_subscription(currency="usd"),
                self.remote_subscription(current_period_end=None),
            ]
        )
        for index, remote in enumerate(cases):
            self.assert_rejected_unchanged(
                obj=remote,
                source="customer.subscription.updated",
                event_id=f"evt_dimensions_{index}",
            )
        self.assert_rejected_unchanged(livemode=True, event_id="evt_live_envelope")

    def test_session_identity_payment_and_customer_mismatches_reject(self):
        self.checkout()
        for index, changes in enumerate(
            (
                {"id": "cs_stale"},
                {"customer": "cus_foreign"},
                {"subscription": "sub_foreign"},
                {"payment_status": "unpaid"},
                {"client_reference_id": ""},
                {"livemode": True},
            )
        ):
            self.assert_rejected_unchanged(
                obj=self.remote_session(status="complete", **changes),
                event_id=f"evt_session_{index}",
            )

    def test_events_before_checkout_and_revoked_approval_cannot_activate(self):
        self.assert_rejected_unchanged(
            obj=self.remote_subscription(), source="customer.subscription.created"
        )
        self.checkout()
        review_application(
            self.application.pk,
            result="DECLINED",
            actor=self.actor,
            reason="Revoked",
            expected_revision=1,
        )
        self.assert_rejected_unchanged(event_id="evt_revoked")

    def test_stale_events_do_not_change_identity_status_or_grace(self):
        self.checkout()
        self.signed_event(offset=10)
        before = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        self.signed_event(
            obj=self.remote_subscription(status="past_due"),
            source="customer.subscription.updated",
            offset=9,
            event_id="evt_stale",
        )
        self.assertEqual(BusinessSubscription.objects.values().get(pk=self.subscription.pk), before)
        self.assertEqual(
            BillingProviderWebhookEvent.objects.get(event_id="evt_stale").status, "processed"
        )

    def test_payment_failure_grace_restricted_mode_and_recovery(self):
        self.checkout()
        self.signed_event()
        invoice = {
            "id": "in_tier",
            "subscription": f"sub_tier_{self.business.pk}",
            "customer": f"cus_tier_{self.business.pk}",
            "livemode": False,
            "currency": "eur",
        }
        self.sdk.Subscription.retrieve.side_effect = (
            lambda *args, **kwargs: self.remote_subscription(status="past_due")
        )
        self.signed_event(
            obj=invoice, source="invoice.payment_failed", offset=1, event_id="evt_failed_payment"
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "past_due")
        self.assertTrue(self.subscription.has_access)
        self.assertTrue(
            self.subscription.has_restricted_access_at(self.subscription.grace_period_ends_at)
        )
        self.sdk.Subscription.retrieve.side_effect = (
            lambda *args, **kwargs: self.remote_subscription()
        )
        self.signed_event(obj=invoice, source="invoice.paid", offset=2, event_id="evt_recovered")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "active")
        self.assertIsNone(self.subscription.grace_period_ends_at)


@skipUnless(connection.vendor == "postgresql", "Row-lock verification requires PostgreSQL")
@override_settings(**TIER_SETTINGS)
class TierCheckoutConcurrencyTests(TierCheckoutFixture, TransactionTestCase):
    def parallel(self, actions):
        barrier = Barrier(len(actions))

        def worker(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return action()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(worker, actions))

    def test_parallel_checkout_clicks_create_one_session(self):
        results = self.parallel([self.checkout, self.checkout])
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.sessions.create.call_count, 1)

    def test_parallel_signed_delivery_activates_once(self):
        self.checkout()
        self.parallel([lambda: self.signed_event(client=Client()).status_code for _ in range(2)])
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "active")
        self.assertEqual(BillingProviderWebhookEvent.objects.count(), 1)
        self.assertEqual(SubscriptionNotification.objects.count(), 1)

    def test_approval_revocation_racing_payment_always_denies_access(self):
        self.checkout()
        self.parallel(
            [
                lambda: self.signed_event(client=Client()).status_code,
                lambda: review_application(
                    self.application.pk,
                    result="DECLINED",
                    actor=self.actor,
                    reason="Revoked",
                    expected_revision=1,
                ),
            ]
        )
        self.subscription.refresh_from_db()
        self.assertFalse(self.subscription.has_access)
        self.assertNotEqual(self.subscription.status, "active")
