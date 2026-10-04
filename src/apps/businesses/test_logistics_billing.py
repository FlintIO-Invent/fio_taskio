from datetime import timedelta
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest import mock

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import (
    RequestFactory,
    SimpleTestCase,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forms import BusinessRegistrationForm
from apps.accounts.models import TaskIOUser

from .billing_policy import billing_offering, is_stripe_billable_plan
from .models import (
    Business,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    SubscriptionNotification,
)
from .plan_catalog import (
    PUBLIC_BILLING_INTERVALS,
    PUBLIC_PAID_PLAN_SLUGS,
    PUBLIC_PRICING_CURRENCIES,
)
from .stripe_checkout import (
    StripeCheckoutError,
    create_trial_checkout_session,
    ensure_pending_checkout_subscription,
    resume_trial_checkout_session,
)
from .stripe_config import (
    STRIPE_CHECK_MISSING_PRICE_ID,
    STRIPE_CHECK_UNSUPPORTED_INTERVAL,
    StripeConfigurationError,
    get_stripe_price_id,
    resolve_stripe_price_id,
    validate_stripe_configuration,
)
from .stripe_portal import (
    get_customer_portal_availability,
    get_payment_recovery_portal_availability,
)
from .stripe_webhooks import StripeWebhookProcessingError, _sync_subscription_object
from .subscription_notifications import (
    build_subscription_notification_email_context,
    enqueue_subscription_notification,
)
from .subscription_reminders import enqueue_due_subscription_reminders
from .utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    assign_business_subscription_plan,
    create_default_trial_subscription,
)


def stripe_settings(*, logistics=True):
    price_map = {
        (slug, interval, currency): f"price_{slug}_{interval}_{currency}"
        for slug in PUBLIC_PAID_PLAN_SLUGS
        for interval in PUBLIC_BILLING_INTERVALS
        for currency in PUBLIC_PRICING_CURRENCIES
    }
    if logistics:
        price_map.update(
            {
                ("logistics", "yearly", currency): f"price_logistics_yearly_{currency}"
                for currency in PUBLIC_PRICING_CURRENCIES
            }
        )
    return {
        "STRIPE_ENABLED": True,
        "STRIPE_PUBLISHABLE_KEY": "pk_test_logistics",
        "STRIPE_SECRET_KEY": "sk_test_logistics",
        "STRIPE_WEBHOOK_SECRET": "whsec_logistics",
        "STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "bpc_test_logistics",
        "STRIPE_PRICE_ID_MAP": price_map,
    }


class LogisticsOfferingTests(TestCase):
    def setUp(self):
        self.logistics_plan = ClarivoPlan.objects.get(slug="logistics")
        self.logistics_plan.is_active = True
        self.logistics_plan.save(update_fields=["is_active"])
        self.service_plan = ClarivoPlan.objects.get(slug="pro")
        self.business = Business.objects.create(
            name="Logistics", slug="logistics-tests", vertical="LOGISTICS"
        )
        self.service_business = Business.objects.create(name="Service", slug="service-tests")
        self.user = TaskIOUser.objects.create_user(
            email="logistics@example.com", password="testpass123"
        )
        BusinessUser.objects.create(
            business=self.business, user=self.user, role=BusinessUser.Role.OWNER
        )
        self.now = timezone.now()

    def pending(self):
        return ensure_pending_checkout_subscription(
            business=self.business,
            plan=self.logistics_plan,
            billing_interval="yearly",
            currency="usd",
        )

    def active(self):
        return BusinessSubscription.objects.create(
            business=self.business,
            plan=self.logistics_plan,
            status="active",
            payment_provider="stripe",
            billing_interval="yearly",
            billing_currency="usd",
            provider_price_id="price_logistics_yearly_usd",
            provider_customer_id="cus_logistics",
            provider_subscription_id="sub_logistics",
            current_period_start=self.now,
            current_period_end=self.now + timedelta(days=365),
        )

    def remote(self, subscription, *, status="active", price_slug="logistics", interval="year"):
        return {
            "id": "sub_logistics",
            "customer": "cus_logistics",
            "status": status,
            "trial_start": None,
            "trial_end": None,
            "current_period_start": int(self.now.timestamp()),
            "current_period_end": int((self.now + timedelta(days=365)).timestamp()),
            "metadata": {
                "motionmate_business_id": str(self.business.pk),
                "motionmate_subscription_id": str(subscription.pk),
                "plan_slug": subscription.plan.slug,
                "billing_interval": subscription.billing_interval,
                "billing_currency": subscription.billing_currency,
            },
            "items": {
                "data": [
                    {
                        "price": {
                            "id": f"price_{price_slug}_yearly_usd",
                            "currency": "usd",
                            "recurring": {"interval": interval},
                        }
                    }
                ]
            },
        }

    def sync(self, remote, *, source="customer.subscription.updated", event_at=None):
        return _sync_subscription_object(
            provider_subscription=remote,
            provider_event_at=event_at or self.now,
            source=source,
            source_provider_event_id="evt_logistics",
        )

    def test_public_catalog_and_existing_plan_families_are_unchanged(self):
        self.assertEqual(
            list(ClarivoPlan.motionmate_plans().values_list("slug", flat=True)),
            list(PUBLIC_PAID_PLAN_SLUGS),
        )
        self.assertEqual(
            set(
                ClarivoPlan.objects.filter(slug__in=PUBLIC_PAID_PLAN_SLUGS).values_list(
                    "family", flat=True
                )
            ),
            {"SERVICE"},
        )
        self.assertEqual(self.logistics_plan.family, "LOGISTICS")
        self.assertEqual(ClarivoPlan(name="Legacy", slug="legacy").family, "SERVICE")
        self.assertTrue(is_stripe_billable_plan(self.logistics_plan))
        self.assertFalse(ClarivoPlan.motionmate_plans().filter(pk=self.logistics_plan.pk).exists())

    def test_normal_registration_excludes_and_rejects_logistics(self):
        form = BusinessRegistrationForm()
        self.assertEqual(
            list(form.fields["plan"].queryset.values_list("slug", flat=True)),
            list(PUBLIC_PAID_PLAN_SLUGS),
        )
        with self.assertRaises(ValidationError):
            form.fields["plan"].clean("logistics")

    def test_normal_plan_change_ui_cannot_assign_service_to_logistics(self):
        self.active()
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        response = self.client.post(
            reverse("business_subscription"),
            {"plan": self.service_plan.pk, "confirm_plan_change": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["plan_form"].errors)
        self.assertEqual(
            BusinessSubscription.objects.get(business=self.business).plan_id, self.logistics_plan.pk
        )

    def test_local_plan_changes_reject_both_cross_family_directions(self):
        for business, plan in (
            (self.service_business, self.logistics_plan),
            (self.business, self.service_plan),
            (self.business, self.logistics_plan),
        ):
            with (
                self.subTest(business=business.vertical, plan=plan.slug),
                self.assertRaises(ValueError),
            ):
                assign_business_subscription_plan(business, plan)
        self.assertFalse(BusinessSubscription.objects.exists())

    def test_normal_service_plan_change_ui_rejects_logistics(self):
        subscription = create_default_trial_subscription(self.service_business)
        BusinessUser.objects.create(
            business=self.service_business, user=self.user, role=BusinessUser.Role.OWNER
        )
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.service_business.pk
        session.save()
        response = self.client.post(
            reverse("business_subscription"),
            {"plan": self.logistics_plan.pk, "confirm_plan_change": "1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["plan_form"].errors)
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan_id, self.service_plan.pk)

    def test_direct_subscription_creation_rejects_cross_family_monthly_and_trial(self):
        for business, plan, interval, status in (
            (self.service_business, self.logistics_plan, "yearly", "active"),
            (self.business, self.service_plan, "yearly", "active"),
            (self.business, self.logistics_plan, "monthly", "pending_checkout"),
            (self.business, self.logistics_plan, "yearly", "trialing"),
        ):
            with (
                self.subTest(business=business.vertical, interval=interval, status=status),
                self.assertRaises(ValidationError),
            ):
                BusinessSubscription.objects.create(
                    business=business, plan=plan, billing_interval=interval, status=status
                )

    def test_invalid_bulk_update_does_not_grant_access(self):
        subscription = self.active()
        BusinessSubscription.objects.filter(pk=subscription.pk).update(plan=self.service_plan)
        subscription.refresh_from_db()
        self.assertFalse(subscription.has_access)
        self.assertFalse(subscription.can_use_module("clients"))
        self.assertFalse(subscription.is_stripe_billable)

    def test_logistics_has_shared_and_domain_entitlements_without_service_workflows(self):
        subscription = self.active()
        for capability in (
            "workspace",
            "team",
            "clients",
            "invoicing",
            "parcels",
            "tracking",
            "shipments",
            "manifests",
        ):
            with self.subTest(capability=capability):
                self.assertTrue(subscription.can_use_module(capability))
        for capability in ("services", "service_requests", "appointments", "public_booking"):
            with self.subTest(capability=capability):
                self.assertFalse(subscription.can_use_module(capability))

    def test_service_local_trial_still_lasts_exactly_fourteen_days(self):
        with mock.patch("apps.businesses.utils.timezone.now", return_value=self.now):
            subscription = create_default_trial_subscription(self.service_business)
        self.assertEqual(subscription.status, "trialing")
        self.assertEqual(subscription.trial_start, self.now)
        self.assertEqual(subscription.trial_end, self.now + timedelta(days=14))
        self.assertEqual(subscription.plan.slug, "pro")

    def test_logistics_receives_no_automatic_local_trial(self):
        self.assertIsNone(create_default_trial_subscription(self.business))
        self.assertIsNone(
            create_default_trial_subscription(self.business, plan=self.logistics_plan)
        )
        self.assertEqual(billing_offering("logistics").trial_days, 0)
        self.assertFalse(BusinessSubscription.objects.exists())

    def test_seed_reapplication_preserves_configured_pricing(self):
        self.logistics_plan.price_yearly = Decimal("123.45")
        self.logistics_plan.save(update_fields=["price_yearly"])
        seed = import_module(
            "apps.businesses.migrations.0026_logistics_offering"
        ).seed_logistics_offering
        seed(apps, SimpleNamespace(connection=connection))
        self.logistics_plan.refresh_from_db()
        self.assertEqual(self.logistics_plan.price_yearly, Decimal("123.45"))
        self.assertTrue(self.logistics_plan.is_active)

    def test_seed_rollback_refuses_to_delete_a_configured_offering(self):
        remove = import_module(
            "apps.businesses.migrations.0026_logistics_offering"
        ).remove_logistics_offering
        with self.assertRaises(RuntimeError):
            remove(apps, SimpleNamespace(connection=connection))
        self.assertTrue(ClarivoPlan.objects.filter(pk=self.logistics_plan.pk).exists())

    @override_settings(**stripe_settings())
    def test_yearly_pending_checkout_is_allowed_without_access_or_trial(self):
        subscription = self.pending()
        self.assertEqual(subscription.status, "pending_checkout")
        self.assertEqual(subscription.billing_interval, "yearly")
        self.assertIsNone(subscription.trial_start)
        self.assertIsNone(subscription.trial_end)
        self.assertFalse(subscription.has_access)
        self.assertFalse(subscription.is_public_paid_plan)
        self.assertTrue(subscription.is_stripe_billable)

    @override_settings(**stripe_settings())
    def test_checkout_rejects_monthly_and_cross_family_before_creating_rows(self):
        for business, plan, interval in (
            (self.business, self.logistics_plan, "monthly"),
            (self.service_business, self.logistics_plan, "yearly"),
            (self.business, self.service_plan, "yearly"),
        ):
            with (
                self.subTest(vertical=business.vertical, plan=plan.slug),
                self.assertRaises(StripeCheckoutError),
            ):
                ensure_pending_checkout_subscription(
                    business=business, plan=plan, billing_interval=interval, currency="usd"
                )
        self.assertFalse(BusinessSubscription.objects.exists())

    @override_settings(**stripe_settings())
    def test_stripe_yearly_checkout_omits_trial_and_preserves_metadata(self):
        from apps.logistics.models import LogisticsApplication
        from apps.logistics.services import review_application
        from apps.logistics.tests import application_data

        # Block 5 requires a current converted approval at the shared entry point.
        application = LogisticsApplication.objects.create(
            **application_data(email=self.user.email, preferred_currency="USD")
        )
        reviewer = TaskIOUser.objects.create_superuser(email="billing-reviewer@example.com")
        review_application(
            application.pk,
            result="APPROVED",
            actor=reviewer,
            reason="Checkout fixture approved",
            expected_revision=1,
        )
        LogisticsApplication.objects.filter(pk=application.pk).update(
            business=self.business,
            enrolled_user=self.user,
            converted_revision=1,
            converted_at=self.now,
        )
        self.logistics_plan.regional_prices = {"usd": {"currency": "USD", "yearly": "100.00"}}
        self.logistics_plan.save(update_fields=["regional_prices"])
        subscription = self.pending()
        session_create = mock.Mock(
            return_value={"id": "cs_logistics", "url": "https://checkout.stripe.test/logistics"}
        )
        sdk = SimpleNamespace(
            checkout=SimpleNamespace(Session=SimpleNamespace(create=session_create)),
            Price=SimpleNamespace(
                retrieve=mock.Mock(
                    return_value={
                        "id": "price_logistics_yearly_usd",
                        "active": True,
                        "type": "recurring",
                        "currency": "usd",
                        "unit_amount": 10000,
                        "billing_scheme": "per_unit",
                        "recurring": {
                            "interval": "year",
                            "interval_count": 1,
                            "usage_type": "licensed",
                        },
                    }
                )
            ),
        )
        with mock.patch("apps.businesses.stripe_checkout.configure_stripe_sdk", return_value=sdk):
            url = create_trial_checkout_session(
                request=RequestFactory().post("/", HTTP_HOST="localhost"),
                subscription=subscription,
                user=self.user,
            )
        self.assertEqual(url, "https://checkout.stripe.test/logistics")
        params = session_create.call_args.kwargs
        self.assertNotIn("trial_period_days", params["subscription_data"])
        self.assertEqual(
            params["line_items"], [{"price": "price_logistics_yearly_usd", "quantity": 1}]
        )
        self.assertEqual(params["metadata"]["plan_slug"], "logistics")
        self.assertEqual(params["metadata"]["motionmate_business_id"], str(self.business.pk))
        self.assertEqual(params["subscription_data"]["metadata"], params["metadata"])

    @override_settings(**stripe_settings())
    def test_resume_revalidates_offering_before_reusing_a_session(self):
        subscription = self.pending()
        subscription.provider_checkout_session_id = "cs_logistics"
        subscription.billing_interval = "monthly"
        with (
            mock.patch("apps.businesses.stripe_checkout.configure_stripe_sdk") as configure,
            self.assertRaises(StripeCheckoutError),
        ):
            resume_trial_checkout_session(
                request=RequestFactory().post("/"), subscription=subscription, user=self.user
            )
        configure.assert_not_called()

    @override_settings(**stripe_settings())
    def test_service_stripe_monthly_and_yearly_keep_fourteen_day_trial(self):
        for interval in PUBLIC_BILLING_INTERVALS:
            with self.subTest(interval=interval):
                subscription = ensure_pending_checkout_subscription(
                    business=self.service_business,
                    plan=self.service_plan,
                    billing_interval=interval,
                    currency="usd",
                )
                create = mock.Mock(
                    return_value={
                        "id": f"cs_{interval}",
                        "url": "https://checkout.stripe.test/service",
                    }
                )
                sdk = SimpleNamespace(
                    checkout=SimpleNamespace(Session=SimpleNamespace(create=create))
                )
                with mock.patch(
                    "apps.businesses.stripe_checkout.configure_stripe_sdk", return_value=sdk
                ):
                    create_trial_checkout_session(
                        request=RequestFactory().post("/", HTTP_HOST="localhost"),
                        subscription=subscription,
                        user=self.user,
                    )
                self.assertEqual(
                    create.call_args.kwargs["subscription_data"]["trial_period_days"], 14
                )
                self.assertEqual(create.call_args.kwargs["metadata"]["plan_slug"], "pro")
                subscription.delete()

    @override_settings(**stripe_settings())
    def test_webhook_activates_annual_logistics_and_enqueues_activation(self):
        subscription = self.pending()
        self.sync(self.remote(subscription))
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, "active")
        self.assertIsNone(subscription.trial_end)
        self.assertTrue(subscription.has_access)
        self.assertEqual(
            SubscriptionNotification.objects.get().notification_type, "subscription_activated"
        )

    @override_settings(**stripe_settings())
    def test_webhook_rejects_trial_monthly_and_service_price(self):
        subscription = self.pending()
        for options in ({"status": "trialing"}, {"interval": "month"}, {"price_slug": "pro"}):
            with self.subTest(options=options), self.assertRaises(StripeWebhookProcessingError):
                self.sync(self.remote(subscription, **options))
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, "pending_checkout")
        self.assertEqual(SubscriptionNotification.objects.count(), 0)

    @override_settings(**stripe_settings())
    def test_webhook_rejects_mismatched_business_vertical(self):
        subscription = self.pending()
        Business.objects.filter(pk=self.business.pk).update(vertical="SERVICE")
        with self.assertRaises(StripeWebhookProcessingError):
            self.sync(self.remote(subscription))

    @override_settings(**stripe_settings())
    def test_past_due_grace_reminders_and_recovery_reuse_shared_lifecycle(self):
        subscription = self.active()
        self.sync(self.remote(subscription, status="past_due"))
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, "past_due")
        self.assertTrue(subscription.has_access)
        self.assertIsNotNone(subscription.grace_period_ends_at)
        self.assertFalse(subscription.effective_access_state.payment_recovery_available)
        notification = SubscriptionNotification.objects.get(
            notification_type="payment_grace_started"
        )
        context = build_subscription_notification_email_context(notification)
        self.assertIn(
            "Contact support for help with your Logistics subscription payment.",
            context["body_lines"],
        )
        self.assertNotIn(
            "Open the Motionmate subscription page to update your payment method.",
            context["body_lines"],
        )
        reminder_at = subscription.grace_period_ends_at - timedelta(hours=12)
        enqueue_due_subscription_reminders(evaluation_time=reminder_at)
        self.assertTrue(
            SubscriptionNotification.objects.filter(
                notification_type="payment_grace_ending_1_day"
            ).exists()
        )
        self.assertTrue(
            subscription.can_view_module_at("clients", subscription.grace_period_ends_at)
        )
        self.assertFalse(
            subscription.can_modify_module_at("clients", subscription.grace_period_ends_at)
        )
        enqueue_due_subscription_reminders(evaluation_time=subscription.grace_period_ends_at)
        self.assertTrue(
            SubscriptionNotification.objects.filter(
                notification_type="restricted_mode_started"
            ).exists()
        )
        recovered_at = subscription.grace_period_ends_at + timedelta(minutes=1)
        self.sync(
            self.remote(subscription, status="active"), source="invoice.paid", event_at=recovered_at
        )
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, "active")
        self.assertIsNone(subscription.past_due_since)
        self.assertTrue(subscription.has_access_at(recovered_at))
        self.assertTrue(
            SubscriptionNotification.objects.filter(notification_type="payment_recovered").exists()
        )

    @override_settings(**stripe_settings())
    def test_invalid_monthly_logistics_is_ineligible_for_outbox(self):
        subscription = self.active()
        subscription.billing_interval = "monthly"
        rows = enqueue_subscription_notification(
            subscription=subscription,
            notification_type="subscription_activated",
            deduplication_context="invalid",
        )
        self.assertEqual(rows, [])

    @override_settings(**stripe_settings())
    def test_logistics_portal_and_recovery_portal_remain_disabled(self):
        subscription = self.active()
        availability = get_customer_portal_availability(
            business=self.business, user=self.user, subscription=subscription
        )
        self.assertFalse(availability.can_open)
        self.assertEqual(availability.reason, "logistics_portal_disabled")
        subscription.status = "past_due"
        availability = get_payment_recovery_portal_availability(
            business=self.business, user=self.user, subscription=subscription
        )
        self.assertFalse(availability.can_open)
        self.assertEqual(availability.reason, "logistics_portal_disabled")


class LogisticsPriceConfigurationTests(SimpleTestCase):
    def test_environment_pattern_includes_only_yearly_logistics_prices(self):
        from config import Settings

        config = Settings(
            _env_file=None,
            stripe_price_logistics_yearly_usd="  price_logistics_yearly_usd  ",
            stripe_price_logistics_yearly_eur=None,
        )
        self.assertEqual(config.stripe_price_logistics_yearly_usd, "price_logistics_yearly_usd")
        self.assertEqual(config.stripe_price_logistics_yearly_eur, "")
        self.assertFalse(hasattr(config, "stripe_price_logistics_monthly_usd"))

    @override_settings(**stripe_settings(logistics=False))
    def test_existing_service_configuration_needs_no_logistics_prices(self):
        self.assertEqual(validate_stripe_configuration(), [])
        for slug in PUBLIC_PAID_PLAN_SLUGS:
            for interval in PUBLIC_BILLING_INTERVALS:
                for currency in PUBLIC_PRICING_CURRENCIES:
                    self.assertEqual(
                        get_stripe_price_id(
                            plan_slug=slug, billing_interval=interval, currency=currency
                        ),
                        f"price_{slug}_{interval}_{currency}",
                    )
        with self.assertRaises(StripeConfigurationError):
            get_stripe_price_id(plan_slug="logistics", billing_interval="yearly", currency="usd")

    @override_settings(**stripe_settings())
    def test_logistics_yearly_prices_resolve_without_monthly_mapping(self):
        self.assertEqual(validate_stripe_configuration(), [])
        for currency in PUBLIC_PRICING_CURRENCIES:
            price = get_stripe_price_id(
                plan_slug="logistics", billing_interval="yearly", currency=currency
            )
            self.assertEqual(resolve_stripe_price_id(price).plan_slug, "logistics")
        with self.assertRaises(StripeConfigurationError):
            get_stripe_price_id(plan_slug="logistics", billing_interval="monthly", currency="usd")

    def test_logistics_monthly_mapping_is_rejected_and_service_checks_remain_required(self):
        config = stripe_settings()
        config["STRIPE_PRICE_ID_MAP"][("logistics", "monthly", "usd")] = "price_invalid_monthly"
        del config["STRIPE_PRICE_ID_MAP"][("starter", "monthly", "usd")]
        with override_settings(**config):
            issue_ids = {issue.id for issue in validate_stripe_configuration()}
        self.assertIn(STRIPE_CHECK_UNSUPPORTED_INTERVAL, issue_ids)
        self.assertIn(STRIPE_CHECK_MISSING_PRICE_ID, issue_ids)


class PlanFamilyMigrationTests(TransactionTestCase):
    def test_existing_rows_default_to_service_and_seed_is_inactive_with_unset_prices(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [("businesses", "0024_business_vertical")]
        after = [("businesses", "0026_logistics_offering")]
        try:
            executor.migrate(before)
            historical = executor.loader.project_state(before).apps
            OldPlan = historical.get_model("businesses", "ClarivoPlan")
            legacy = OldPlan.objects.create(
                name="Legacy custom plan", slug="legacy-family", price_monthly=Decimal("45.67")
            )
            snapshot = {
                plan.pk: (plan.slug, plan.price_monthly, plan.price_yearly, plan.max_clients)
                for plan in OldPlan.objects.all()
            }
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            Plan = executor.loader.project_state(after).apps.get_model("businesses", "ClarivoPlan")
            for pk, values in snapshot.items():
                plan = Plan.objects.get(pk=pk)
                self.assertEqual(plan.family, "SERVICE")
                self.assertEqual(
                    (plan.slug, plan.price_monthly, plan.price_yearly, plan.max_clients), values
                )
            self.assertEqual(Plan.objects.get(pk=legacy.pk).family, "SERVICE")
            logistics = Plan.objects.get(slug="logistics")
            self.assertEqual(logistics.family, "LOGISTICS")
            self.assertFalse(logistics.is_active)
            self.assertEqual(logistics.price_yearly, Decimal("0.00"))
            self.assertEqual(logistics.price_monthly, Decimal("0.00"))
        finally:
            MigrationExecutor(connection).migrate(latest)
