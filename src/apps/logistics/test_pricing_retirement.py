"""Retired commercial admission and historical webhook identity, with mocked Stripe."""

from copy import deepcopy
from datetime import timedelta
from unittest import skipUnless

from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.businesses.billing_policy import billing_offering
from apps.businesses.models import (
    BillingProviderWebhookEvent,
    BusinessSubscription,
    ClarivoPlan,
    SubscriptionNotification,
)
from apps.businesses.stripe_checkout import (
    StripeCheckoutError,
    create_trial_checkout_session,
    ensure_pending_checkout_subscription,
    resume_trial_checkout_session,
)
from apps.businesses.test_logistics_billing import stripe_settings

from .test_checkout import LogisticsCheckoutFixture
from .test_stripe_prices import provider_price, tier_map
from .test_tier_checkout import TIER_SETTINGS, TierCheckoutFixture
from .tests import PILOT_POLICY

RETIREMENT_SETTINGS = {
    "LOGISTICS_ELIGIBILITY_POLICY": PILOT_POLICY,
    **stripe_settings(logistics=False),
    "STRIPE_LOGISTICS_TIER_PRICE_ID_MAP": tier_map(),
}


class HistoricalPricingRetirementFixture(LogisticsCheckoutFixture):
    legacy_billing_fixture = True

    def setUp(self):
        ClarivoPlan.objects.get_or_create(
            slug="logistics", defaults={"name": "Logistics", "family": "LOGISTICS"}
        )
        super().setUp()
        self.historical_checkout()
        self.subscription.provider_customer_id = "cus_logistics"
        self.subscription.provider_subscription_id = "sub_logistics"
        self.subscription.status = "active"
        self.subscription.current_period_start = self.now
        self.subscription.current_period_end = self.now + timedelta(days=365)
        self.subscription.save()

    def snapshot(self):
        return BusinessSubscription.objects.values().get(pk=self.subscription.pk)


@override_settings(**RETIREMENT_SETTINGS)
class HistoricalPricingRetirementTests(HistoricalPricingRetirementFixture, TestCase):
    def test_retired_pending_payment_links_hidden_without_changing_local_entitlements(self):
        BusinessSubscription.objects.filter(pk=self.subscription.pk).update(
            status="pending_checkout"
        )
        self.subscription.refresh_from_db()
        self.assertFalse(self.subscription.effective_access_state.can_resume_checkout)
        with override_settings(
            DEBUG=True, MOTIONMATE_ENVIRONMENT="local", LOGISTICS_LOCAL_BILLING_BYPASS=True
        ):
            self.assertTrue(self.subscription.has_access)
            self.assertFalse(self.subscription.effective_access_state.can_resume_checkout)
        self.login()
        response = self.client.get(reverse("logistics_enrollment_complete"))
        self.assertContains(response, "retired Logistics pricing")
        self.assertNotContains(response, "Continue to annual checkout")
        response = self.client.get(reverse("business_subscription"))
        self.assertNotContains(response, "Complete payment setup")

    def test_every_new_and_resume_checkout_entry_rejects_legacy_without_provider_calls(self):
        self.assertFalse(billing_offering("logistics").checkout_enabled)
        self.assertTrue(billing_offering("logistics").historical_only)
        request = self.factory.post("/", HTTP_HOST="localhost")
        operations = (
            self.checkout,
            lambda: ensure_pending_checkout_subscription(
                business=self.business, plan=self.plan, billing_interval="yearly", currency="eur"
            ),
            lambda: create_trial_checkout_session(
                request=request, subscription=self.subscription, user=self.user
            ),
            lambda: resume_trial_checkout_session(
                request=request, subscription=self.subscription, user=self.user
            ),
        )
        # Pending and already-paid historical records must both be preserved.
        for status in ("pending_checkout", "active"):
            BusinessSubscription.objects.filter(pk=self.subscription.pk).update(status=status)
            self.subscription.refresh_from_db()
            before = self.snapshot()
            for operation in operations:
                with self.subTest(status=status), self.assertRaises(StripeCheckoutError):
                    operation()
                self.assertEqual(self.snapshot(), before)
        self.configure.assert_not_called()
        self.sdk.Price.retrieve.assert_not_called()
        self.sessions.create.assert_not_called()
        self.sessions.expire.assert_not_called()

    def test_bound_historical_contract_syncs_cancels_and_replays_without_legacy_mapping(self):
        for offset, status in enumerate(("past_due", "active", "canceled"), 1):
            remote = self.remote_subscription(status=status)
            for _ in range(2):
                response = self.webhook(
                    event_type="customer.subscription.updated",
                    event_id=f"evt_retired_{status}",
                    remote=remote,
                    offset=offset,
                )
                self.assertEqual(response.status_code, 200)
            self.subscription.refresh_from_db()
            self.assertEqual(
                self.subscription.status, "cancelled" if status == "canceled" else status
            )
            self.assertEqual(self.subscription.plan_id, self.plan.pk)
            self.assertEqual(self.subscription.provider_price_id, "price_logistics_yearly_eur")
        self.assertEqual(BillingProviderWebhookEvent.objects.filter(status="processed").count(), 3)
        self.assertEqual(BusinessSubscription.objects.count(), 1)
        self.sessions.create.assert_not_called()

    def test_unknown_or_conflicting_identity_cannot_recover_or_reclassify_legacy(self):
        for index, changes in enumerate(
            (
                {"id": "sub_other"},
                {"customer": "cus_other"},
                {"items": {"data": [{"price": provider_price()}]}},
                {"metadata": {**self.metadata(), "plan_slug": "logistics-core"}},
            )
        ):
            before = self.snapshot()
            response = self.webhook(
                event_type="customer.subscription.updated",
                event_id=f"evt_conflict_{index}",
                remote=self.remote_subscription(**changes),
                offset=index + 1,
            )
            self.assertIn(response.status_code, (200, 500))
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(
                BillingProviderWebhookEvent.objects.get(event_id=f"evt_conflict_{index}").status,
                "failed",
            )

    def test_missing_saved_binding_is_retryable_and_never_inferred_from_price_metadata(self):
        for index, field in enumerate(
            ("provider_price_id", "provider_customer_id", "provider_subscription_id")
        ):
            original = getattr(self.subscription, field)
            BusinessSubscription.objects.filter(pk=self.subscription.pk).update(**{field: ""})
            self.subscription.refresh_from_db()
            before = self.snapshot()
            remote = self.remote_subscription()
            remote["items"]["data"][0]["price"]["metadata"] = {"motionmate_plan_slug": "logistics"}
            self.assertEqual(
                self.webhook(
                    event_type="customer.subscription.updated",
                    event_id=f"evt_unbound_{index}",
                    remote=remote,
                ).status_code,
                500,
            )
            self.assertEqual(self.snapshot(), before)
            BusinessSubscription.objects.filter(pk=self.subscription.pk).update(**{field: original})
            self.subscription.refresh_from_db()

    def test_ambiguous_or_tier_mapping_never_uses_historical_fallback(self):
        before = self.snapshot()
        for index, legacy in enumerate((True, False)):
            mapping = deepcopy(stripe_settings(logistics=legacy)["STRIPE_PRICE_ID_MAP"])
            with override_settings(
                STRIPE_PRICE_ID_MAP=mapping,
                STRIPE_LOGISTICS_TIER_PRICE_ID_MAP={
                    **tier_map(),
                    ("logistics-core", "yearly", "eur"): "price_logistics_yearly_eur",
                },
            ):
                response = self.webhook(
                    event_type="customer.subscription.updated",
                    event_id=f"evt_alias_{index}",
                    remote=self.remote_subscription(),
                )
            self.assertIn(response.status_code, (200, 500))
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(
                BillingProviderWebhookEvent.objects.get(event_id=f"evt_alias_{index}").status,
                "failed",
            )


@skipUnless(connection.vendor == "postgresql", "Row locks require PostgreSQL")
@override_settings(**RETIREMENT_SETTINGS)
class HistoricalPricingRetirementConcurrencyTests(
    HistoricalPricingRetirementFixture, TransactionTestCase
):
    def test_duplicate_signed_legacy_delivery_without_mapping_is_serialized(self):
        from .test_tier_checkout import TierCheckoutConcurrencyTests

        responses = TierCheckoutConcurrencyTests.parallel(
            self,
            [
                lambda: self.webhook(
                    event_type="customer.subscription.updated",
                    event_id="evt_legacy_race",
                    remote=self.remote_subscription(status="past_due"),
                    offset=1,
                    client=Client(),
                ).status_code
                for _ in range(2)
            ],
        )
        self.assertEqual(responses, [200, 200])
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "past_due")
        self.assertEqual(self.subscription.plan.slug, "logistics")
        self.assertEqual(BillingProviderWebhookEvent.objects.filter(status="processed").count(), 1)
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type="payment_grace_started"
            ).count(),
            1,
        )
        self.assertEqual(BusinessSubscription.objects.count(), 1)


# Current tier approval must remain authoritative even if an operator reuses a
# historical Price ID in the tier mapping. Price metadata cannot grant access.


@override_settings(**TIER_SETTINGS)
class RetiredEventTierIsolationTests(TierCheckoutFixture, TestCase):
    def test_old_legacy_event_cannot_activate_core_even_when_price_id_is_reused(self):

        prices = {**tier_map(), ("logistics-core", "yearly", "eur"): "price_old_legacy"}
        with override_settings(
            STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=prices,
            STRIPE_PRICE_ID_MAP=stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"],
        ):
            self.sdk.Price.retrieve.side_effect = lambda price_id: provider_price(id=price_id)
            self.checkout()
            before = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
            remote = self.remote_subscription()
            remote["items"]["data"][0]["price"] = provider_price(
                id="price_old_legacy", metadata={"motionmate_plan_slug": "logistics-core"}
            )
            remote["metadata"].update(plan_slug="logistics", logistics_plan_slug="logistics")
            self.assertEqual(
                self.signed_event(obj=remote, source="customer.subscription.created").status_code,
                200,
            )
            self.assertEqual(
                BusinessSubscription.objects.values().get(pk=self.subscription.pk), before
            )
            self.assertEqual(BillingProviderWebhookEvent.objects.get().status, "failed")

    def test_orphaned_legacy_event_is_ignored_without_attaching_it_to_core(self):
        self.checkout()
        before = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        remote = self.remote_subscription(id="sub_orphan", customer="cus_orphan")
        remote["metadata"].update(
            motionmate_business_id="99999999",
            motionmate_subscription_id="99999999",
            plan_slug="logistics",
        )
        self.assertEqual(
            self.signed_event(obj=remote, source="customer.subscription.updated").status_code, 200
        )
        self.assertEqual(BillingProviderWebhookEvent.objects.get().status, "ignored")
        self.assertEqual(BusinessSubscription.objects.values().get(pk=self.subscription.pk), before)
