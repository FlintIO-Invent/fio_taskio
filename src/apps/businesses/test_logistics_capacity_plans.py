"""Staged Logistics capacity definitions; no provider calls or quota writers."""

from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.crm.importing.client_preview import project_client_capacity

from .billing_policy import BILLABLE_PLAN_SLUGS, billing_offering, is_stripe_billable_plan
from .models import Business, BusinessSubscription, ClarivoPlan
from .plan_catalog import LOGISTICS_TIER_CAPACITY_FIELDS, LOGISTICS_TIER_SLUGS
from .stripe_checkout import StripeCheckoutError, ensure_pending_checkout_subscription
from .stripe_config import StripeConfigurationError, get_stripe_price_id
from .utils import (
    PLAN_USAGE_LIMIT_NAMES,
    business_limit_reached,
    can_use_module,
    get_business_plan_usage_summary,
    get_plan_limit,
    resolve_business_plan_limit,
)

MIGRATION = import_module("apps.businesses.migrations.0029_logistics_capacity_plans")
EXPECTED = {
    "logistics-core": (1700, (10, 2, 250, 300, 80, 100, 25, 3000, 300, 1)),
    "logistics-growth": (2300, (15, 4, 800, 900, 200, 300, 50, 9000, 900, 3)),
    "logistics-scale": (3000, (25, 8, 2000, 1800, 400, 600, 100, 18000, 1800, 6)),
}
METRICS = (
    "users",
    "locations",
    "clients",
    "parcels_per_month",
    "shipments_per_month",
    "invoices_per_month",
    "services",
    "parcel_events_per_month",
    "transactional_emails_per_month",
    "storage_gb",
)
FEATURES = (
    "tracking",
    "public_tracking",
    "qr_scanning",
    "barcode_scanning",
    "scanning",
    "parcels",
    "shipments",
    "manifests",
    "invoice_pdfs",
    "invoicing",
    "multi_location",
    "location_permissions",
    "parcel_history",
    "services",
    "clients",
    "team",
)


@override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False)
class LogisticsCapacityPlanTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Tier fixture", slug="tier-fixture", vertical="LOGISTICS"
        )

    def subscribe(self, slug="logistics-core", *, activate=True):
        plan = ClarivoPlan.objects.get(slug=slug)
        if activate:
            plan.is_active = True
            plan.save(update_fields=["is_active"])
        subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
            payment_provider=BusinessSubscription.PaymentProvider.LOCAL,
            billing_interval=BusinessSubscription.BillingInterval.YEARLY,
            billing_currency=BusinessSubscription.BillingCurrency.EUR,
        )
        self.business.refresh_from_db()
        return subscription

    def test_seeded_configuration_is_exact_inactive_and_eur_annual_only(self):
        self.assertEqual(tuple(EXPECTED), LOGISTICS_TIER_SLUGS)
        for slug, (yearly, capacities) in EXPECTED.items():
            with self.subTest(slug=slug):
                plan = ClarivoPlan.objects.get(slug=slug)
                self.assertEqual(plan.family, "LOGISTICS")
                self.assertFalse(plan.is_active)
                self.assertTrue(plan.has_complete_logistics_capacity)
                self.assertEqual(plan.price_yearly, Decimal(yearly))
                self.assertEqual(
                    plan.regional_prices, {"eur": {"currency": "EUR", "yearly": f"{yearly}.00"}}
                )
                self.assertEqual(
                    tuple(getattr(plan, field) for field in LOGISTICS_TIER_CAPACITY_FIELDS),
                    capacities,
                )
                offering = billing_offering(slug)
                self.assertEqual(
                    (
                        offering.family,
                        offering.intervals,
                        offering.trial_days,
                        offering.checkout_enabled,
                    ),
                    ("LOGISTICS", ("yearly",), 0, False),
                )
                for feature in FEATURES:
                    self.assertTrue(plan.allows_module(feature), feature)

    def test_new_tier_price_display_never_falls_back_to_usd_or_monthly(self):
        for slug, (yearly, _) in EXPECTED.items():
            with self.subTest(slug=slug):
                plan = ClarivoPlan.objects.get(slug=slug)
                eur = plan.get_display_pricing(region="eur")
                usd = plan.get_display_pricing(region="usd")
                self.assertEqual(
                    (eur["currency"], eur["yearly"], eur["monthly"]), ("EUR", Decimal(yearly), None)
                )
                self.assertEqual(eur["monthly_display"], "Annual billing only")
                self.assertEqual(
                    (usd["currency"], usd["monthly"], usd["yearly"]), ("USD", None, None)
                )
                self.assertEqual(usd["yearly_display"], "Not configured")

    def test_all_tier_limits_resolve_through_existing_registry(self):
        for slug, (_, capacities) in EXPECTED.items():
            with self.subTest(slug=slug):
                subscription = self.subscribe(slug)
                self.assertTrue(subscription.has_access)
                for metric, capacity in zip(METRICS, capacities, strict=True):
                    result = resolve_business_plan_limit(self.business, metric)
                    self.assertTrue(result.available, metric)
                    self.assertEqual(result.limit, capacity, metric)
                    self.assertFalse(result.unlimited, metric)
                    self.assertEqual(get_plan_limit(subscription.plan, metric), capacity)
                    if metric.endswith("_per_month"):
                        self.assertEqual(result.period, "calendar_month_utc")
                for feature in FEATURES:
                    self.assertTrue(can_use_module(self.business, feature), feature)
                for feature in ("appointments", "public_booking", "service_requests"):
                    self.assertFalse(can_use_module(self.business, feature), feature)
                self.assertEqual(
                    project_client_capacity(
                        business=self.business, new_importable_clients=1
                    ).plan_limit,
                    capacities[2],
                )
                subscription.delete()
                self.business.refresh_from_db()

    def test_inactive_seed_does_not_grant_access(self):
        subscription = self.subscribe(activate=False)
        self.assertFalse(subscription.has_access)
        self.assertFalse(resolve_business_plan_limit(self.business, "clients").available)

    def test_new_tier_missing_configuration_fails_closed_not_unlimited(self):
        subscription = self.subscribe()
        for field in LOGISTICS_TIER_CAPACITY_FIELDS:
            with self.subTest(field=field):
                previous = getattr(subscription.plan, field)
                ClarivoPlan.objects.filter(pk=subscription.plan_id).update(**{field: None})
                self.business.refresh_from_db()
                result = resolve_business_plan_limit(self.business, "clients")
                self.assertFalse(result.available)
                self.assertFalse(result.unlimited)
                self.assertFalse(
                    project_client_capacity(
                        business=self.business, new_importable_clients=1
                    ).available
                )
                ClarivoPlan.objects.filter(pk=subscription.plan_id).update(**{field: previous})

    def test_monthly_and_trial_logistics_subscriptions_are_rejected(self):
        for slug in LOGISTICS_TIER_SLUGS:
            plan = ClarivoPlan.objects.get(slug=slug)
            for values in (
                {"billing_interval": "monthly", "status": "active"},
                {"billing_interval": "yearly", "status": "trialing"},
            ):
                with self.subTest(slug=slug, values=values), self.assertRaises(ValidationError):
                    BusinessSubscription.objects.create(business=self.business, plan=plan, **values)

    def test_monitoring_and_storage_are_not_hard_limits(self):
        self.subscribe()
        for metric in ("parcel_events_per_month", "transactional_emails_per_month", "storage_gb"):
            with self.subTest(metric=metric):
                result = resolve_business_plan_limit(self.business, metric)
                self.assertEqual(
                    result.kind,
                    "storage_planning" if metric == "storage_gb" else "monitoring_budget",
                )
                with patch("apps.businesses.utils.get_business_usage_count", return_value=10**9):
                    self.assertFalse(business_limit_reached(self.business, metric))
        summary = get_business_plan_usage_summary(self.business, self.business.subscription.plan)
        self.assertEqual(tuple(row["name"] for row in summary), PLAN_USAGE_LIMIT_NAMES)

    def test_legacy_null_capacity_remains_unlimited_but_unset_budgets_do_not(self):
        self.subscribe("logistics")
        for metric in (
            "users",
            "clients",
            "invoices_per_month",
            "locations",
            "services",
            "parcels_per_month",
            "shipments_per_month",
        ):
            with self.subTest(metric=metric):
                result = resolve_business_plan_limit(self.business, metric)
                self.assertTrue(result.available)
                self.assertIsNone(result.limit)
                self.assertTrue(result.unlimited)
        for metric in ("parcel_events_per_month", "transactional_emails_per_month", "storage_gb"):
            result = resolve_business_plan_limit(self.business, metric)
            self.assertFalse(result.available)
            self.assertFalse(result.unlimited)
        self.assertTrue(
            project_client_capacity(business=self.business, new_importable_clients=1000).allowed
        )

    def test_missing_expired_and_wrong_vertical_entitlements_are_unavailable(self):
        self.assertFalse(resolve_business_plan_limit(self.business, "clients").available)
        self.assertFalse(resolve_business_plan_limit(self.business, "unknown").available)
        subscription = self.subscribe()
        subscription.status = BusinessSubscription.Status.EXPIRED
        subscription.save(update_fields=["status"])
        self.business.refresh_from_db()
        self.assertFalse(resolve_business_plan_limit(self.business, "clients").available)
        subscription.delete()
        self.business.vertical = "SERVICE"
        self.business.save(update_fields=["vertical"])
        subscription = BusinessSubscription.objects.create(
            business=self.business, plan=ClarivoPlan.objects.get(slug="pro"), status="active"
        )
        self.business.refresh_from_db()
        self.assertTrue(resolve_business_plan_limit(self.business, "clients").available)
        self.assertFalse(resolve_business_plan_limit(self.business, "parcels_per_month").available)
        self.assertTrue(subscription.can_use_module("appointments"))

    def test_tier_checkout_requires_approved_enrollment_and_test_configuration(self):
        subscription = self.subscribe()
        self.assertTrue(subscription.is_stripe_billable)
        self.assertTrue(is_stripe_billable_plan(subscription.plan))
        self.assertEqual(BILLABLE_PLAN_SLUGS, ("starter", "pro", "business", "logistics"))
        self.assertEqual({key[0] for key in settings.STRIPE_PRICE_ID_MAP}, set(BILLABLE_PLAN_SLUGS))
        with (
            override_settings(STRIPE_ENABLED=True),
            patch("apps.businesses.stripe_checkout.configure_stripe_sdk") as provider,
        ):
            with self.assertRaises((StripeCheckoutError, StripeConfigurationError)):
                ensure_pending_checkout_subscription(
                    business=self.business,
                    plan=subscription.plan,
                    billing_interval="yearly",
                    currency="eur",
                )
            provider.assert_not_called()
        # A stray configuration value cannot activate an unapproved tier.
        with override_settings(
            STRIPE_PRICE_ID_MAP={("logistics-core", "yearly", "eur"): "price_fixture_only"}
        ):
            with self.assertRaises(StripeConfigurationError):
                get_stripe_price_id(
                    plan_slug="logistics-core", billing_interval="yearly", currency="eur"
                )

    def test_reseeding_does_not_write_or_change_any_existing_plans(self):
        before = list(ClarivoPlan.objects.order_by("pk").values())
        with CaptureQueriesContext(connection) as captured:
            MIGRATION.seed_tiers(apps, SimpleNamespace(connection=connection))
        self.assertFalse(
            any(
                q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for q in captured
            )
        )
        self.assertEqual(list(ClarivoPlan.objects.order_by("pk").values()), before)

    def test_collision_is_not_overwritten_and_reverse_refuses_used_plans(self):
        plan = ClarivoPlan.objects.get(slug="logistics-core")
        plan.price_yearly = Decimal("9999.00")
        plan.save(update_fields=["price_yearly"])
        with self.assertRaisesMessage(RuntimeError, "different configuration"):
            MIGRATION.seed_tiers(apps, SimpleNamespace(connection=connection))
        plan.refresh_from_db()
        self.assertEqual(plan.price_yearly, Decimal("9999.00"))
        with self.assertRaises(RuntimeError):
            MIGRATION.remove_unused_tiers(apps, SimpleNamespace(connection=connection))
        self.assertEqual(ClarivoPlan.objects.filter(slug__in=LOGISTICS_TIER_SLUGS).count(), 3)

    def test_reverse_refuses_a_subscription_even_on_an_unchanged_inactive_tier(self):
        self.subscribe(activate=False)
        with self.assertRaisesMessage(RuntimeError, "subscribed"):
            MIGRATION.remove_unused_tiers(apps, SimpleNamespace(connection=connection))
        self.assertEqual(ClarivoPlan.objects.filter(slug__in=LOGISTICS_TIER_SLUGS).count(), 3)

    @override_settings(
        DEBUG=True, MOTIONMATE_ENVIRONMENT="local", LOGISTICS_LOCAL_BILLING_BYPASS=True
    )
    def test_staged_tier_local_access_keeps_limits_and_nonlocal_isolation(self):
        subscription = self.subscribe(activate=False)
        subscription.status = BusinessSubscription.Status.PENDING_CHECKOUT
        subscription.payment_provider = BusinessSubscription.PaymentProvider.STRIPE
        subscription.save(update_fields=["status", "payment_provider"])
        self.business.refresh_from_db()
        self.assertEqual(resolve_business_plan_limit(self.business, "clients").limit, 250)
        self.assertTrue(
            project_client_capacity(business=self.business, new_importable_clients=1).allowed
        )
        self.assertFalse(
            project_client_capacity(business=self.business, new_importable_clients=251).allowed
        )
        for environment in ("development", "staging", "production"):
            with (
                self.subTest(environment=environment),
                override_settings(MOTIONMATE_ENVIRONMENT=environment),
            ):
                self.assertFalse(resolve_business_plan_limit(self.business, "clients").available)
        ClarivoPlan.objects.filter(pk=subscription.plan_id).update(max_clients=None)
        self.business.refresh_from_db()
        self.assertFalse(resolve_business_plan_limit(self.business, "clients").available)


class LogisticsCapacityMigrationTests(TransactionTestCase):
    def test_existing_plans_subscriptions_and_lab_foundations_are_unchanged(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [("businesses", "0028_logistics_capacity_fields")]
        after = [("businesses", "0029_logistics_capacity_plans")]
        try:
            executor.migrate(before)
            historical = executor.loader.project_state(before).apps
            HistoricalSubscription = historical.get_model("businesses", "BusinessSubscription")
            HistoricalMembership = historical.get_model("businesses", "BusinessUser")
            HistoricalLocation = executor.loader.project_state(latest).apps.get_model(
                "logistics", "LogisticsLocation"
            )
            legacy, _ = ClarivoPlan.objects.get_or_create(
                slug="logistics", defaults={"name": "Legacy Logistics", "family": "LOGISTICS"}
            )
            legacy.is_active = True
            legacy.price_yearly = Decimal("9876.54")
            legacy.regional_prices = {"usd": {"currency": "USD", "yearly": "4321.00"}}
            legacy.save()
            # Environment-specific IDs are fixtures only, never application policy.
            for identifier in (11, 166):
                business = Business.objects.create(
                    pk=identifier,
                    name="Existing lab",
                    slug=f"existing-lab-{identifier}",
                    vertical="LOGISTICS",
                )
                HistoricalSubscription.objects.create(
                    business_id=business.pk,
                    plan_id=legacy.pk,
                    status="active",
                    payment_provider="stripe",
                    billing_interval="yearly",
                    billing_currency="usd",
                    provider_price_id=f"price_fixture_{identifier}",
                    provider_customer_id=f"cus_fixture_{identifier}",
                    provider_subscription_id=f"sub_fixture_{identifier}",
                    current_period_end=timezone.now() + timedelta(days=100),
                )
                for index in range(9):
                    user = TaskIOUser.objects.create_user(
                        email=f"lab-{identifier}-{index}@example.test",
                        password="unchanged-fixture-password",
                    )
                    HistoricalMembership.objects.create(
                        business_id=business.pk,
                        user_id=user.pk,
                        role="owner" if index == 0 else "staff",
                    )
                for index in range(4):
                    HistoricalLocation.objects.create(
                        business_id=business.pk,
                        code=f"SITE-{index}",
                        name=f"Existing site {index}",
                        location_type="WAREHOUSE",
                        country_code="SX",
                        city="Philipsburg",
                    )
            models = (
                ClarivoPlan,
                Business,
                HistoricalSubscription,
                HistoricalMembership,
                TaskIOUser,
                HistoricalLocation,
            )
            snapshots = {model: list(model.objects.order_by("pk").values()) for model in models}
            MigrationExecutor(connection).migrate(after)
            for model in models:
                actual = model.objects.order_by("pk")
                if model is ClarivoPlan:
                    actual = actual.exclude(slug__in=LOGISTICS_TIER_SLUGS)
                self.assertEqual(list(actual.values()), snapshots[model], model.__name__)
            self.assertEqual(ClarivoPlan.objects.filter(slug__in=LOGISTICS_TIER_SLUGS).count(), 3)
        finally:
            # Reverse tests intentionally refuse subscribed/modified new tiers;
            # this fixture only subscribes to legacy, so latest can be restored.
            MigrationExecutor(connection).migrate(latest)
