"""Reusable Logistics free-test links exercise the existing registration boundary."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.forms.models import model_to_dict
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.businesses.admin import CommercialPlanAdminForm
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.plan_catalog import LOGISTICS_TIER_CAPACITY_FIELDS, LOGISTICS_TIER_SLUGS
from apps.businesses.stripe_checkout import StripeCheckoutError, _validated_checkout_dimensions
from apps.businesses.stripe_config import StripeConfigurationError
from apps.businesses.stripe_portal import (
    get_customer_portal_availability,
    get_payment_recovery_portal_availability,
)
from apps.businesses.usage_limits import QuotaError
from apps.businesses.utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    can_use_module,
    resolve_business_plan_limit,
)
from apps.crm.models import Client
from apps.logistics.billing import validate_offering_activation
from apps.logistics.classification import default_operating_areas
from apps.logistics.models import LogisticsApplication, LogisticsProfile
from config import Settings

from .forms import BusinessRegistrationForm
from .free_test_registration import FREE_TEST_TOKEN_SETTING_BY_PLAN
from .models import SaaSUserProfile, TaskIOUser

TOKENS = {slug: f"fixture-only-{slug}-registration-secret" for slug in LOGISTICS_TIER_SLUGS}
TOKEN_SETTINGS = {FREE_TEST_TOKEN_SETTING_BY_PLAN[slug]: token for slug, token in TOKENS.items()}
EXPECTED_LIMITS = {
    "logistics-core": (10, 2, 250, 300, 80, 100, 25, 3000, 300, 1),
    "logistics-growth": (15, 4, 800, 900, 200, 300, 50, 9000, 900, 3),
    "logistics-scale": (25, 8, 2000, 1800, 400, 600, 100, 18000, 1800, 6),
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


class LogisticsFreeTestConfigurationTests(SimpleTestCase):
    def test_tokens_default_empty(self):
        configuration = Settings(_env_file=None)
        for tier in LOGISTICS_TIER_SLUGS:
            self.assertEqual(
                getattr(configuration, FREE_TEST_TOKEN_SETTING_BY_PLAN[tier].lower()), ""
            )

    def test_tokens_are_trimmed(self):
        values = {
            FREE_TEST_TOKEN_SETTING_BY_PLAN[tier].lower(): f" {TOKENS[tier]} "
            for tier in LOGISTICS_TIER_SLUGS
        }
        configuration = Settings(_env_file=None, **values)
        for tier in LOGISTICS_TIER_SLUGS:
            self.assertEqual(
                getattr(configuration, FREE_TEST_TOKEN_SETTING_BY_PLAN[tier].lower()), TOKENS[tier]
            )


@override_settings(
    FREE_TEST_REGISTRATION_ENABLED=True,
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
    MOTIONMATE_ENVIRONMENT="production",
    DEBUG=False,
    STRIPE_ENABLED=True,
    STRIPE_SECRET_KEY="sk_live_fixture_only",
    STRIPE_PUBLISHABLE_KEY="pk_live_fixture_only",
    STRIPE_LOGISTICS_TIER_PRICE_ID_MAP={},
    **TOKEN_SETTINGS,
)
class LogisticsFreeTestRegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Free availability never activates the paid offering, even with LIVE keys.
        ClarivoPlan.objects.filter(slug__in=LOGISTICS_TIER_SLUGS).update(
            is_active=False, logistics_free_test_enabled=True
        )

    def setUp(self):
        http = patch(
            "stripe._http_client.RequestsClient.request",
            side_effect=AssertionError("Stripe called"),
        )
        self.stripe_http = http.start()
        self.addCleanup(http.stop)
        self.addCleanup(self.stripe_http.assert_not_called)

    def url(self, tier, token=None):
        return reverse("register_business_free_test", args=[tier, token or TOKENS[tier]])

    def payload(self, tier, suffix="", **overrides):
        data = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": f"{tier}{suffix}@example.test",
            "business_name": f"Free {tier}{suffix}",
            "business_email": f"office-{tier}{suffix}@example.test",
            "country": "Sint Maarten",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        }
        data.update(overrides)
        return data

    def register(self, tier, suffix="", **overrides):
        self.client.logout()
        response = self.client.post(self.url(tier), self.payload(tier, suffix, **overrides))
        self.assertRedirects(response, reverse("agent_dashboard"))
        return Business.objects.get(name=f"Free {tier}{suffix}")

    def assert_no_registration(self, payload):
        self.assertFalse(TaskIOUser.objects.filter(email__iexact=payload["email"]).exists())
        self.assertFalse(Business.objects.filter(name=payload["business_name"]).exists())

    def test_admin_enables_only_selected_free_tier_without_paid_activation_or_stripe(self):
        ClarivoPlan.objects.filter(slug__in=LOGISTICS_TIER_SLUGS).update(
            logistics_free_test_enabled=False
        )
        plan = ClarivoPlan.objects.get(slug="logistics-scale")
        data = {**model_to_dict(plan), "logistics_free_test_enabled": True}
        with patch("apps.logistics.billing.configure_stripe_sdk") as sdk:
            form = CommercialPlanAdminForm(data, instance=plan)
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
        sdk.assert_not_called()
        plan.refresh_from_db()
        self.assertTrue(plan.allows_logistics_free_test)
        self.assertFalse(plan.is_active)
        self.assertEqual(self.client.get(self.url(plan.slug)).status_code, 200)
        for slug in ("logistics-core", "logistics-growth"):
            self.assertFalse(ClarivoPlan.objects.get(slug=slug).logistics_free_test_enabled)
            self.assertRedirects(self.client.get(self.url(slug)), reverse("register_business"))

    def test_free_flag_cannot_skip_paid_activation_or_checkout_validation(self):
        business = self.register("logistics-scale")
        plan = business.subscription.plan
        with self.assertRaises(StripeCheckoutError):
            _validated_checkout_dimensions(
                business=business, plan=plan, billing_interval="yearly", currency="eur"
            )
        plan.is_active = True
        with self.assertRaisesMessage(StripeConfigurationError, "TEST keys"):
            validate_offering_activation(plan)
        form = CommercialPlanAdminForm(model_to_dict(plan), instance=plan)
        self.assertFalse(form.is_valid())
        with self.assertRaisesMessage(StripeConfigurationError, "TEST keys"):
            _validated_checkout_dimensions(
                business=business, plan=plan, billing_interval="yearly", currency="eur"
            )
        plan.refresh_from_db()
        self.assertFalse(plan.is_active)

    def test_admin_free_flag_rejects_other_plans_and_incomplete_tiers(self):
        for slug in (*LOGISTICS_TIER_SLUGS, "starter", "beta", "logistics"):
            plan = ClarivoPlan.objects.get(slug=slug)
            changes = [{"logistics_free_test_enabled": True, "is_active": False}]
            if slug in LOGISTICS_TIER_SLUGS:
                changes = [
                    {**changes[0], field: None} for field in LOGISTICS_TIER_CAPACITY_FIELDS
                ] + [{**changes[0], "family": ClarivoPlan.Family.SERVICE}]
            for change in changes:
                with self.subTest(slug=slug, change=change):
                    form = CommercialPlanAdminForm(
                        {**model_to_dict(plan), **change},
                        instance=ClarivoPlan.objects.get(pk=plan.pk),
                    )
                    self.assertFalse(form.is_valid())
                    self.assertIn("logistics_free_test_enabled", form.errors)

    def test_access_exception_requires_free_test_local_and_preserves_suspension(self):
        business = self.register("logistics-scale")
        subscription = business.subscription
        for field, value in (
            ("payment_provider", BusinessSubscription.PaymentProvider.STRIPE),
            ("provisioning_source", BusinessSubscription.ProvisioningSource.STANDARD),
        ):
            original = getattr(subscription, field)
            setattr(subscription, field, value)
            self.assertEqual(
                subscription.effective_access_state.code, subscription.AccessCode.PLAN_INACTIVE
            )
            setattr(subscription, field, original)
        for status in (
            BusinessSubscription.Status.PENDING_CHECKOUT,
            BusinessSubscription.Status.PAST_DUE,
            BusinessSubscription.Status.CANCELLED,
            BusinessSubscription.Status.EXPIRED,
        ):
            subscription.status = status
            self.assertFalse(subscription.has_access)
        subscription.status = BusinessSubscription.Status.ACTIVE
        self.assertTrue(subscription.has_access)
        subscription.logistics_approval_review_required = True
        self.assertFalse(subscription.has_access)
        subscription.logistics_approval_review_required = False
        subscription.business.is_active = False
        self.assertFalse(subscription.has_access)
        subscription.business.is_active = True
        subscription.plan.logistics_free_test_enabled = False
        self.assertFalse(subscription.has_access)

    def test_existing_active_free_tier_does_not_require_new_flag(self):
        ClarivoPlan.objects.filter(slug="logistics-scale").update(
            is_active=True, logistics_free_test_enabled=False
        )
        business = self.register("logistics-scale")
        self.assertTrue(business.subscription.has_access)

    @override_settings(STRIPE_ENABLED=False, STRIPE_SECRET_KEY="", STRIPE_PUBLISHABLE_KEY="")
    def test_free_registration_does_not_require_any_stripe_keys(self):
        with patch("apps.logistics.billing.configure_stripe_sdk") as sdk:
            business = self.register("logistics-scale")
        sdk.assert_not_called()
        self.assertTrue(business.subscription.has_access)

    def test_each_tier_provisions_logistics_owner_profiles_and_session_without_stripe(self):
        with (
            patch("apps.accounts.views.ensure_pending_checkout_subscription") as pending,
            patch("apps.accounts.views.create_trial_checkout_session") as checkout,
            patch(
                "stripe._http_client.RequestsClient.request",
                side_effect=AssertionError("Stripe called"),
            ) as http,
        ):
            for tier in LOGISTICS_TIER_SLUGS:
                with self.subTest(tier=tier):
                    business = self.register(tier)
                    subscription = business.subscription
                    owner = business.memberships.get()
                    self.assertEqual(business.vertical, Business.Vertical.LOGISTICS)
                    self.assertTrue(business.is_active)
                    self.assertEqual(owner.role, BusinessUser.Role.OWNER)
                    self.assertTrue(owner.is_active)
                    self.assertTrue(owner.user.check_password("StrongPass123!"))
                    profile = business.logistics_profile
                    self.assertEqual(profile.operating_areas, default_operating_areas())
                    self.assertEqual(profile.transportation_modes, [])
                    self.assertIsNone(profile.location_access_reviewed_at)
                    self.assertIsNone(profile.location_operations_enabled_at)
                    user_profile = SaaSUserProfile.objects.get(user=owner.user)
                    self.assertEqual(user_profile.workspace_name, business.name)
                    self.assertEqual(user_profile.billing_email, business.email)
                    self.assertEqual(
                        int(self.client.session[CURRENT_BUSINESS_SESSION_KEY]), business.pk
                    )
                    self.assertEqual(int(self.client.session["_auth_user_id"]), owner.user_id)
                    self.assertEqual(subscription.plan.slug, tier)
                    self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
                    self.assertEqual(
                        subscription.provisioning_source,
                        BusinessSubscription.ProvisioningSource.FREE_TEST,
                    )
                    self.assertEqual(
                        subscription.payment_provider, BusinessSubscription.PaymentProvider.LOCAL
                    )
                    self.assertEqual(
                        subscription.billing_interval, BusinessSubscription.BillingInterval.YEARLY
                    )
                    self.assertEqual(subscription.billing_currency, "")
                    for field in (
                        "provider_customer_id",
                        "provider_subscription_id",
                        "provider_checkout_session_id",
                        "provider_price_id",
                    ):
                        self.assertEqual(getattr(subscription, field), "")
                    for field in (
                        "trial_start",
                        "trial_end",
                        "current_period_start",
                        "current_period_end",
                        "checkout_session_expires_at",
                    ):
                        self.assertIsNone(getattr(subscription, field))
                    self.assertFalse(subscription.cancel_at_period_end)
                    self.assertFalse(subscription.logistics_approval_review_required)
                    self.assertTrue(subscription.has_access)
                    self.assertFalse(subscription.plan.is_active)
                    self.assertIsNone(subscription.access_ends_at)
                    self.assertFalse(
                        LogisticsApplication.objects.filter(business=business).exists()
                    )
            pending.assert_not_called()
            checkout.assert_not_called()
            http.assert_not_called()

    def test_each_tier_has_its_existing_capacities_and_logistics_modules(self):
        for tier, limits in EXPECTED_LIMITS.items():
            with self.subTest(tier=tier):
                business = self.register(tier)
                for metric, expected in zip(METRICS, limits, strict=True):
                    entitlement = resolve_business_plan_limit(business, metric)
                    self.assertTrue(entitlement.available, metric)
                    self.assertEqual(entitlement.limit, expected, metric)
                for module in (
                    "clients",
                    "team",
                    "services",
                    "parcels",
                    "tracking",
                    "shipments",
                    "manifests",
                    "invoicing",
                ):
                    self.assertTrue(can_use_module(business, module), module)
                for module in ("appointments", "public_booking", "service_requests"):
                    self.assertFalse(can_use_module(business, module), module)

    def test_free_registration_still_enforces_the_normal_client_quota(self):
        for tier in LOGISTICS_TIER_SLUGS:
            with self.subTest(tier=tier):
                ClarivoPlan.objects.filter(slug=tier).update(max_clients=1)
                business = self.register(tier)
                Client.objects.create(
                    business=business, first_name="First", email=f"first-{tier}@example.test"
                )
                with self.assertRaises(QuotaError):
                    Client.objects.create(
                        business=business,
                        first_name="Blocked",
                        email=f"blocked-{tier}@example.test",
                    )
                self.assertEqual(business.clients.count(), 1)

    def test_each_link_is_reusable_for_distinct_accounts(self):
        for tier in LOGISTICS_TIER_SLUGS:
            with self.subTest(tier=tier):
                first = self.register(tier, "-first")
                second = self.register(tier, "-second")
                self.assertNotEqual(first.pk, second.pk)
                self.assertEqual(first.subscription.plan_id, second.subscription.plan_id)

    def test_wrong_missing_and_other_tier_tokens_reject_get_and_post(self):
        for tier in LOGISTICS_TIER_SLUGS:
            for token in (
                "invalid",
                TOKENS["logistics-growth" if tier == "logistics-core" else "logistics-core"],
            ):
                with self.subTest(tier=tier, token=token):
                    for method in ("get", "post"):
                        response = getattr(self.client, method)(
                            self.url(tier, token), self.payload(tier)
                        )
                        self.assertRedirects(response, reverse("register_business"))
                    self.assert_no_registration(self.payload(tier))
            with override_settings(**{FREE_TEST_TOKEN_SETTING_BY_PLAN[tier]: ""}):
                response = self.client.post(self.url(tier), self.payload(tier))
                self.assertRedirects(response, reverse("register_business"))
                self.assert_no_registration(self.payload(tier))

    def test_disabled_links_reject_registration_for_every_tier(self):
        with override_settings(FREE_TEST_REGISTRATION_ENABLED=False):
            for tier in LOGISTICS_TIER_SLUGS:
                for method in ("get", "post"):
                    response = getattr(self.client, method)(self.url(tier), self.payload(tier))
                    self.assertRedirects(response, reverse("register_business"))
                self.assert_no_registration(self.payload(tier))

    def test_tier_is_locked_in_get_and_rejects_post_tier_and_vertical_tampering(self):
        for tier in LOGISTICS_TIER_SLUGS:
            with self.subTest(tier=tier):
                response = self.client.get(
                    self.url(tier), {"plan": "starter", "vertical": "SERVICE"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["free_test_plan"].slug, tier)
                self.assertContains(response, f'value="{tier}"')
                self.assertNotContains(response, '<select name="plan"')
                for overrides in (
                    {"plan": "starter"},
                    {"plan": "logistics-scale" if tier != "logistics-scale" else "logistics-core"},
                    {"vertical": "SERVICE"},
                ):
                    payload = self.payload(tier, **overrides)
                    response = self.client.post(self.url(tier), payload)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.context["form"].errors)
                    self.assert_no_registration(payload)

    def test_inactive_wrong_family_missing_and_every_incomplete_capacity_are_unavailable(self):
        for tier in LOGISTICS_TIER_SLUGS:
            plan = ClarivoPlan.objects.get(slug=tier)
            cases = [{"logistics_free_test_enabled": False}, {"family": "SERVICE"}]
            cases += [{field: None} for field in LOGISTICS_TIER_CAPACITY_FIELDS]
            for changes in cases:
                with self.subTest(tier=tier, changes=changes):
                    ClarivoPlan.objects.filter(pk=plan.pk).update(**changes)
                    for method in ("get", "post"):
                        response = getattr(self.client, method)(self.url(tier), self.payload(tier))
                        self.assertRedirects(response, reverse("register_business"))
                    form = BusinessRegistrationForm(self.payload(tier), free_test_plan_slug=tier)
                    self.assertFalse(form.is_valid())
                    self.assert_no_registration(self.payload(tier))
                    ClarivoPlan.objects.filter(pk=plan.pk).update(
                        **{field: getattr(plan, field) for field in changes}
                    )
            plan.delete()
            response = self.client.post(self.url(tier), self.payload(tier))
            self.assertRedirects(response, reverse("register_business"))
            self.assert_no_registration(self.payload(tier))

    def test_retired_unknown_and_public_registration_cannot_request_logistics_free_access(self):
        for tier in ("logistics", "enterprise", "LOGISTICS-CORE"):
            response = self.client.post(
                reverse("register_business_free_test", args=[tier, TOKENS["logistics-core"]]),
                self.payload("logistics-core"),
            )
            self.assertRedirects(response, reverse("register_business"))
        for tier in LOGISTICS_TIER_SLUGS:
            payload = self.payload(tier, plan=tier)
            response = self.client.post(reverse("register_business"), payload)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assert_no_registration(payload)

    def test_password_validation_and_existing_email_protections_are_preserved(self):
        for tier in LOGISTICS_TIER_SLUGS:
            for overrides in ({"password1": "123", "password2": "123"}, {"password2": "different"}):
                payload = self.payload(tier, **overrides)
                response = self.client.post(self.url(tier), payload)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assert_no_registration(payload)
            business = self.register(tier)
            response = self.client.post(
                self.url(tier),
                self.payload(tier, "-duplicate", email=f"{tier.upper()}@example.test"),
            )
            self.assertContains(response, "An account with this email already exists.")
            self.assertEqual(business.memberships.count(), 1)
            self.assertEqual(
                TaskIOUser.objects.filter(email__iexact=f"{tier}@example.test").count(), 1
            )
            self.assertFalse(Business.objects.filter(name=f"Free {tier}-duplicate").exists())

    def test_profile_failure_rolls_back_all_registration_records(self):
        for tier in LOGISTICS_TIER_SLUGS:
            before = tuple(
                model.objects.count()
                for model in (
                    TaskIOUser,
                    Business,
                    BusinessUser,
                    BusinessSubscription,
                    SaaSUserProfile,
                    LogisticsProfile,
                )
            )
            with patch.object(SaaSUserProfile, "save", side_effect=RuntimeError("profile failure")):
                with self.assertRaisesMessage(RuntimeError, "profile failure"):
                    self.client.post(self.url(tier), self.payload(tier))
            self.assertEqual(
                before,
                tuple(
                    model.objects.count()
                    for model in (
                        TaskIOUser,
                        Business,
                        BusinessUser,
                        BusinessSubscription,
                        SaaSUserProfile,
                        LogisticsProfile,
                    )
                ),
            )
            self.assertNotIn(CURRENT_BUSINESS_SESSION_KEY, self.client.session)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_rotation_and_disabling_leave_existing_accounts_unchanged_and_access_has_no_year_limit(
        self,
    ):
        future = timezone.now() + timedelta(days=800)
        for tier in LOGISTICS_TIER_SLUGS:
            business = self.register(tier)
            subscription = business.subscription
            before = BusinessSubscription.objects.values().get(pk=subscription.pk)
            new_token = f"rotated-fixture-{tier}"
            with override_settings(**{FREE_TEST_TOKEN_SETTING_BY_PLAN[tier]: new_token}):
                response = self.client.post(self.url(tier), self.payload(tier, "-old-link"))
                self.assertRedirects(response, reverse("register_business"))
                self.assert_no_registration(self.payload(tier, "-old-link"))
                self.assertEqual(self.client.get(self.url(tier, new_token)).status_code, 200)
            with override_settings(
                FREE_TEST_REGISTRATION_ENABLED=False,
                **{FREE_TEST_TOKEN_SETTING_BY_PLAN[tier]: ""},
            ):
                with patch("django.utils.timezone.now", return_value=future):
                    self.assertTrue(subscription.has_access)
                    self.assertIsNone(subscription.access_ends_at)
                    self.assertTrue(can_use_module(business, "parcels"))
                    self.client.force_login(business.memberships.get().user)
                    response = self.client.get(reverse("agent_dashboard"))
                    self.assertEqual(response.status_code, 200)
                    call_command("reconcile_subscription_access", stdout=StringIO())
            self.assertEqual(before, BusinessSubscription.objects.values().get(pk=subscription.pk))
            business.refresh_from_db()
            self.assertTrue(business.is_active)
            with patch("django.utils.timezone.now", return_value=future):
                self.assertEqual(self.client.get(self.url(tier)).status_code, 200)

    def test_free_test_owner_cannot_change_tier_and_both_portals_remain_unavailable(self):
        for tier in LOGISTICS_TIER_SLUGS:
            business = self.register(tier)
            subscription = business.subscription
            owner = business.memberships.get().user
            other = ClarivoPlan.objects.exclude(slug=tier).get(
                slug="logistics-scale" if tier != "logistics-scale" else "logistics-core"
            )
            response = self.client.post(
                reverse("business_subscription"), {"plan": other.pk}, follow=True
            )
            self.assertContains(response, "Plan changes are unavailable for free-test workspaces")
            subscription.refresh_from_db()
            self.assertEqual(subscription.plan.slug, tier)
            for portal in (
                get_customer_portal_availability,
                get_payment_recovery_portal_availability,
            ):
                availability = portal(business=business, user=owner, subscription=subscription)
                self.assertFalse(availability.can_open)
                self.assertEqual(availability.reason, "logistics_portal_disabled")
