"""F2A: billing validation is operation-specific; all provider calls are mocked."""

from copy import copy
from dataclasses import replace
from unittest import mock, skipUnless

from django.db import connection
from django.forms.models import model_to_dict
from django.test import Client, TestCase, TransactionTestCase, override_settings

from apps.businesses.admin import CommercialPlanAdminForm
from apps.businesses.billing_policy import BILLING_OFFERINGS
from apps.businesses.models import (
    BillingProviderWebhookEvent,
    Business,
    BusinessSubscription,
    ClarivoPlan,
    SubscriptionNotification,
)
from apps.businesses.stripe_config import (
    StripeConfigurationError,
    get_stripe_price_id,
    resolve_stripe_price_id,
    validate_stripe_configuration,
)
from apps.businesses.test_logistics_billing import stripe_settings

from . import test_tier_checkout as tier_tests
from .billing import configured_annual_price, validate_offering_activation
from .checks import check_logistics_plan
from .stripe_prices import configured_tier_prices
from .test_checkout import LogisticsCheckoutFixture
from .test_stripe_prices import provider_price, tier_map
from .test_webhook_same_second import SameSecondFixture
from .tests import PILOT_POLICY


@override_settings(**stripe_settings(logistics=False), MOTIONMATE_ENVIRONMENT="development")
class TierActivationCompatibilityTests(TestCase):
    def test_each_admin_tier_uses_only_its_own_eur_price_and_does_not_activate_on_validation(self):
        for slug in (key[0] for key in tier_map()):
            plan = ClarivoPlan.objects.get(slug=slug)
            before = ClarivoPlan.objects.values().get(pk=plan.pk)
            data = {**model_to_dict(plan), "is_active": True}
            mapping = {(slug, "yearly", "eur"): f"price_{slug}"}
            with (
                self.subTest(slug=slug),
                override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=mapping),
                mock.patch("stripe.Price.retrieve", return_value=provider_price(slug)) as retrieve,
                mock.patch("stripe.checkout.Session.create") as checkout,
            ):
                self.assertEqual(validate_stripe_configuration(), [])
                form = CommercialPlanAdminForm(data, instance=plan)
                self.assertTrue(form.is_valid(), form.errors)
                retrieve.assert_called_once_with(f"price_{slug}")
                checkout.assert_not_called()
                self.assertEqual(ClarivoPlan.objects.values().get(pk=plan.pk), before)
                self.assertEqual(resolve_stripe_price_id(f"price_{slug}").plan_slug, slug)
                # The full E3 audit still requires all three mappings.
                with self.assertRaises(StripeConfigurationError):
                    configured_tier_prices()

    @override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=tier_map())
    def test_admin_rejects_wrong_family_incomplete_capacity_bad_display_and_provider_price(self):
        plan = ClarivoPlan.objects.get(slug="logistics-core")
        data = {**model_to_dict(plan), "is_active": True}
        for changes in (
            {"family": "SERVICE"},
            {"max_users": None},
            {"regional_prices": {"eur": {"currency": "EUR", "yearly": "1.00"}}},
        ):
            with self.subTest(changes=changes), mock.patch("stripe.Price.retrieve") as retrieve:
                form = CommercialPlanAdminForm({**data, **changes}, instance=copy(plan))
                self.assertFalse(form.is_valid())
                retrieve.assert_not_called()
        with mock.patch("stripe.Price.retrieve", return_value=provider_price(active=False)):
            self.assertFalse(CommercialPlanAdminForm(data, instance=copy(plan)).is_valid())

    @override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=tier_map())
    def test_activation_rejects_ineligible_offering_and_live_keys_without_provider_call(self):
        plan = ClarivoPlan.objects.get(slug="logistics-core")
        plan.is_active = True
        for offering in (
            replace(BILLING_OFFERINGS[plan.slug], test_checkout_enabled=False),
            replace(BILLING_OFFERINGS[plan.slug], checkout_enabled=True),
            replace(BILLING_OFFERINGS[plan.slug], family="SERVICE"),
            replace(BILLING_OFFERINGS[plan.slug], intervals=("monthly",)),
        ):
            with mock.patch.dict(BILLING_OFFERINGS, {plan.slug: offering}):
                with self.assertRaises(StripeConfigurationError):
                    validate_offering_activation(plan)
        with (
            mock.patch("stripe.Price.retrieve") as retrieve,
            override_settings(
                MOTIONMATE_ENVIRONMENT="production",
                STRIPE_PUBLISHABLE_KEY="pk_live_fixture",
                STRIPE_SECRET_KEY="sk_live_fixture",
            ),
            self.assertRaises(StripeConfigurationError),
        ):
            validate_offering_activation(plan)
        retrieve.assert_not_called()
        with self.assertRaises(StripeConfigurationError):
            configured_annual_price(plan, "usd")

    def test_tier_activation_ignores_unverified_legacy_usd_provider_price(self):
        mapping = {
            **stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"],
            ("logistics", "yearly", "usd"): "price_unverified_legacy_usd",
        }
        plan = ClarivoPlan.objects.get(slug="logistics-core")
        plan.is_active = True
        with (
            override_settings(
                STRIPE_PRICE_ID_MAP=mapping, STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=tier_map()
            ),
            mock.patch("stripe.Price.retrieve", return_value=provider_price()) as retrieve,
        ):
            validate_offering_activation(plan)
        retrieve.assert_called_once_with("price_logistics-core")

    def test_duplicate_price_rejected_in_both_directions_without_legacy_to_core_fallback(self):
        for other_key in (("logistics", "yearly", "eur"), ("pro", "yearly", "eur")):
            mapping = {
                **stripe_settings()["STRIPE_PRICE_ID_MAP"],
                other_key: "price_logistics-core",
            }
            with override_settings(
                STRIPE_PRICE_ID_MAP=mapping, STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=tier_map()
            ):
                for operation in (
                    lambda: resolve_stripe_price_id("price_logistics-core"),
                    lambda: get_stripe_price_id(
                        plan_slug="logistics-core", billing_interval="yearly", currency="eur"
                    ),
                    lambda other_key=other_key: get_stripe_price_id(
                        plan_slug=other_key[0], billing_interval="yearly", currency="eur"
                    ),
                ):
                    with self.assertRaises(StripeConfigurationError) as raised:
                        operation()
                    self.assertEqual(raised.exception.code, "logistics_tier_price_duplicate")


@override_settings(
    **stripe_settings(logistics=False),
    LOGISTICS_DEPLOYMENT_CHECKS_ENABLED=True,
    STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=tier_map(),
    MOTIONMATE_ENVIRONMENT="development",
)
class ConditionalLegacyChecksTests(TestCase):
    def checks(self):
        with mock.patch("stripe.Price.retrieve") as retrieve:
            issues = check_logistics_plan(None, databases=["default"])
        retrieve.assert_not_called()
        return {issue.id for issue in issues}

    def legacy_subscription(self, *, provider="stripe", currency="usd"):
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.regional_prices = {
            "eur": {"currency": "EUR", "yearly": "1700.00"},
            "usd": {"currency": "USD", "yearly": "1906.00"},
        }
        plan.save(update_fields=["is_active", "regional_prices"])
        business = Business.objects.create(
            name="Historical fixture", slug="historical", vertical="LOGISTICS"
        )
        return BusinessSubscription.objects.create(
            business=business,
            plan=plan,
            status="active",
            payment_provider=provider,
            billing_interval="yearly",
            billing_currency=currency,
        )

    def test_no_legacy_subscription_or_local_entitlement_requires_legacy_prices(self):
        self.assertEqual(self.checks(), set())
        subscription = self.legacy_subscription(provider="local")
        before = BusinessSubscription.objects.values().get(pk=subscription.pk)
        self.assertTrue(subscription.has_access)
        self.assertIsNone(subscription.plan.max_users)
        self.assertEqual(self.checks(), set())
        self.assertEqual(BusinessSubscription.objects.values().get(pk=subscription.pk), before)
        ClarivoPlan.objects.filter(slug="logistics").update(is_active=False)
        self.assertIn("logistics.E010", self.checks())

    def test_actual_legacy_stripe_currency_remains_required_including_late_events(self):
        subscription = self.legacy_subscription()
        before = BusinessSubscription.objects.values().get(pk=subscription.pk)
        self.assertIn("logistics.E011", self.checks())
        mapping = {
            **stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"],
            ("logistics", "yearly", "usd"): "price_legacy_usd",
        }
        with override_settings(STRIPE_PRICE_ID_MAP=mapping):
            self.assertEqual(self.checks(), set())
            ClarivoPlan.objects.filter(slug="logistics").update(regional_prices={})
            self.assertIn("logistics.E012", self.checks())
        self.assertEqual(BusinessSubscription.objects.values().get(pk=subscription.pk), before)
        BusinessSubscription.objects.filter(pk=subscription.pk).update(
            status="cancelled", payment_provider="", provider_subscription_id="sub_historical"
        )
        self.assertIn("logistics.E011", self.checks())

    def test_active_tier_checks_its_own_configuration_without_legacy_or_sibling_prices(self):
        ClarivoPlan.objects.filter(slug="logistics-core").update(is_active=True)
        mapping = {("logistics-core", "yearly", "eur"): "price_logistics-core"}
        with override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=mapping):
            self.assertEqual(self.checks(), set())
            ClarivoPlan.objects.filter(slug="logistics-core").update(max_clients=None)
            self.assertIn("logistics.E016", self.checks())
        with override_settings(STRIPE_LOGISTICS_TIER_PRICE_ID_MAP={}):
            self.assertIn("logistics.E016", self.checks())


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, **stripe_settings())
class LegacyMappingCompatibilityTests(LogisticsCheckoutFixture, TestCase):
    def test_missing_mapping_blocks_recovery_and_signed_event_then_retries_after_repair(self):
        self.checkout()
        before = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        with override_settings(
            STRIPE_PRICE_ID_MAP=stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"]
        ):
            with self.assertRaises(StripeConfigurationError):
                self.checkout()
            self.assertEqual(self.webhook().status_code, 500)
        self.assertEqual(BusinessSubscription.objects.values().get(pk=self.subscription.pk), before)
        self.assertEqual(BillingProviderWebhookEvent.objects.get().status, "failed")
        self.assertEqual(self.webhook().status_code, 200)
        self.assertEqual(self.webhook().status_code, 200)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan.slug, "logistics")
        self.assertEqual(self.subscription.status, "active")

    def test_ambiguous_or_core_only_mapping_cannot_reclassify_legacy_subscription(self):
        self.checkout()
        before = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        core = {("logistics-core", "yearly", "eur"): "price_logistics_yearly_eur"}
        for index, legacy in enumerate((True, False)):
            with override_settings(
                STRIPE_PRICE_ID_MAP=stripe_settings(logistics=legacy)["STRIPE_PRICE_ID_MAP"],
                STRIPE_LOGISTICS_TIER_PRICE_ID_MAP=core,
            ):
                remote = self.remote_subscription(
                    items={"data": [{"price": provider_price(id="price_logistics_yearly_eur")}]}
                )
                response = self.webhook(event_id=f"evt_ambiguous_{index}", remote=remote)
                self.assertEqual(response.status_code, 500 if legacy else 200)
                record = BillingProviderWebhookEvent.objects.get(event_id=f"evt_ambiguous_{index}")
                self.assertEqual(record.status, "failed")
                if not legacy:
                    self.assertIn("does not match the local plan", record.last_error)
                self.assertEqual(
                    BusinessSubscription.objects.values().get(pk=self.subscription.pk), before
                )


@skipUnless(connection.vendor == "postgresql", "Row-lock verification requires PostgreSQL")
@override_settings(
    **{
        **tier_tests.TIER_SETTINGS,
        "STRIPE_PRICE_ID_MAP": stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"],
    }
)
class IndependentTierConcurrencyTests(SameSecondFixture, TransactionTestCase):
    parallel = tier_tests.TierCheckoutConcurrencyTests.parallel

    def test_tier_same_second_events_and_duplicate_delivery_without_legacy_mapping(self):
        self.start()
        self.provider_now("past_due")
        responses = self.parallel(
            [
                lambda: self.deliver("past_due", "evt_failure", client=Client()).status_code,
                lambda: self.deliver("past_due", "evt_failure", client=Client()).status_code,
                lambda: self.deliver("active", "evt_old_snapshot", client=Client()).status_code,
            ]
        )
        self.assertEqual(responses, [200, 200, 200])
        self.assert_status("past_due")
        self.assertEqual(self.subscription.plan.slug, "logistics-core")
        self.assertEqual(BusinessSubscription.objects.count(), 1)
        self.assertEqual(BillingProviderWebhookEvent.objects.filter(status="processed").count(), 3)
        self.assertEqual(
            SubscriptionNotification.objects.filter(
                notification_type="payment_grace_started"
            ).count(),
            1,
        )
