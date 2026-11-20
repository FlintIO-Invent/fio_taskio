"""Services subscription presentation, real forms and unchanged Logistics contracts."""

import os
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.test import Client as WebClient
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.businesses import tests as portal_contracts
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.test_service_allowances import ServicesFixture
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client
from apps.crm.test_services_dashboard_ui import assert_disposable


class SubscriptionPresentationTests(ServicesFixture, TestCase):
    def setUp(self):
        assert_disposable()
        super().setUp()
        self.login()
        self.url = reverse("business_subscription")

    def test_bound_plan_errors_are_visible_without_mutation(self):
        original = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        response = self.client.post(self.url, {"plan": "999999"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review your plan selection")
        self.assertContains(response, "Select a valid choice.")
        self.assertEqual(
            original, BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        )

    def test_quota_and_module_loss_confirmation_keeps_records(self):
        target = ClarivoPlan.objects.get(slug="starter")
        target.max_clients = 0
        target.allow_invoicing = False
        target.save()
        before = list(Client.objects.order_by("pk").values())
        response = self.client.post(self.url, {"plan": target.pk})
        self.assertContains(response, "Confirm change to Starter")
        self.assertContains(response, "Modules no longer included")
        self.assertContains(response, 'name="confirm_plan_change" value="1"')
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan_id, self.plan.pk)
        self.assertContains(self.client.get(self.url), "Available plans")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan_id, self.plan.pk)
        self.assertEqual(
            self.client.post(self.url, {"plan": target.pk, "confirm_plan_change": "1"}).status_code,
            302,
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan_id, target.pk)
        self.assertEqual(before, list(Client.objects.order_by("pk").values()))

    def test_csrf_and_owner_boundary_are_server_enforced(self):
        guarded = WebClient(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        session = guarded.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(guarded.post(self.url, {"plan": self.plan.pk}).status_code, 403)
        for role in ["admin", "staff", "accountant", "viewer"]:
            self.member.role = role
            self.member.save(update_fields=["role"])
            response = self.client.get(self.url)
            self.assertIn(response.status_code, [302, 403])
            self.assertNotIn(b"mm-services-subscriptions", response.content)
            self.assertIn(
                self.client.post(self.url, {"plan": self.plan.pk}).status_code, [302, 403]
            )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan_id, self.plan.pk)

    def test_foreign_non_catalogue_plan_is_rejected(self):
        other = Business.objects.create(name="Foreign", slug="foreign-subscription")
        foreign = ClarivoPlan.objects.create(name="Private plan", slug="private-plan")
        BusinessSubscription.objects.create(
            business=other, plan=foreign, status="active", payment_provider="local"
        )
        response = self.client.post(self.url, {"plan": foreign.pk})
        self.assertContains(response, "Select a valid choice.")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan_id, self.plan.pk)

    def test_missing_subscription_retains_original_readonly_ui_guard(self):
        # A separate synthetic workspace starts without a subscription; no existing row is removed.
        other = Business.objects.create(name="Unsubscribed", slug="unsubscribed-ui")
        user = self.user()
        BusinessUser.objects.create(business=other, user=user, role="owner")
        self.client.force_login(user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = other.pk
        session.save()
        response = self.client.get(self.url)
        self.assertContains(response, "does not have an active subscription record")
        self.assertContains(
            response, "Plan changes are unavailable while this workspace is read-only."
        )
        self.assertNotContains(response, "Select Starter")
        self.assertFalse(BusinessSubscription.objects.filter(business=other).exists())

    def test_empty_plan_and_free_test_states_preserve_guards(self):
        self.subscription.provisioning_source = "free_test"
        self.subscription.save()
        original = self.subscription.plan_id
        response = self.client.post(
            self.url, {"plan": ClarivoPlan.objects.get(slug="starter").pk}, follow=True
        )
        self.assertContains(response, "Plan changes are unavailable for free-test workspaces")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan_id, original)
        ClarivoPlan.motionmate_plans().update(is_active=False)
        self.assertContains(
            self.client.get(self.url), "No active Motionmate plans are configured yet."
        )

    def test_logistics_original_rendering_and_admin_read_policy(self):
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save()
        self.business.vertical = "LOGISTICS"
        self.business.save()
        self.subscription.plan = plan
        self.subscription.billing_interval = "yearly"
        self.subscription.save()
        before = Path(os.environ["SERVICES_SUBSCRIPTIONS_BEFORE"]) / "src/templates"
        templates = [
            {**settings.TEMPLATES[0], "DIRS": [str(before), *settings.TEMPLATES[0]["DIRS"]]}
        ]

        def clean(value):
            value = re.sub(
                r'name="csrfmiddlewaretoken" value="[^"]+"',
                'name="csrfmiddlewaretoken" value="NORMALIZED"',
                value.decode(),
            )
            return re.sub(r">\s+<", "><", value).strip()

        for role in ["owner", "admin", "staff", "accountant", "viewer"]:
            self.member.role = role
            self.member.save()
            current = self.client.get(self.url)
            with override_settings(TEMPLATES=templates):
                original = self.client.get(self.url)
            self.assertEqual(current.status_code, original.status_code)
            self.assertEqual(clean(current.content), clean(original.content))
            self.assertNotContains(
                current, "services-subscriptions.css", status_code=current.status_code
            )


# Reuse every original portal assertion with a quota-valid membership bootstrap.
# The legacy setup inserts a second member without any subscription, before a
# test can create its own provider state. No model/permission guard is patched.


class PortalContractsWithValidMembershipFixture(portal_contracts.StripeCustomerPortalServiceTests):
    def setUp(self):
        assert_disposable()
        self.factory = portal_contracts.RequestFactory()
        self.owner = portal_contracts.TaskIOUser.objects.create_user(
            email="portal-owner@example.com", password="StrongPass123!"
        )
        self.staff = portal_contracts.TaskIOUser.objects.create_user(
            email="portal-staff@example.com", password="StrongPass123!"
        )
        self.business = Business.objects.create(name="Portal Workspace", slug="portal-workspace")
        self.plan = ClarivoPlan.objects.get(slug="pro")
        bootstrap = BusinessSubscription.objects.create(
            business=self.business, plan=self.plan, status="active", payment_provider="local"
        )
        BusinessUser.objects.create(user=self.owner, business=self.business, role="owner")
        BusinessUser.objects.create(user=self.staff, business=self.business, role="staff")
        # This row belongs only to this test's setup transaction. The inherited
        # tests must create their own subscription states exactly as before.
        bootstrap.delete()
        self.business.refresh_from_db()

    def test_portal_eligibility_denies_ineligible_statuses_and_invalid_local_state(self):
        now = portal_contracts.timezone.now()
        inactive_plan = ClarivoPlan.objects.create(
            name="Inactive Portal Plan",
            slug="inactive-portal-plan",
            is_active=False,
        )
        beta_plan = ClarivoPlan.objects.get(slug=portal_contracts.BETA_PLAN_SLUG)
        inactive_business = Business.objects.create(
            name="Inactive Portal Workspace",
            slug="inactive-portal-workspace",
            is_active=True,
        )
        BusinessUser.objects.create(
            user=self.owner,
            business=inactive_business,
            role=BusinessUser.Role.OWNER,
        )
        inactive_business.is_active = False
        inactive_business.save(update_fields=["is_active"])
        cases = (
            (
                {"status": BusinessSubscription.Status.PENDING_CHECKOUT},
                "status_not_allowed",
            ),
            (
                {
                    "status": BusinessSubscription.Status.TRIALING,
                    "trial_start": now - timedelta(days=15),
                    "trial_end": now - timedelta(days=1),
                    "current_period_start": now - timedelta(days=15),
                    "current_period_end": now - timedelta(days=1),
                },
                BusinessSubscription.AccessCode.TRIAL_EXPIRED,
            ),
            (
                {
                    "status": BusinessSubscription.Status.ACTIVE,
                    "current_period_start": now - timedelta(days=40),
                    "current_period_end": now - timedelta(days=1),
                },
                BusinessSubscription.AccessCode.PROVIDER_STATE_STALE,
            ),
            ({"status": BusinessSubscription.Status.EXPIRED}, "status_not_allowed"),
            ({"status": BusinessSubscription.Status.CANCELLED}, "status_not_allowed"),
            ({"status": BusinessSubscription.Status.PAST_DUE}, "status_not_allowed"),
            ({"status": "surprise"}, "status_not_allowed"),
            ({"plan": beta_plan}, "non_public_plan"),
            ({"plan": inactive_plan}, BusinessSubscription.AccessCode.PLAN_INACTIVE),
            (
                {
                    "business": inactive_business,
                    "provider_customer_id": "cus_inactive_business",
                    "provider_subscription_id": "sub_inactive_business",
                },
                BusinessSubscription.AccessCode.BUSINESS_INACTIVE,
            ),
            (
                {"payment_provider": BusinessSubscription.PaymentProvider.LOCAL},
                "non_stripe_provider",
            ),
            ({"provider_customer_id": ""}, "invalid_provider_customer_id"),
            ({"provider_subscription_id": ""}, "invalid_provider_subscription_id"),
            ({"provider_customer_id": "customer_bad"}, "invalid_provider_customer_id"),
            ({"provider_subscription_id": "subscription_bad"}, "invalid_provider_subscription_id"),
        )

        with override_settings(**self._valid_stripe_settings()):
            for fields, expected_reason in cases:
                with self.subTest(expected_reason=expected_reason):
                    BusinessSubscription.objects.filter(
                        business__in=[self.business, inactive_business]
                    ).delete()
                    subscription = self._subscription(**fields)
                    business = fields.get("business", self.business)

                    availability = portal_contracts.get_customer_portal_availability(
                        business=business,
                        user=self.owner,
                        subscription=subscription,
                        at_time=now,
                    )

                    self.assertFalse(availability.can_open)
                    self.assertEqual(availability.reason, expected_reason)
