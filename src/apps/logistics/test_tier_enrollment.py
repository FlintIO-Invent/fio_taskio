"""E2 selection and approval binding; payment remains disabled."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier
from unittest import mock, skipUnless

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, ClarivoPlan
from apps.businesses.plan_catalog import LOGISTICS_TIER_SLUGS
from apps.businesses.stripe_checkout import StripeCheckoutError
from apps.businesses.stripe_config import StripeConfigurationError

from .billing import checkout_for_application
from .checkout_approval import (
    approval_metadata,
    current_checkout_application,
    matches_current_approval,
)
from .enrollment import enroll_application, enroll_new_pilot_application, issue_enrollment_link
from .forms import LogisticsApplicationForm
from .models import LogisticsApplication, LogisticsEnrollmentToken
from .services import review_application
from .test_enrollment import PASSWORD, reviewer
from .tests import PILOT_POLICY, application_data


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, LOGISTICS_AUTO_APPROVE_ALL=True)
class TierEnrollmentTests(TestCase):
    def setUp(self):
        self.actor = reviewer()
        ClarivoPlan.objects.filter(slug__in=LOGISTICS_TIER_SLUGS).update(is_active=True)

    def application(self, slug="logistics-core", **changes):
        return LogisticsApplication.objects.create(
            **application_data(selected_plan_slug=slug, **changes)
        )

    def grant(self, application):
        return issue_enrollment_link(
            application.pk, actor=self.actor, expected_revision=application.revision
        )

    def test_each_hyphenated_tier_survives_form_approval_grant_provisioning_and_retry(self):
        for slug in LOGISTICS_TIER_SLUGS:
            with self.subTest(slug=slug):
                form = LogisticsApplicationForm(
                    application_data(selected_plan_slug=slug, email=f"{slug}@example.com")
                )
                self.assertTrue(form.is_valid(), form.errors)
                application = form.save()
                self.assertEqual(application.status, "APPROVED")
                decision = application.decisions.latest("pk")
                self.assertEqual(decision.evaluated_inputs["selected_plan_slug"], slug)
                token = self.grant(application)
                self.assertEqual(application.enrollment_tokens.get().selected_plan_slug, slug)
                with mock.patch("stripe.checkout.Session.create") as payment:
                    result = enroll_application(token, password=PASSWORD)
                    retry = enroll_application(token, authenticated_user=result.user)
                    payment.assert_not_called()
                self.assertTrue(retry.reused)
                self.assertEqual(retry.subscription.pk, result.subscription.pk)
                sub = result.subscription
                self.assertEqual(sub.plan.slug, slug)
                self.assertEqual(sub.status, "pending_checkout")
                self.assertEqual(sub.billing_interval, "yearly")
                self.assertEqual(sub.billing_currency, "eur")
                self.assertIsNone(sub.trial_end)
                self.assertFalse(sub.has_access)
                self.assertEqual(sub.provider_price_id, "")
                application.refresh_from_db()
                self.assertEqual(current_checkout_application(sub), application)
                metadata = approval_metadata(application)
                self.assertEqual(metadata["logistics_plan_slug"], slug)
                self.assertTrue(matches_current_approval(sub, metadata))
                metadata["logistics_plan_slug"] = "logistics"
                self.assertFalse(matches_current_approval(sub, metadata))
        self.assertEqual(BusinessSubscription.objects.count(), 3)

    def test_pilot_signup_uses_selected_tier(self):
        for slug in LOGISTICS_TIER_SLUGS:
            response = self.client.post(
                reverse("logistics_application_create"),
                application_data(
                    selected_plan_slug=slug,
                    email=f"{slug}@example.com",
                    password1=PASSWORD,
                    password2=PASSWORD,
                ),
            )
            self.assertEqual(response.status_code, 302)
            sub = BusinessSubscription.objects.get(business__email=f"{slug}@example.com")
            self.assertEqual(sub.plan.slug, slug)
            self.client.logout()

    def test_invalid_inactive_incomplete_and_wrong_family_selections_fail(self):
        for slug in ("pro", "logistics-scale-yearly", "logistics_core", "unknown"):
            with self.subTest(slug=slug):
                form = LogisticsApplicationForm(application_data(selected_plan_slug=slug))
                self.assertFalse(form.is_valid())
                self.assertIn("selected_plan_slug", form.errors)
                with self.assertRaises(ValidationError):
                    self.application(slug)
        for changes in ({"is_active": False}, {"max_clients": None}, {"family": "SERVICE"}):
            with self.subTest(changes=changes):
                with self.captureOnCommitCallbacks():
                    plan = ClarivoPlan.objects.get(slug="logistics-core")
                    original = {key: getattr(plan, key) for key in changes}
                    ClarivoPlan.objects.filter(pk=plan.pk).update(**changes)
                    with self.assertRaises(ValidationError):
                        self.application()
                    ClarivoPlan.objects.filter(pk=plan.pk).update(**original)
        self.assertFalse(Business.objects.exists())

    def test_configuration_is_rechecked_at_approval_issuance_and_provisioning(self):
        application = self.application()
        token = self.grant(application)
        ClarivoPlan.objects.filter(slug="logistics-core").update(is_active=False)
        for operation in (
            lambda: self.grant(application),
            lambda: review_application(
                application.pk,
                result="APPROVED",
                actor=self.actor,
                reason="Reviewed",
                expected_revision=1,
            ),
            lambda: enroll_application(token, password=PASSWORD),
            lambda: enroll_new_pilot_application(application.pk, password=PASSWORD),
        ):
            with self.assertRaises(ValidationError):
                operation()
        self.assertFalse(Business.objects.exists())
        self.assertEqual(TaskIOUser.objects.count(), 1)
        self.assertIsNone(application.enrollment_tokens.get().used_at)

    def test_tier_change_requires_new_revision_approval_and_grant(self):
        application = self.application()
        stale = self.grant(application)
        application.selected_plan_slug = "logistics-growth"
        application.save(update_fields=["selected_plan_slug"])
        self.assertEqual(application.revision, 2)
        with self.assertRaises(ValidationError):
            enroll_application(stale, password=PASSWORD)
        with self.assertRaises(ValidationError):
            issue_enrollment_link(application.pk, actor=self.actor, expected_revision=1)
        token = self.grant(application)
        result = enroll_application(token, password=PASSWORD)
        self.assertEqual(result.subscription.plan.slug, "logistics-growth")
        application.refresh_from_db()
        application.selected_plan_slug = "logistics-scale"
        with self.assertRaises(ValidationError):
            application.save()

    @override_settings(LOGISTICS_AUTO_APPROVE_ALL=False)
    def test_manual_approval_and_reapproval_bind_current_tier_and_revoke_old_grant(self):
        application = self.application(monthly_parcel_estimate=100000)
        self.assertEqual(application.status, "UNDER_REVIEW")
        with self.assertRaises(ValidationError):
            self.grant(application)
        token = None
        for _ in range(2):
            review_application(
                application.pk,
                result="APPROVED",
                actor=self.actor,
                reason="Tier and operations reviewed",
                expected_revision=1,
            )
            if token is not None:
                with self.assertRaises(ValidationError):
                    enroll_application(token, password=PASSWORD)
            token = self.grant(application)
        result = enroll_application(token, password=PASSWORD)
        self.assertEqual(result.subscription.plan.slug, "logistics-core")

    def test_same_revision_tampering_cannot_replace_approved_tier_or_grant_snapshot(self):
        application = self.application()
        token = self.grant(application)
        LogisticsApplication.objects.filter(pk=application.pk).update(
            selected_plan_slug="logistics-scale"
        )
        with self.assertRaises(ValidationError):
            self.grant(application)
        with self.assertRaises(ValidationError):
            enroll_application(token, password=PASSWORD)
        LogisticsApplication.objects.filter(pk=application.pk).update(
            selected_plan_slug="logistics-core"
        )
        LogisticsEnrollmentToken.objects.filter(application=application).update(
            selected_plan_slug="logistics-scale"
        )
        with self.assertRaises(ValidationError):
            enroll_application(token, password=PASSWORD)
        self.assertFalse(Business.objects.exists())

    def test_enrollment_post_cannot_inject_tier_and_checkout_never_requests_payment(self):
        application = self.application()
        token = self.grant(application)
        response = self.client.post(
            reverse("logistics_application_enroll", args=[token]),
            {
                "password1": PASSWORD,
                "password2": PASSWORD,
                "selected_plan_slug": "logistics-scale",
                "plan": "pro",
            },
        )
        self.assertEqual(response.status_code, 302)
        sub = BusinessSubscription.objects.get()
        self.assertEqual(sub.plan.slug, "logistics-core")
        application.refresh_from_db()
        with mock.patch("apps.logistics.billing.configure_stripe_sdk") as provider:
            with self.assertRaises((StripeCheckoutError, StripeConfigurationError)):
                checkout_for_application(
                    application.pk, request=None, user=application.enrolled_user
                )
            provider.assert_not_called()

    def test_failed_conversion_rolls_back_and_retry_retains_tier(self):
        application = self.application("logistics-scale")
        token = self.grant(application)
        with mock.patch.object(LogisticsEnrollmentToken, "save", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                enroll_application(token, password=PASSWORD)
        self.assertFalse(Business.objects.exists())
        self.assertEqual(TaskIOUser.objects.count(), 1)
        result = enroll_application(token, password=PASSWORD)
        self.assertEqual(result.subscription.plan.slug, "logistics-scale")
        BusinessSubscription.objects.filter(pk=result.subscription.pk).update(
            plan=ClarivoPlan.objects.get(slug="logistics-growth")
        )
        with self.assertRaises(ValidationError):
            enroll_application(token, authenticated_user=result.user)
        result.subscription.refresh_from_db()
        self.assertIsNone(current_checkout_application(result.subscription))

    def test_omitted_selection_rejects_without_changing_unlimited_legacy(self):
        legacy = ClarivoPlan.objects.get(slug="logistics")
        before = {field.name: getattr(legacy, field.name) for field in legacy._meta.fields}
        data = application_data()
        data.pop("selected_plan_slug")
        form = LogisticsApplicationForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("selected_plan_slug", form.errors)
        self.assertFalse(BusinessSubscription.objects.exists())
        legacy.refresh_from_db()
        self.assertEqual(
            before, {field.name: getattr(legacy, field.name) for field in legacy._meta.fields}
        )
        self.assertIsNone(legacy.max_clients)


@skipUnless(connection.vendor == "postgresql", "Row locks require PostgreSQL")
@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, LOGISTICS_AUTO_APPROVE_ALL=True)
class TierEnrollmentConcurrencyTests(TransactionTestCase):
    def test_concurrent_tier_enrollment_reuses_one_subscription(self):
        migration = import_module("apps.businesses.migrations.0029_logistics_capacity_plans")
        for slug, name, amount, capacities in migration.TIERS:
            defaults = migration.tier_defaults(name, amount, capacities)
            defaults["is_active"] = True
            ClarivoPlan.objects.update_or_create(slug=slug, defaults=defaults)
        actor = reviewer()
        user = TaskIOUser.objects.create_user(email="applicant@example.com", password=PASSWORD)
        application = LogisticsApplication.objects.create(
            **application_data(selected_plan_slug="logistics-growth")
        )
        token = issue_enrollment_link(application.pk, actor=actor, expected_revision=1)
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                identity = TaskIOUser.objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                result = enroll_application(token, authenticated_user=identity)
                return result.subscription.pk, result.subscription.plan.slug
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][1], "logistics-growth")
        self.assertEqual(BusinessSubscription.objects.count(), 1)
