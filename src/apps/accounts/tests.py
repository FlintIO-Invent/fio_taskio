from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.accounts.beta_registration import (
    BETA_PLAN_DISPLAY_NAME,
    BETA_PLAN_SLUG,
)
from apps.businesses.models import (
    Business,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
)
from apps.businesses.plan_catalog import (
    PUBLIC_BILLING_INTERVALS,
    PUBLIC_PAID_PLAN_SLUGS,
    PUBLIC_PRICING_CURRENCIES,
    STANDARD_TRIAL_DAYS,
)
from apps.businesses.stripe_checkout import StripeCheckoutError
from apps.businesses.utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    MULTI_WORKSPACE_EMAIL_MESSAGE,
    can_use_module,
)

from .models import SaaSUserProfile
from .views import handle_successful_paid_plan_registration


class CustomerRegistrationViewTests(TestCase):
    def test_get_redirects_legacy_signup_to_business_registration(self):
        response = self.client.get(reverse("customer_registration"), follow=True)

        self.assertRedirects(response, reverse("register_business"))
        self.assertContains(response, "Standalone customer signup is now legacy.")
        self.assertContains(response, "Register your business")

    def test_post_redirects_legacy_signup_without_creating_account(self):
        response = self.client.post(
            reverse("customer_registration"),
            {
                "email": "owner@example.com",
                "first_name": "Jane",
                "last_name": "Doe",
                "company_name": "Acme Freight",
                "phone": "+1 721 555 0100",
                "address": "Philipsburg, Sint Maarten",
                "date_of_birth": "1990-06-15",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("register_business"))
        self.assertFalse(get_user_model().objects.filter(email="owner@example.com").exists())
        self.assertFalse(SaaSUserProfile.objects.exists())
        self.assertContains(response, "Standalone customer signup is now legacy.")

    def test_post_does_not_process_existing_email_payload(self):
        existing_user = get_user_model().objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Existing",
            last_name="User",
        )

        response = self.client.post(
            reverse("customer_registration"),
            {
                "email": "OWNER@example.com",
                "first_name": "Jane",
                "last_name": "Doe",
                "company_name": "Acme Freight",
                "phone": "+1 721 555 0100",
                "address": "Philipsburg, Sint Maarten",
                "date_of_birth": "1990-06-15",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("register_business"))
        self.assertEqual(
            get_user_model().objects.filter(email__iexact="owner@example.com").count(),
            1,
        )
        self.assertFalse(SaaSUserProfile.objects.filter(user=existing_user).exists())


class BusinessRegistrationViewTests(TestCase):
    BETA_TOKEN = "shared-beta-token-for-tests-1234567890"

    @staticmethod
    def _price_map(
        *,
        missing: set[tuple[str, str, str]] | None = None,
    ) -> dict[tuple[str, str, str], str]:
        missing = missing or set()
        return {
            (plan_slug, interval, currency): f"price_{plan_slug}_{interval}_{currency}"
            for plan_slug in PUBLIC_PAID_PLAN_SLUGS
            for interval in PUBLIC_BILLING_INTERVALS
            for currency in PUBLIC_PRICING_CURRENCIES
            if (plan_slug, interval, currency) not in missing
        }

    def _valid_stripe_settings(self, **overrides):
        settings_overrides = {
            "STRIPE_ENABLED": True,
            "STRIPE_PUBLISHABLE_KEY": "pk_test_motionmate",
            "STRIPE_SECRET_KEY": "sk_test_motionmate",
            "STRIPE_WEBHOOK_SECRET": "whsec_motionmate",
            "STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID": "bpc_test_motionmate",
            "STRIPE_PRICE_ID_MAP": self._price_map(),
        }
        settings_overrides.update(overrides)
        return settings_overrides

    def _registration_payload(
        self,
        *,
        email: str = "owner@example.com",
        business_name: str = "Acme Freight",
        plan: ClarivoPlan | None = None,
        billing_interval: str | None = None,
        country: str = "Sint Maarten",
    ) -> dict[str, str | int]:
        payload: dict[str, str | int] = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": email,
            "business_name": business_name,
            "business_email": f"hello+{business_name.lower().replace(' ', '-')}@motionmate.test",
            "country": country,
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        }
        if plan is not None:
            payload["plan"] = plan.slug
        if billing_interval is not None:
            payload["billing_interval"] = billing_interval
        return payload

    def _beta_url(self, token: str | None = None) -> str:
        return reverse("register_business_beta", args=[token or self.BETA_TOKEN])

    def test_get_renders_business_registration_page(self):
        response = self.client.get(reverse("register_business"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Register your business")
        self.assertContains(response, "Owner login email")
        self.assertContains(response, "Selected plan")
        self.assertContains(
            response,
            "Use the email address you want to sign in with. This will become the workspace owner login for this business.",
        )
        self.assertContains(
            response,
            "Use the public contact or billing email for the business. It can be different from the owner login email.",
        )
        self.assertNotContains(response, BETA_PLAN_DISPLAY_NAME)

    def test_get_defaults_selected_plan_summary_to_recommended_pro(self):
        pro_plan = ClarivoPlan.objects.get(slug="pro")

        response = self.client.get(reverse("register_business"))

        self.assertEqual(response.context["form"]["plan"].value(), pro_plan.slug)
        self.assertEqual(response.context["selected_plan"], pro_plan)
        self.assertContains(response, "Selected plan")
        self.assertContains(response, "Pro")
        self.assertContains(response, "$79 / month after trial")
        self.assertContains(response, f"Your {STANDARD_TRIAL_DAYS}-day free trial")
        self.assertContains(response, "A payment method is required")
        self.assertContains(response, "there is no charge today")
        self.assertContains(response, "renews automatically at $79 per month unless cancelled")
        self.assertContains(response, f'name="plan" value="{pro_plan.slug}"')
        self.assertContains(response, 'name="billing_interval" value="monthly"')

    def test_get_selects_requested_trial_plan_from_pricing_link(self):
        for slug in PUBLIC_PAID_PLAN_SLUGS:
            with self.subTest(plan=slug):
                plan = ClarivoPlan.objects.get(slug=slug)
                display_price = plan.get_display_pricing()["monthly_display"]

                response = self.client.get(f"{reverse('register_business')}?plan={slug}")

                self.assertEqual(response.context["form"]["plan"].value(), plan.slug)
                self.assertEqual(
                    response.context["selected_billing_interval"],
                    "monthly",
                )
                self.assertEqual(response.context["selected_plan"], plan)
                self.assertContains(response, "Selected plan")
                self.assertContains(response, plan.name)
                self.assertContains(response, f"{display_price} / month after trial")
                self.assertContains(
                    response,
                    f"Your {STANDARD_TRIAL_DAYS}-day free trial starts with {plan.name} on monthly billing.",
                )
                self.assertContains(response, f'name="plan" value="{plan.slug}"')
                self.assertContains(response, 'name="billing_interval" value="monthly"')

    def test_get_selects_requested_yearly_interval_from_pricing_link(self):
        business_plan = ClarivoPlan.objects.get(slug="business")
        display_price = business_plan.get_display_pricing()["yearly_display"]

        response = self.client.get(
            f"{reverse('register_business')}?plan=business&interval=yearly",
        )

        self.assertEqual(response.context["form"]["plan"].value(), business_plan.slug)
        self.assertEqual(response.context["selected_plan"], business_plan)
        self.assertEqual(response.context["selected_billing_interval"], "yearly")
        self.assertContains(response, f"{display_price} / year after trial")
        self.assertContains(response, "on yearly billing")
        self.assertContains(response, f'name="plan" value="{business_plan.slug}"')
        self.assertContains(response, 'name="billing_interval" value="yearly"')

    def test_get_ignores_unknown_trial_plan_and_defaults_to_pro(self):
        pro_plan = ClarivoPlan.objects.get(slug="pro")

        response = self.client.get(f"{reverse('register_business')}?plan=enterprise")

        self.assertEqual(response.context["form"]["plan"].value(), pro_plan.slug)
        self.assertEqual(response.context["selected_plan"], pro_plan)
        self.assertContains(response, f'name="plan" value="{pro_plan.slug}"')

    def test_public_registration_plan_queryset_excludes_beta(self):
        response = self.client.get(f"{reverse('register_business')}?plan=beta")

        plan_slugs = list(
            response.context["form"].fields["plan"].queryset.values_list("slug", flat=True)
        )

        self.assertEqual(plan_slugs, list(PUBLIC_PAID_PLAN_SLUGS))
        self.assertNotIn(BETA_PLAN_SLUG, plan_slugs)
        self.assertEqual(
            response.context["form"]["plan"].value(),
            ClarivoPlan.objects.get(slug="pro").slug,
        )
        self.assertEqual(response.context["selected_plan"].slug, "pro")
        self.assertNotContains(response, BETA_PLAN_DISPLAY_NAME)

    def test_inactive_public_plan_query_defaults_to_pro(self):
        ClarivoPlan.objects.filter(slug="starter").update(is_active=False)
        pro_plan = ClarivoPlan.objects.get(slug="pro")

        response = self.client.get(f"{reverse('register_business')}?plan=starter")

        self.assertEqual(response.context["form"]["plan"].value(), pro_plan.slug)
        self.assertEqual(response.context["selected_plan"], pro_plan)
        self.assertContains(response, f'name="plan" value="{pro_plan.slug}"')

    def test_public_registration_rejects_manual_beta_plan_post(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)

        response = self.client.post(
            reverse("register_business"),
            self._registration_payload(
                email="manual-beta@example.com",
                business_name="Manual Beta Workspace",
                plan=beta_plan,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(get_user_model().objects.filter(email="manual-beta@example.com").exists())
        self.assertFalse(Business.objects.filter(name="Manual Beta Workspace").exists())

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_valid_shared_beta_link_displays_beta_plan(self):
        response = self.client.get(self._beta_url())

        plan_slugs = list(
            response.context["form"].fields["plan"].queryset.values_list("slug", flat=True)
        )

        self.assertEqual(plan_slugs, [*PUBLIC_PAID_PLAN_SLUGS, BETA_PLAN_SLUG])
        self.assertContains(response, BETA_PLAN_DISPLAY_NAME)

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_wrong_and_modified_beta_tokens_redirect_without_beta_plan(self):
        for token in ("wrong-token", f"{self.BETA_TOKEN}-modified"):
            with self.subTest(token=token):
                response = self.client.get(
                    self._beta_url(token),
                    follow=True,
                )

                self.assertRedirects(response, reverse("register_business"))
                self.assertContains(response, "Beta registration is currently unavailable.")
                self.assertNotContains(response, BETA_PLAN_DISPLAY_NAME)

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_wrong_beta_token_does_not_assign_beta_plan(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)

        response = self.client.post(
            self._beta_url("wrong-token"),
            self._registration_payload(
                email="wrong-token@example.com",
                business_name="Wrong Token Workspace",
                plan=beta_plan,
            ),
            follow=True,
        )

        self.assertRedirects(response, reverse("register_business"))
        self.assertContains(response, "Beta registration is currently unavailable.")
        self.assertFalse(get_user_model().objects.filter(email="wrong-token@example.com").exists())
        self.assertFalse(Business.objects.filter(name="Wrong Token Workspace").exists())

    @override_settings(BETA_REGISTRATION_ENABLED=False, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_disabled_beta_registration_link_redirects_without_beta_plan(self):
        response = self.client.get(self._beta_url(), follow=True)

        self.assertRedirects(response, reverse("register_business"))
        self.assertContains(response, "Beta registration is currently unavailable.")
        self.assertNotContains(response, BETA_PLAN_DISPLAY_NAME)

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN="")
    def test_missing_configured_beta_token_redirects_without_beta_plan(self):
        response = self.client.get(self._beta_url(), follow=True)

        self.assertRedirects(response, reverse("register_business"))
        self.assertContains(response, "Beta registration is currently unavailable.")
        self.assertNotContains(response, BETA_PLAN_DISPLAY_NAME)

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_inactive_beta_plan_blocks_shared_link(self):
        ClarivoPlan.objects.filter(slug=BETA_PLAN_SLUG).update(is_active=False)

        response = self.client.get(self._beta_url(), follow=True)

        self.assertRedirects(response, reverse("register_business"))
        self.assertContains(response, "Beta registration is currently unavailable.")
        self.assertNotContains(response, BETA_PLAN_DISPLAY_NAME)

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_beta_route_rejects_other_internal_plan_post(self):
        internal_plan = ClarivoPlan.objects.create(
            name="Internal VIP",
            slug="internal-vip",
            is_active=True,
            allow_invoicing=True,
            allow_appointments=True,
            allow_public_booking=True,
        )

        response = self.client.post(
            self._beta_url(),
            self._registration_payload(
                email="internal-vip@example.com",
                business_name="Internal VIP Workspace",
                plan=internal_plan,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(get_user_model().objects.filter(email="internal-vip@example.com").exists())
        self.assertFalse(Business.objects.filter(name="Internal VIP Workspace").exists())

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_valid_beta_registration_creates_active_subscription_without_trial(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)

        response = self.client.post(
            self._beta_url(),
            self._registration_payload(
                email="beta-owner@example.com",
                business_name="Beta Workspace",
                plan=beta_plan,
            ),
            follow=True,
        )

        business = Business.objects.get(name="Beta Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertEqual(subscription.plan.slug, BETA_PLAN_SLUG)
        self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertIsNone(subscription.trial_start)
        self.assertIsNone(subscription.trial_end)
        self.assertIsNone(subscription.current_period_start)
        self.assertIsNone(subscription.current_period_end)
        self.assertContains(response, "Beta early access")
        self.assertEqual(int(self.client.session[CURRENT_BUSINESS_SESSION_KEY]), business.id)
        self.assertTrue(can_use_module(business, "appointments"))
        self.assertTrue(can_use_module(business, "public_booking"))

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_beta_registration_does_not_use_paid_plan_handoff(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)

        with mock.patch("apps.accounts.views.handle_successful_paid_plan_registration") as handoff:
            response = self.client.post(
                self._beta_url(),
                self._registration_payload(
                    email="beta-handoff@example.com",
                    business_name="Beta Handoff Workspace",
                    plan=beta_plan,
                ),
                follow=True,
            )

        business = Business.objects.get(name="Beta Handoff Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        handoff.assert_not_called()
        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertEqual(subscription.plan.slug, BETA_PLAN_SLUG)
        self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertIsNone(subscription.trial_end)

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_beta_registration_does_not_start_checkout_when_stripe_enabled(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch("apps.accounts.views.create_trial_checkout_session") as create_checkout:
                response = self.client.post(
                    self._beta_url(),
                    self._registration_payload(
                        email="stripe-beta-owner@example.com",
                        business_name="Stripe Beta Workspace",
                        plan=beta_plan,
                        billing_interval="yearly",
                    ),
                    follow=True,
                )

        business = Business.objects.get(name="Stripe Beta Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        self.assertRedirects(response, reverse("agent_dashboard"))
        create_checkout.assert_not_called()
        self.assertEqual(subscription.plan.slug, BETA_PLAN_SLUG)
        self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
        self.assertEqual(subscription.payment_provider, "")
        self.assertEqual(subscription.billing_interval, "")
        self.assertEqual(subscription.provider_checkout_session_id, "")
        self.assertTrue(subscription.has_access)

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_same_beta_link_can_register_more_than_one_business(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)

        for index in (1, 2):
            with self.subTest(index=index):
                response = self.client.post(
                    self._beta_url(),
                    self._registration_payload(
                        email=f"beta-owner-{index}@example.com",
                        business_name=f"Reusable Beta Workspace {index}",
                        plan=beta_plan,
                    ),
                    follow=True,
                )
                business = Business.objects.get(name=f"Reusable Beta Workspace {index}")
                subscription = BusinessSubscription.objects.get(business=business)

                self.assertRedirects(response, reverse("agent_dashboard"))
                self.assertEqual(subscription.plan.slug, BETA_PLAN_SLUG)
                self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
                self.assertIsNone(subscription.trial_end)
                self.client.logout()

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_beta_link_does_not_expire_because_time_passes(self):
        future = timezone.now() + timedelta(days=3650)

        with mock.patch("django.utils.timezone.now", return_value=future):
            response = self.client.get(self._beta_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, BETA_PLAN_DISPLAY_NAME)

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN="new-beta-token")
    def test_rotating_beta_token_invalidates_old_link_and_validates_new_link(self):
        old_response = self.client.get(self._beta_url(), follow=True)
        new_response = self.client.get(self._beta_url("new-beta-token"))

        self.assertRedirects(old_response, reverse("register_business"))
        self.assertContains(old_response, "Beta registration is currently unavailable.")
        self.assertNotContains(old_response, BETA_PLAN_DISPLAY_NAME)
        self.assertEqual(new_response.status_code, 200)
        self.assertContains(new_response, BETA_PLAN_DISPLAY_NAME)

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_disabling_or_rotating_beta_link_does_not_modify_existing_beta_account(self):
        beta_plan = ClarivoPlan.objects.get(slug=BETA_PLAN_SLUG)
        self.client.post(
            self._beta_url(),
            self._registration_payload(
                email="stable-beta-owner@example.com",
                business_name="Stable Beta Workspace",
                plan=beta_plan,
            ),
            follow=True,
        )
        business = Business.objects.get(name="Stable Beta Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        for enabled, token in ((False, self.BETA_TOKEN), (True, "rotated-beta-token")):
            with self.subTest(enabled=enabled, token=token):
                with override_settings(
                    BETA_REGISTRATION_ENABLED=enabled,
                    BETA_REGISTRATION_TOKEN=token,
                ):
                    self.client.get(self._beta_url(), follow=True)
                business.refresh_from_db()
                subscription.refresh_from_db()

                self.assertTrue(business.is_active)
                self.assertEqual(subscription.plan.slug, BETA_PLAN_SLUG)
                self.assertEqual(subscription.status, BusinessSubscription.Status.ACTIVE)
                self.assertTrue(can_use_module(business, "appointments"))

    def test_selected_public_pricing_plan_is_preserved_through_trial_signup(self):
        pro_client_limit = ClarivoPlan.objects.get(slug="pro").max_clients

        for slug in PUBLIC_PAID_PLAN_SLUGS:
            with self.subTest(plan=slug):
                plan = ClarivoPlan.objects.get(slug=slug)
                get_response = self.client.get(f"{reverse('register_business')}?plan={slug}")

                self.assertEqual(get_response.context["form"]["plan"].value(), plan.slug)

                response = self.client.post(
                    reverse("register_business"),
                    self._registration_payload(
                        email=f"{slug}-owner@example.com",
                        business_name=f"{slug.title()} Trial Workspace",
                        plan=plan,
                    ),
                    follow=True,
                )
                business = Business.objects.get(name=f"{slug.title()} Trial Workspace")
                subscription = BusinessSubscription.objects.get(business=business)

                self.assertRedirects(response, reverse("agent_dashboard"))
                self.assertEqual(subscription.plan_id, plan.pk)
                self.assertEqual(subscription.plan.slug, slug)
                self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
                self.assertEqual(
                    subscription.trial_end - subscription.trial_start,
                    timedelta(days=STANDARD_TRIAL_DAYS),
                )
                self.assertEqual(subscription.plan.max_clients, plan.max_clients)
                if slug != "pro":
                    self.assertNotEqual(subscription.plan.max_clients, pro_client_limit)
                self.client.logout()

    def test_validation_errors_preserve_selected_public_plan_summary(self):
        business_plan = ClarivoPlan.objects.get(slug="business")
        payload = self._registration_payload(
            email="bad-password@example.com",
            business_name="Bad Password Workspace",
            plan=business_plan,
        )
        payload["password2"] = "DifferentStrongPass123!"

        response = self.client.post(reverse("register_business"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match.")
        self.assertEqual(response.context["selected_plan"], business_plan)
        self.assertContains(response, "Business")
        self.assertContains(response, f'name="plan" value="{business_plan.slug}"')
        self.assertFalse(get_user_model().objects.filter(email="bad-password@example.com").exists())
        self.assertFalse(Business.objects.filter(name="Bad Password Workspace").exists())

    def test_public_registration_rejects_unknown_submitted_plan_slug(self):
        response = self.client.post(
            reverse("register_business"),
            {
                **self._registration_payload(
                    email="unknown-plan@example.com",
                    business_name="Unknown Plan Workspace",
                ),
                "plan": "enterprise",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(get_user_model().objects.filter(email="unknown-plan@example.com").exists())
        self.assertFalse(Business.objects.filter(name="Unknown Plan Workspace").exists())

    def test_public_registration_rejects_unknown_submitted_billing_interval(self):
        pro_plan = ClarivoPlan.objects.get(slug="pro")

        response = self.client.post(
            reverse("register_business"),
            self._registration_payload(
                email="unknown-interval@example.com",
                business_name="Unknown Interval Workspace",
                plan=pro_plan,
                billing_interval="weekly",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(
            get_user_model().objects.filter(email="unknown-interval@example.com").exists()
        )
        self.assertFalse(Business.objects.filter(name="Unknown Interval Workspace").exists())

    def test_public_registration_rejects_inactive_submitted_plan_slug(self):
        ClarivoPlan.objects.filter(slug="starter").update(is_active=False)

        response = self.client.post(
            reverse("register_business"),
            {
                **self._registration_payload(
                    email="inactive-plan@example.com",
                    business_name="Inactive Plan Workspace",
                ),
                "plan": "starter",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(
            get_user_model().objects.filter(email="inactive-plan@example.com").exists()
        )
        self.assertFalse(Business.objects.filter(name="Inactive Plan Workspace").exists())

    def test_default_trial_fallback_cannot_select_beta_when_public_plans_are_inactive(self):
        ClarivoPlan.objects.filter(slug__in=ClarivoPlan.MOTIONMATE_PLAN_SLUGS).update(
            is_active=False,
        )
        ClarivoPlan.objects.filter(slug=BETA_PLAN_SLUG).update(is_active=True)

        response = self.client.post(
            reverse("register_business"),
            self._registration_payload(
                email="fallback-beta@example.com",
                business_name="Fallback Beta Workspace",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select Starter, Pro, or Business from pricing")
        self.assertFalse(
            get_user_model().objects.filter(email="fallback-beta@example.com").exists()
        )
        self.assertFalse(Business.objects.filter(name="Fallback Beta Workspace").exists())

    @override_settings(BETA_REGISTRATION_ENABLED=True, BETA_REGISTRATION_TOKEN=BETA_TOKEN)
    def test_management_command_prints_configured_token_accepted_by_beta_route(self):
        output = StringIO()

        call_command(
            "beta_registration_link",
            "--base-url",
            "https://www.motionmate.net",
            stdout=output,
        )

        path = urlparse(output.getvalue().strip()).path
        response = self.client.get(path)

        self.assertEqual(
            output.getvalue().strip(),
            f"https://www.motionmate.net{self._beta_url()}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, BETA_PLAN_DISPLAY_NAME)

    @override_settings(BETA_REGISTRATION_TOKEN="")
    def test_management_command_reports_configuration_error_without_token(self):
        with self.assertRaisesMessage(CommandError, "BETA_REGISTRATION_TOKEN is not configured."):
            call_command("beta_registration_link", stdout=StringIO())

    def test_post_creates_user_business_membership_trial_subscription_and_logs_in(self):
        pro_plan = ClarivoPlan.objects.get(slug="pro")

        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "owner@example.com",
                "business_name": "Acme Freight",
                "business_email": "hello@acmefreight.com",
                "country": "Sint Maarten",
                "plan": pro_plan.slug,
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            follow=True,
        )

        user = get_user_model().objects.get(email="owner@example.com")
        business = Business.objects.get(name="Acme Freight")
        membership = BusinessUser.objects.get(user=user, business=business)
        subscription = BusinessSubscription.objects.get(business=business)
        profile = SaaSUserProfile.objects.get(user=user)

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertEqual(user.company_name, "Acme Freight")
        self.assertEqual(business.email, "hello@acmefreight.com")
        self.assertEqual(business.country, "Sint Maarten")
        self.assertEqual(membership.role, BusinessUser.Role.OWNER)
        self.assertEqual(subscription.plan.slug, "pro")
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertIsNotNone(subscription.trial_start)
        self.assertIsNotNone(subscription.trial_end)
        self.assertEqual(
            subscription.trial_end - subscription.trial_start,
            timedelta(days=STANDARD_TRIAL_DAYS),
        )
        self.assertLessEqual(subscription.trial_start, timezone.now())
        self.assertEqual(profile.workspace_name, "Acme Freight")
        self.assertEqual(profile.billing_email, "hello@acmefreight.com")
        self.assertEqual(int(self.client.session[CURRENT_BUSINESS_SESSION_KEY]), business.id)
        self.assertContains(response, f"{STANDARD_TRIAL_DAYS}-day trial")
        self.assertContains(response, "Welcome to Motionmate")
        self.assertTrue(response.context["onboarding_status"]["should_auto_show_welcome"])

    def test_public_registration_rejects_missing_submitted_plan_slug(self):
        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "missing-plan@example.com",
                "business_name": "Missing Plan Workspace",
                "business_email": "hello@missing-plan.test",
                "country": "Sint Maarten",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select Starter, Pro, or Business from pricing")
        self.assertFalse(get_user_model().objects.filter(email="missing-plan@example.com").exists())
        self.assertFalse(Business.objects.filter(name="Missing Plan Workspace").exists())

    def test_post_creates_trial_subscription_for_selected_plan(self):
        starter_plan = ClarivoPlan.objects.get(slug="starter")

        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "starter-owner@example.com",
                "business_name": "Starter Workspace",
                "business_email": "hello@starter.test",
                "country": "Sint Maarten",
                "plan": starter_plan.slug,
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            follow=True,
        )

        business = Business.objects.get(name="Starter Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertEqual(subscription.plan.slug, "starter")
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(
            subscription.trial_end - subscription.trial_start,
            timedelta(days=STANDARD_TRIAL_DAYS),
        )

    @override_settings(STRIPE_ENABLED=False)
    def test_stripe_disabled_registration_does_not_call_checkout_service(self):
        starter_plan = ClarivoPlan.objects.get(slug="starter")

        with mock.patch("apps.accounts.views.create_trial_checkout_session") as create_checkout:
            response = self.client.post(
                reverse("register_business"),
                self._registration_payload(
                    email="disabled-checkout@example.com",
                    business_name="Disabled Checkout Workspace",
                    plan=starter_plan,
                    billing_interval="yearly",
                ),
                follow=True,
            )

        business = Business.objects.get(name="Disabled Checkout Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        self.assertRedirects(response, reverse("agent_dashboard"))
        create_checkout.assert_not_called()
        self.assertEqual(subscription.plan, starter_plan)
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(subscription.payment_provider, "")
        self.assertEqual(subscription.billing_interval, "")
        self.assertEqual(subscription.billing_currency, "")
        self.assertContains(response, f"{STANDARD_TRIAL_DAYS}-day trial")

    def test_stripe_enabled_registration_creates_pending_subscription_and_redirects_to_checkout(
        self,
    ):
        starter_plan = ClarivoPlan.objects.get(slug="starter")

        def fake_checkout(*, request, subscription, user):
            subscription.provider_price_id = "price_starter_yearly_eur"
            subscription.provider_checkout_session_id = "cs_test_registration"
            subscription.checkout_session_expires_at = timezone.now() + timedelta(hours=1)
            subscription.save(
                update_fields=[
                    "provider_price_id",
                    "provider_checkout_session_id",
                    "checkout_session_expires_at",
                    "updated_at",
                ]
            )
            return "https://checkout.stripe.test/registration"

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch(
                "apps.accounts.views.create_trial_checkout_session",
                side_effect=fake_checkout,
            ) as create_checkout:
                response = self.client.post(
                    reverse("register_business"),
                    self._registration_payload(
                        email="stripe-enabled@example.com",
                        business_name="Stripe Enabled Workspace",
                        plan=starter_plan,
                        billing_interval="yearly",
                        country="Netherlands",
                    ),
                )

        user = get_user_model().objects.get(email="stripe-enabled@example.com")
        business = Business.objects.get(name="Stripe Enabled Workspace")
        membership = BusinessUser.objects.get(user=user, business=business)
        subscription = BusinessSubscription.objects.get(business=business)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://checkout.stripe.test/registration")
        self.assertEqual(membership.role, BusinessUser.Role.OWNER)
        self.assertEqual(int(self.client.session[CURRENT_BUSINESS_SESSION_KEY]), business.pk)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(user.pk))
        self.assertEqual(subscription.plan, starter_plan)
        self.assertEqual(subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertEqual(subscription.payment_provider, BusinessSubscription.PaymentProvider.STRIPE)
        self.assertEqual(subscription.billing_interval, BusinessSubscription.BillingInterval.YEARLY)
        self.assertEqual(subscription.billing_currency, BusinessSubscription.BillingCurrency.EUR)
        self.assertEqual(subscription.provider_price_id, "price_starter_yearly_eur")
        self.assertEqual(subscription.provider_checkout_session_id, "cs_test_registration")
        self.assertFalse(subscription.has_access)
        self.assertIsNone(subscription.trial_start)
        self.assertIsNone(subscription.trial_end)
        self.assertEqual(create_checkout.call_args.kwargs["subscription"], subscription)
        self.assertEqual(create_checkout.call_args.kwargs["user"], user)

    def test_stripe_enabled_checkout_failure_keeps_pending_subscription_for_resume(self):
        pro_plan = ClarivoPlan.objects.get(slug="pro")

        with override_settings(**self._valid_stripe_settings()):
            with mock.patch(
                "apps.accounts.views.create_trial_checkout_session",
                side_effect=StripeCheckoutError("Checkout unavailable"),
            ):
                response = self.client.post(
                    reverse("register_business"),
                    self._registration_payload(
                        email="stripe-failure@example.com",
                        business_name="Stripe Failure Workspace",
                        plan=pro_plan,
                    ),
                    follow=True,
                )

        business = Business.objects.get(name="Stripe Failure Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        self.assertRedirects(response, reverse("billing_checkout_cancelled"))
        self.assertContains(response, "secure payment setup could not be started")
        self.assertContains(response, "No payment was taken")
        self.assertEqual(subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertFalse(subscription.has_access)
        self.assertIsNone(subscription.trial_start)
        self.assertEqual(subscription.plan, pro_plan)

    def test_stripe_enabled_missing_price_id_keeps_pending_without_network_call(self):
        starter_plan = ClarivoPlan.objects.get(slug="starter")

        with override_settings(
            **self._valid_stripe_settings(
                STRIPE_PRICE_ID_MAP=self._price_map(missing={("starter", "monthly", "usd")}),
            )
        ):
            with mock.patch(
                "apps.businesses.stripe_checkout.configure_stripe_sdk",
            ) as configure_stripe:
                response = self.client.post(
                    reverse("register_business"),
                    self._registration_payload(
                        email="missing-price@example.com",
                        business_name="Missing Price Workspace",
                        plan=starter_plan,
                        billing_interval="monthly",
                    ),
                    follow=True,
                )

        business = Business.objects.get(name="Missing Price Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        self.assertRedirects(response, reverse("billing_checkout_cancelled"))
        configure_stripe.assert_not_called()
        self.assertEqual(subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertEqual(subscription.provider_price_id, "")
        self.assertEqual(subscription.provider_checkout_session_id, "")
        self.assertFalse(subscription.has_access)

    def test_home_pricing_links_pass_selected_trial_plan_to_registration(self):
        response = self.client.get(reverse("home"))

        self.assertContains(
            response,
            f"{reverse('register_business')}?plan=starter&amp;interval=monthly",
        )
        self.assertContains(
            response,
            f"{reverse('register_business')}?plan=pro&amp;interval=monthly",
        )
        self.assertContains(
            response,
            f"{reverse('register_business')}?plan=business&amp;interval=monthly",
        )
        self.assertContains(response, "data-yearly-registration-url")
        self.assertContains(response, "interval=yearly")
        self.assertNotContains(response, BETA_PLAN_DISPLAY_NAME)

    def test_post_generates_unique_slug_for_duplicate_business_names(self):
        pro_plan = ClarivoPlan.objects.get(slug="pro")
        existing_owner = get_user_model().objects.create_user(
            email="existing@example.com",
            password="StrongPass123!",
            first_name="Existing",
            last_name="Owner",
        )
        existing_business = Business.objects.create(
            name="Acme Freight",
            slug="acme-freight",
            email="existing@acmefreight.com",
            country="Sint Maarten",
        )
        BusinessUser.objects.create(
            user=existing_owner,
            business=existing_business,
            role=BusinessUser.Role.OWNER,
        )

        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "new-owner@example.com",
                "business_name": "Acme Freight",
                "business_email": "hello@acmefreight.com",
                "country": "Sint Maarten",
                "plan": pro_plan.slug,
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Business.objects.filter(slug="acme-freight-2").exists())

    def test_post_uses_selected_active_plan_when_pro_is_unavailable(self):
        ClarivoPlan.objects.filter(slug="pro").update(is_active=False)
        starter_plan = ClarivoPlan.objects.get(slug="starter")

        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "starter-owner@example.com",
                "business_name": "Starter Workspace",
                "business_email": "hello@starter.test",
                "country": "Sint Maarten",
                "plan": starter_plan.slug,
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            follow=True,
        )

        business = Business.objects.get(name="Starter Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertEqual(subscription.plan.slug, "starter")
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)

    def test_post_rejects_registration_when_no_active_public_plan_is_selected(self):
        ClarivoPlan.objects.update(is_active=False)

        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "no-plan-owner@example.com",
                "business_name": "No Plan Workspace",
                "business_email": "hello@noplans.test",
                "country": "Sint Maarten",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select Starter, Pro, or Business from pricing")
        self.assertFalse(
            get_user_model().objects.filter(email="no-plan-owner@example.com").exists()
        )
        self.assertFalse(Business.objects.filter(name="No Plan Workspace").exists())


class PaidPlanRegistrationHandoffTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(
            email="handoff-owner@example.com",
            password="StrongPass123!",
        )
        self.business = Business.objects.create(
            name="Handoff Workspace",
            slug="handoff-workspace",
        )
        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        self.plan = ClarivoPlan.objects.get(slug="pro")

    def _request(self):
        request = self.factory.post(reverse("register_business"))
        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)
        return request

    def test_handoff_creates_trial_subscription_logs_in_and_redirects(self):
        request = self._request()

        response = handle_successful_paid_plan_registration(
            request,
            user=self.user,
            business=self.business,
            selected_plan=self.plan,
        )

        subscription = BusinessSubscription.objects.get(business=self.business)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("agent_dashboard"))
        self.assertEqual(subscription.plan, self.plan)
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertEqual(
            subscription.trial_end - subscription.trial_start,
            timedelta(days=STANDARD_TRIAL_DAYS),
        )
        self.assertEqual(request.session.get("_auth_user_id"), str(self.user.pk))
        self.assertEqual(int(request.session[CURRENT_BUSINESS_SESSION_KEY]), self.business.id)

    def test_handoff_does_not_create_duplicate_subscription(self):
        existing_subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.TRIALING,
            trial_start=timezone.now(),
            trial_end=timezone.now() + timedelta(days=STANDARD_TRIAL_DAYS),
        )
        request = self._request()

        response = handle_successful_paid_plan_registration(
            request,
            user=self.user,
            business=self.business,
            selected_plan=self.plan,
            subscription=existing_subscription,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(BusinessSubscription.objects.filter(business=self.business).count(), 1)
        self.assertEqual(
            BusinessSubscription.objects.get(business=self.business), existing_subscription
        )


class BusinessLoginViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Jane",
            last_name="Doe",
        )
        self.business = Business.objects.create(
            name="Acme Freight",
            slug="acme-freight",
            email="hello@acmefreight.com",
            country="Sint Maarten",
        )
        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )

    def test_get_renders_business_login_page(self):
        response = self.client.get(reverse("business_login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in to your workspace")
        self.assertContains(response, "Forgot password?")
        self.assertContains(response, reverse("password_reset"))

    def test_post_logs_in_business_user_and_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("business_login"),
            {
                "email": "owner@example.com",
                "password": "StrongPass123!",
            },
        )

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertEqual(int(self.client.session[CURRENT_BUSINESS_SESSION_KEY]), self.business.id)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.user.id))

    def test_post_rejects_user_without_active_business_membership(self):
        user_without_workspace = get_user_model().objects.create_user(
            email="orphan@example.com",
            password="StrongPass123!",
            first_name="Orphan",
            last_name="User",
        )

        response = self.client.post(
            reverse("business_login"),
            {
                "email": user_without_workspace.email,
                "password": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not have an active Motionmate workspace yet")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_agent_login_remains_staff_only_for_business_owners(self):
        response = self.client.post(
            reverse("agent_login"),
            {
                "email": "owner@example.com",
                "password": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not authorized to access this portal")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_signs_out_and_redirects_to_business_login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()

        response = self.client.get(reverse("logout"), follow=True)

        self.assertRedirects(response, reverse("business_login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "You have been signed out.")


class PasswordManagementViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Jane",
            last_name="Doe",
        )

    def test_password_reset_route_loads(self):
        response = self.client.get(reverse("password_reset"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reset your password")
        self.assertContains(response, "Motionmate")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@motionmate.test",
        MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net/",
    )
    def test_password_reset_form_sends_motionmate_branded_email(self):
        if hasattr(mail, "outbox"):
            mail.outbox.clear()

        response = self.client.post(
            reverse("password_reset"),
            {"email": self.user.email},
        )

        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        rendered_message = message.body + "\n".join(
            alternative[0] for alternative in message.alternatives
        )
        self.assertEqual(message.subject, "MotionMate password reset")
        self.assertIn("MotionMate workspace login", message.body)
        self.assertIn("MotionMate", message.body)
        self.assertIn("https://www.motionmate.net/accounts/password-reset/", message.body)
        self.assertNotIn("testserver", message.body)
        self.assertNotIn("StrongPass123!", rendered_message)

    def test_password_reset_confirm_page_loads_for_valid_token(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        response = self.client.get(
            reverse("password_reset_confirm", kwargs={"uidb64": uidb64, "token": token}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose a new password")
        self.assertContains(response, "Motionmate workspace login")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@motionmate.test",
        MOTIONMATE_SUPPORT_EMAIL="support@motionmate.test",
    )
    def test_password_reset_completion_sends_security_confirmation_email(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        reset_password = "ResetStrongPass123!"
        confirm_url = reverse(
            "password_reset_confirm",
            kwargs={"uidb64": uidb64, "token": token},
        )
        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 302)
        set_password_url = response["Location"]
        if hasattr(mail, "outbox"):
            mail.outbox.clear()

        response = self.client.post(
            set_password_url,
            {
                "new_password1": reset_password,
                "new_password2": reset_password,
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        rendered_message = message.body + "\n".join(
            alternative[0] for alternative in message.alternatives
        )
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertTrue(self.user.check_password(reset_password))
        self.assertEqual(message.subject, "Your MotionMate password was reset")
        self.assertEqual(message.to, [self.user.email])
        self.assertIn(
            "If you did not reset your password, please contact support immediately",
            message.body,
        )
        self.assertIn("support@motionmate.test", message.body)
        self.assertTrue(any(alternative[1] == "text/html" for alternative in message.alternatives))
        self.assertNotIn(reset_password, rendered_message)
        self.assertNotIn(token, rendered_message)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_reset_completion_still_succeeds_if_confirmation_email_fails_safely(self):
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        reset_password = "ResetStrongPass123!"
        confirm_url = reverse(
            "password_reset_confirm",
            kwargs={"uidb64": uidb64, "token": token},
        )
        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 302)
        set_password_url = response["Location"]

        with self.assertLogs("apps.notifications.emails", level="ERROR") as captured:
            with mock.patch(
                "apps.notifications.emails.EmailMultiAlternatives.send",
                side_effect=RuntimeError("SMTP unavailable password=secret-token"),
            ):
                response = self.client.post(
                    set_password_url,
                    {
                        "new_password1": reset_password,
                        "new_password2": reset_password,
                    },
                    follow=True,
                )

        self.user.refresh_from_db()
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertTrue(self.user.check_password(reset_password))
        log_output = "\n".join(captured.output)
        self.assertIn("Failed to send password reset confirmation email notification.", log_output)
        self.assertNotIn("SMTP unavailable", log_output)
        self.assertNotIn("secret-token", log_output)

    def test_password_change_route_requires_login(self):
        response = self.client.get(reverse("password_change"))

        self.assertRedirects(
            response,
            f"{reverse('business_login')}?next={reverse('password_change')}",
        )

    def test_logged_in_user_can_access_password_change_page(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("password_change"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Change Password")
        self.assertContains(response, "Update the password for your Motionmate account.")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@motionmate.test",
        MOTIONMATE_SUPPORT_EMAIL="support@motionmate.test",
    )
    def test_logged_in_user_can_change_password(self):
        self.client.force_login(self.user)
        old_password = "StrongPass123!"
        new_password = "NewStrongPass123!"
        if hasattr(mail, "outbox"):
            mail.outbox.clear()

        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": old_password,
                "new_password1": new_password,
                "new_password2": new_password,
            },
            follow=True,
        )

        self.user.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        rendered_message = message.body + "\n".join(
            alternative[0] for alternative in message.alternatives
        )
        self.assertRedirects(response, reverse("password_change_done"))
        self.assertTrue(self.user.check_password(new_password))
        self.assertContains(response, "Your password was changed successfully.")
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.user.pk))
        self.assertEqual(message.subject, "Your MotionMate password was changed")
        self.assertEqual(message.to, [self.user.email])
        self.assertIn(
            "If you did not make this change, please contact support immediately",
            message.body,
        )
        self.assertIn("support@motionmate.test", message.body)
        self.assertTrue(any(alternative[1] == "text/html" for alternative in message.alternatives))
        self.assertNotIn(old_password, rendered_message)
        self.assertNotIn(new_password, rendered_message)
        self.assertNotIn("token", rendered_message.lower())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_password_change_still_succeeds_if_confirmation_email_fails_safely(self):
        self.client.force_login(self.user)
        new_password = "NewStrongPass123!"

        with self.assertLogs("apps.notifications.emails", level="ERROR") as captured:
            with mock.patch(
                "apps.notifications.emails.EmailMultiAlternatives.send",
                side_effect=RuntimeError("SMTP unavailable password=secret-token"),
            ):
                response = self.client.post(
                    reverse("password_change"),
                    {
                        "old_password": "StrongPass123!",
                        "new_password1": new_password,
                        "new_password2": new_password,
                    },
                    follow=True,
                )

        self.user.refresh_from_db()
        self.assertRedirects(response, reverse("password_change_done"))
        self.assertTrue(self.user.check_password(new_password))
        self.assertContains(response, "Your password was changed successfully.")
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.user.pk))
        log_output = "\n".join(captured.output)
        self.assertIn("Failed to send password change confirmation email notification.", log_output)
        self.assertNotIn("SMTP unavailable", log_output)
        self.assertNotIn("secret-token", log_output)


class OnboardingScopeGuardTests(TestCase):
    def test_no_interactive_guided_tour_model_or_migration_was_added(self):
        model_names = {model.__name__.lower() for model in apps.get_models()}
        forbidden_models = {
            "guidedtour",
            "guidedtourprogress",
            "producttour",
            "producttourstep",
            "tourcompletion",
            "tourprogress",
        }
        self.assertFalse(model_names & forbidden_models)

        apps_dir = Path(__file__).resolve().parents[1]
        migration_names = {
            path.name.lower()
            for path in apps_dir.glob("*/migrations/*.py")
            if path.name != "__init__.py"
        }
        forbidden_terms = ("guided_tour", "product_tour", "tour_progress", "tourcompletion")
        self.assertFalse(
            [
                migration_name
                for migration_name in migration_names
                if any(term in migration_name for term in forbidden_terms)
            ]
        )

    def test_no_memberships_stripe_saas_billing_or_customer_portal_was_added(self):
        app_labels = {app_config.label for app_config in apps.get_app_configs()}
        self.assertFalse(
            app_labels & {"memberships", "payments", "stripe", "customer_portal", "saas_billing"}
        )

        model_names = {model.__name__.lower() for model in apps.get_models()}
        forbidden_models = {
            "customerportal",
            "membership",
            "payment",
            "saasbillingaccount",
            "stripecheckoutsession",
            "stripecustomer",
            "stripesubscription",
        }
        self.assertFalse(model_names & forbidden_models)

        apps_dir = Path(__file__).resolve().parents[1]
        migration_names = {
            path.name.lower()
            for path in apps_dir.glob("*/migrations/*.py")
            if path.name != "__init__.py"
        }
        forbidden_terms = ("customer_portal", "membership", "payment", "saas_billing", "stripe")
        self.assertFalse(
            [
                migration_name
                for migration_name in migration_names
                if any(term in migration_name for term in forbidden_terms)
            ]
        )


class BusinessInvitationAcceptanceTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Owner",
            last_name="User",
        )
        self.business = Business.objects.create(
            name="Acme Freight",
            slug="acme-freight-team",
            email="hello@acmefreight.com",
            country="Sint Maarten",
        )
        BusinessUser.objects.create(
            user=self.owner,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        invitation_access_plan = ClarivoPlan.objects.create(
            name="Invitation Access",
            slug="invitation-access-plan",
        )
        BusinessSubscription.objects.create(
            business=self.business,
            plan=invitation_access_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

    def test_accept_invitation_creates_employee_account_and_membership(self):
        invitation = BusinessInvitation.objects.create(
            business=self.business,
            email="employee@example.com",
            role=BusinessUser.Role.STAFF,
            token="new-user-token",
            invited_by=self.owner,
        )

        response = self.client.post(
            reverse("accept_business_invitation", args=[invitation.token]),
            {
                "first_name": "New",
                "last_name": "Employee",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        user = get_user_model().objects.get(email="employee@example.com")
        invitation.refresh_from_db()

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertEqual(Business.objects.count(), 1)
        self.assertTrue(BusinessUser.objects.filter(user=user, business=self.business).exists())
        self.assertEqual(invitation.status, BusinessInvitation.Status.ACCEPTED)
        self.assertEqual(invitation.accepted_by, user)
        self.assertEqual(int(self.client.session[CURRENT_BUSINESS_SESSION_KEY]), self.business.id)

    def test_accept_invitation_for_existing_user_attaches_membership(self):
        existing_user = get_user_model().objects.create_user(
            email="employee@example.com",
            password="StrongPass123!",
            first_name="Existing",
            last_name="Employee",
        )
        invitation = BusinessInvitation.objects.create(
            business=self.business,
            email=existing_user.email,
            role=BusinessUser.Role.ACCOUNTANT,
            token="existing-user-token",
            invited_by=self.owner,
        )

        response = self.client.post(
            reverse("accept_business_invitation", args=[invitation.token]),
            {
                "password": "StrongPass123!",
            },
        )

        invitation.refresh_from_db()
        membership = BusinessUser.objects.get(user=existing_user, business=self.business)

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertEqual(membership.role, BusinessUser.Role.ACCOUNTANT)
        self.assertTrue(membership.is_active)
        self.assertEqual(invitation.status, BusinessInvitation.Status.ACCEPTED)
        self.assertEqual(invitation.accepted_by, existing_user)

    def test_accepted_invitation_cannot_be_reused(self):
        accepted_user = get_user_model().objects.create_user(
            email="accepted@example.com",
            password="StrongPass123!",
            first_name="Accepted",
            last_name="User",
        )
        invitation = BusinessInvitation.objects.create(
            business=self.business,
            email=accepted_user.email,
            role=BusinessUser.Role.STAFF,
            token="accepted-token",
            invited_by=self.owner,
            status=BusinessInvitation.Status.ACCEPTED,
            accepted_by=accepted_user,
            accepted_at=timezone.now(),
        )

        response = self.client.get(reverse("accept_business_invitation", args=[invitation.token]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already been accepted")
        self.assertFalse(
            BusinessUser.objects.filter(user=accepted_user, business=self.business).exists()
        )

    def test_accept_invitation_is_blocked_for_user_with_active_other_workspace_membership(self):
        existing_user = get_user_model().objects.create_user(
            email="employee@example.com",
            password="StrongPass123!",
            first_name="Existing",
            last_name="Employee",
        )
        other_business = Business.objects.create(
            name="Other Workspace",
            slug="other-workspace-team",
            email="hello@otherworkspace.com",
            country="Aruba",
        )
        BusinessUser.objects.create(
            user=existing_user,
            business=other_business,
            role=BusinessUser.Role.STAFF,
        )
        invitation = BusinessInvitation.objects.create(
            business=self.business,
            email=existing_user.email,
            role=BusinessUser.Role.ACCOUNTANT,
            token="cross-workspace-token",
            invited_by=self.owner,
        )

        response = self.client.post(
            reverse("accept_business_invitation", args=[invitation.token]),
            {
                "password": "StrongPass123!",
            },
        )

        invitation.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(invitation.status, BusinessInvitation.Status.PENDING)
        self.assertFalse(
            BusinessUser.objects.filter(user=existing_user, business=self.business).exists()
        )
        self.assertContains(response, MULTI_WORKSPACE_EMAIL_MESSAGE)


class SaaSProfileViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="owner@example.com",
            password="StrongPass123!",
            first_name="Jane",
            last_name="Doe",
            company_name="Acme Freight",
            incorporation_status="CORPORATED",
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse("saas_profile"))

        self.assertRedirects(
            response,
            f"{reverse('business_login')}?next={reverse('saas_profile')}",
        )

    def test_get_creates_profile_and_renders_page(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("saas_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Account Profile")
        self.assertContains(
            response,
            "Business-level workspace details and invoice defaults are managed from Business Settings.",
        )
        self.assertTrue(SaaSUserProfile.objects.filter(user=self.user).exists())

    def test_post_basic_info_updates_user(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("saas_profile"),
            {
                "section": "basic",
                "first_name": "Janet",
                "last_name": "Rivera",
                "email": "janet@example.com",
                "company_name": "FlintIO Caribbean",
                "phone": "+1 721 555 0111",
                "assigned_location": "ST_MAARTEN",
                "date_of_birth": "1992-08-04",
                "address": "Front Street, Philipsburg",
            },
            follow=True,
        )

        self.user.refresh_from_db()

        self.assertRedirects(response, f"{reverse('saas_profile')}?section=basic")
        self.assertEqual(self.user.first_name, "Janet")
        self.assertEqual(self.user.email, "janet@example.com")
        self.assertEqual(self.user.company_name, "FlintIO Caribbean")
        self.assertContains(response, "Basic profile details updated.")

    def test_post_invoice_settings_updates_profile(self):
        self.client.force_login(self.user)
        profile = SaaSUserProfile.get_or_create_for_user(self.user)

        response = self.client.post(
            reverse("saas_profile"),
            {
                "section": "invoice",
                "currency_code": "XCD",
                "invoice_prefix": "CAS",
                "invoice_default_due_days": "21",
                "invoice_accent_color": "#0B6E4F",
                "show_company_address_on_invoice": "on",
                "payment_instructions": "Bank transfer only.",
                "invoice_footer_note": "Thanks for trusting Motionmate.",
            },
            follow=True,
        )

        profile.refresh_from_db()

        self.assertRedirects(response, f"{reverse('saas_profile')}?section=invoice")
        self.assertEqual(profile.currency_code, "XCD")
        self.assertEqual(profile.invoice_prefix, "CAS")
        self.assertEqual(profile.invoice_default_due_days, 21)
        self.assertEqual(profile.invoice_accent_color, "#0B6E4F")
        self.assertTrue(profile.show_company_address_on_invoice)
        self.assertFalse(profile.show_tax_id_on_invoice)
        self.assertContains(response, "Legacy invoice preferences updated.")
