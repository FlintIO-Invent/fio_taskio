"""F1 admission retirement; existing legacy contracts and evidence stay intact."""

from unittest import mock

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from apps.businesses.models import Business, BusinessSubscription, ClarivoPlan
from apps.businesses.plan_catalog import LOGISTICS_TIER_SLUGS
from apps.businesses.utils import business_can_access_module

from .enrollment import (
    enroll_application,
    enroll_new_pilot_application,
    inspect_enrollment_link,
    issue_enrollment_link,
)
from .forms import LogisticsApplicationAdminForm, LogisticsApplicationForm
from .models import LogisticsApplication, LogisticsEnrollmentToken
from .registration_test_support import activate_logistics_tiers, restore_legacy_fixture
from .services import reevaluate_application, review_application
from .test_enrollment import PASSWORD, reviewer
from .tests import PILOT_POLICY, application_data


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, LOGISTICS_AUTO_APPROVE_ALL=True)
class RegistrationRetirementTests(TestCase):
    def setUp(self):
        activate_logistics_tiers()
        self.actor = reviewer()

    def application(self):
        return LogisticsApplication.objects.create(**application_data())

    def grant(self, application):
        return issue_enrollment_link(
            application.pk, actor=self.actor, expected_revision=application.revision
        )

    def legacy_fixture(self, *, converted=False):
        application = self.application()
        token = self.grant(application)
        result = enroll_application(token, password=PASSWORD) if converted else None
        restore_legacy_fixture(application)
        return application, token, result

    def test_public_and_admin_choices_require_explicit_current_tier(self):
        for form_class in (LogisticsApplicationForm, LogisticsApplicationAdminForm):
            field = form_class().fields["selected_plan_slug"]
            self.assertTrue(field.required)
            self.assertEqual(field.initial, "")
            self.assertEqual({slug for slug, _ in field.choices}, {"", *LOGISTICS_TIER_SLUGS})
        response = self.client.get(reverse("logistics_application_create"))
        self.assertNotContains(response, "Logistics (legacy)")
        ClarivoPlan.objects.filter(slug__in=LOGISTICS_TIER_SLUGS).update(is_active=False)
        self.assertEqual(
            list(LogisticsApplicationForm().fields["selected_plan_slug"].choices),
            [("", "Select an annual tier")],
        )

    def test_forms_and_public_post_reject_missing_blank_legacy_and_forged_tiers(self):
        for slug in (None, "", "logistics", "pro", "logistics_core", "logistics-scale-yearly"):
            data = application_data()
            if slug is None:
                data.pop("selected_plan_slug")
            else:
                data["selected_plan_slug"] = slug
            for form_class in (LogisticsApplicationForm, LogisticsApplicationAdminForm):
                with self.subTest(slug=slug, form=form_class):
                    form = form_class(data)
                    self.assertFalse(form.is_valid())
                    self.assertIn("selected_plan_slug", form.errors)
            response = self.client.post(
                reverse("logistics_application_create"),
                {**data, "password1": PASSWORD, "password2": PASSWORD},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("selected_plan_slug", response.context["form"].errors)
        self.assertFalse(LogisticsApplication.objects.exists())
        self.assertFalse(Business.objects.exists())

    def test_actual_admin_add_rejects_legacy_and_missing_tier(self):
        self.actor.is_superuser = True
        self.actor.save(update_fields=["is_superuser"])
        self.client.force_login(self.actor)
        for slug in ("logistics", "", "unknown"):
            response = self.client.post(
                reverse("admin:logistics_logisticsapplication_add"),
                application_data(selected_plan_slug=slug),
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("selected_plan_slug", response.context["adminform"].form.errors)
        self.assertFalse(LogisticsApplication.objects.exists())

    def test_programmatic_create_save_and_upserts_reject_legacy_or_missing_selection(self):
        for slug in (None, "", "logistics", "unknown", "business"):
            data = application_data()
            if slug is None:
                data.pop("selected_plan_slug")
            else:
                data["selected_plan_slug"] = slug
            for operation in (
                lambda data=data: LogisticsApplication.objects.create(**data),
                lambda data=data: LogisticsApplication(**data).save(),
                lambda data=data: LogisticsApplication(**data).full_clean(),
                lambda data=data: LogisticsApplication.objects.get_or_create(**data),
                lambda data=data: LogisticsApplication.objects.update_or_create(**data),
            ):
                with self.subTest(slug=slug), self.assertRaises(ValidationError):
                    operation()
        # Bulk writes bypass revision/evaluation hooks and are deliberately rejected.
        with self.assertRaises(ValidationError):
            LogisticsApplication.objects.bulk_create([LogisticsApplication(**application_data())])
        self.assertFalse(LogisticsApplication.objects.exists())

    def test_unconverted_legacy_approval_and_old_grants_cannot_admit(self):
        application, token, _ = self.legacy_fixture()
        decisions = list(application.decisions.values())
        grants = list(application.enrollment_tokens.values())
        for operation in (
            lambda: self.grant(application),
            lambda: inspect_enrollment_link(token),
            lambda: enroll_application(token, password=PASSWORD),
            lambda: enroll_new_pilot_application(application.pk, password=PASSWORD),
            lambda: reevaluate_application(application.pk),
            lambda: review_application(
                application.pk,
                result="APPROVED",
                actor=self.actor,
                reason="Legacy cannot be newly approved",
                expected_revision=1,
            ),
        ):
            with self.assertRaises(ValidationError):
                operation()
        self.assertEqual(list(application.decisions.values()), decisions)
        self.assertEqual(list(application.enrollment_tokens.values()), grants)
        self.assertFalse(Business.objects.exists())

    @override_settings(LOGISTICS_AUTO_APPROVE_ALL=False)
    def test_legacy_tier_selection_requires_new_revision_evaluation_approval_and_grant(self):
        # Reconstruct an approval made before retirement using a current fixture.
        with override_settings(LOGISTICS_AUTO_APPROVE_ALL=True):
            application, old_token, _ = self.legacy_fixture()
        original = list(application.decisions.values())
        application.selected_plan_slug = "logistics-growth"
        application.monthly_parcel_estimate = 100000
        application.save(update_fields=["selected_plan_slug", "monthly_parcel_estimate"])
        self.assertEqual(application.revision, 2)
        self.assertEqual(application.status, "UNDER_REVIEW")
        self.assertEqual(application.evaluated_revision, 2)
        self.assertIsNone(application.approved_revision)
        self.assertEqual(
            list(application.decisions.filter(pk=original[0]["id"]).values()), original
        )
        with self.assertRaises(ValidationError):
            self.grant(application)
        with self.assertRaises(ValidationError):
            enroll_application(old_token, password=PASSWORD)
        with self.assertRaises(ValidationError):
            review_application(
                application.pk,
                result="APPROVED",
                actor=self.actor,
                reason="Stale review",
                expected_revision=1,
            )
        review_application(
            application.pk,
            result="APPROVED",
            actor=self.actor,
            reason="Growth reviewed",
            expected_revision=2,
        )
        application.refresh_from_db()
        with mock.patch("stripe.checkout.Session.create") as provider:
            result = enroll_application(self.grant(application), password=PASSWORD)
        provider.assert_not_called()
        self.assertEqual(result.subscription.plan.slug, "logistics-growth")

    def test_same_revision_legacy_to_tier_tampering_cannot_reuse_approval(self):
        application, token, _ = self.legacy_fixture()
        LogisticsApplication.objects.filter(pk=application.pk).update(
            selected_plan_slug="logistics-core"
        )
        with self.assertRaises(ValidationError):
            enroll_application(token, password=PASSWORD)
        with self.assertRaises(ValidationError):
            self.grant(application)
        self.assertFalse(Business.objects.exists())

    def test_converted_legacy_retry_preserves_historical_evidence_and_records(self):
        application, token, result = self.legacy_fixture(converted=True)
        # Pre-E2 decisions without a slug must still mean legacy.
        decision = application.decisions.get()
        inputs = dict(decision.evaluated_inputs)
        inputs.pop("selected_plan_slug")
        application.decisions.filter(pk=decision.pk).update(evaluated_inputs=inputs)
        before = (
            list(LogisticsApplication.objects.values()),
            list(application.decisions.values()),
            list(LogisticsEnrollmentToken.objects.values()),
            list(BusinessSubscription.objects.values()),
        )
        for _ in range(2):
            retry = enroll_application(token, authenticated_user=result.user)
            self.assertTrue(retry.reused)
            self.assertEqual(retry.subscription.pk, result.subscription.pk)
            self.assertEqual(retry.subscription.plan.slug, "logistics")
        with self.assertRaises(PermissionDenied):
            enroll_application(token, password=PASSWORD)
        self.assertEqual(
            before,
            (
                list(LogisticsApplication.objects.values()),
                list(application.decisions.values()),
                list(LogisticsEnrollmentToken.objects.values()),
                list(BusinessSubscription.objects.values()),
            ),
        )
        application.phone = "+31 20 000 9999"
        application.save(update_fields=["phone"])
        self.assertEqual(application.decisions.get(pk=decision.pk).evaluated_inputs, inputs)
        application.selected_plan_slug = "logistics-core"
        with self.assertRaises(ValidationError):
            application.save()

    def test_existing_legacy_local_entitlements_and_admin_readonly_tier_are_preserved(self):
        application, _, result = self.legacy_fixture(converted=True)
        plan = ClarivoPlan.objects.get(slug="logistics")
        ClarivoPlan.objects.filter(pk=plan.pk).update(is_active=True)
        BusinessSubscription.objects.filter(pk=result.subscription.pk).update(
            status="active", payment_provider="local", billing_currency="usd"
        )
        subscription = BusinessSubscription.objects.get(pk=result.subscription.pk)
        result.business.refresh_from_db()
        plan.refresh_from_db()
        before = (
            ClarivoPlan.objects.filter(pk=plan.pk).values().get(),
            BusinessSubscription.objects.filter(pk=subscription.pk).values().get(),
        )
        self.assertTrue(subscription.has_access)
        self.assertTrue(business_can_access_module(result.business, "parcels"))
        for field in ("max_users", "max_locations", "max_clients", "max_parcels_per_month"):
            self.assertIsNone(getattr(plan, field))
        request = RequestFactory().get("/admin/")
        request.user = self.actor
        model_admin = admin.site._registry[LogisticsApplication]
        self.assertIn("selected_plan_slug", model_admin.get_readonly_fields(request, application))
        form_class = model_admin.get_form(request, application)
        self.assertNotIn("selected_plan_slug", form_class().fields)
        with self.assertRaises(ValidationError):
            LogisticsApplication.objects.create(**application_data(selected_plan_slug="logistics"))
        plan.refresh_from_db()
        subscription.refresh_from_db()
        self.assertEqual(
            before,
            (
                ClarivoPlan.objects.filter(pk=plan.pk).values().get(),
                BusinessSubscription.objects.filter(pk=subscription.pk).values().get(),
            ),
        )

    def test_current_application_cannot_change_back_to_legacy(self):
        application = self.application()
        application.selected_plan_slug = "logistics"
        with self.assertRaises(ValidationError):
            application.save()
        application.refresh_from_db()
        self.assertEqual(application.selected_plan_slug, "logistics-core")
