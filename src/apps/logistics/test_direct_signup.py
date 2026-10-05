"""Pilot signup reuses enrollment conversion without granting unpaid operational access."""

import json
from unittest import mock

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import SaaSUserProfile, TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY, business_can_access_module

from .enrollment import enroll_application, enroll_new_pilot_application, issue_enrollment_link
from .forms import LogisticsApplicationForm, LogisticsSignupForm
from .models import LogisticsApplication, LogisticsApplicationDecision, LogisticsEnrollmentToken
from .services import review_application
from .test_enrollment import PASSWORD
from .tests import PILOT_POLICY, application_data


@override_settings(LOGISTICS_AUTO_APPROVE_ALL=True, LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY)
class DirectSignupTests(TestCase):
    def payload(self, **changes):
        return {**application_data(), "password1": PASSWORD, "password2": PASSWORD, **changes}

    def submit(self, **changes):
        return self.client.post(reverse("logistics_application_create"), self.payload(**changes))

    def approve_and_issue(self, application):
        actor = TaskIOUser.objects.create_user(email="reviewer@example.com", is_staff=True)
        actor.user_permissions.add(Permission.objects.get(codename="change_logisticsapplication"))
        review_application(
            application.pk,
            result="APPROVED",
            actor=actor,
            reason="Reviewed application and identity",
            expected_revision=application.revision,
        )
        return issue_enrollment_link(
            application.pk, actor=actor, expected_revision=application.revision
        )

    def test_new_signup_provisions_logs_in_selects_workspace_and_redirects(self):
        with mock.patch(
            "apps.businesses.stripe_checkout._stripe_create_checkout_session"
        ) as checkout:
            response = self.submit()
        checkout.assert_not_called()
        self.assertRedirects(response, reverse("agent_dashboard"))
        application = LogisticsApplication.objects.get()
        self.assertEqual(application.status, "APPROVED")
        user = TaskIOUser.objects.get()
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(user.email, application.email)
        business = Business.objects.get()
        self.assertEqual(business.vertical, Business.Vertical.LOGISTICS)
        self.assertEqual(business.name, application.business_name)
        self.assertEqual(application.business_id, business.pk)
        self.assertEqual(application.business_id_snapshot, business.pk)
        self.assertEqual(application.enrolled_user_id, user.pk)
        self.assertEqual(application.converted_revision, application.revision)
        self.assertIsNotNone(application.converted_at)
        self.assertEqual(BusinessUser.objects.get().role, BusinessUser.Role.OWNER)
        self.assertEqual(SaaSUserProfile.objects.get().user_id, user.pk)
        subscription = BusinessSubscription.objects.get()
        self.assertEqual(subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertEqual(subscription.billing_interval, BusinessSubscription.BillingInterval.YEARLY)
        self.assertEqual(subscription.plan.family, ClarivoPlan.Family.LOGISTICS)
        self.assertEqual(subscription.payment_provider, BusinessSubscription.PaymentProvider.STRIPE)
        self.assertIsNone(subscription.trial_start)
        self.assertIsNone(subscription.trial_end)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertEqual(self.client.session[CURRENT_BUSINESS_SESSION_KEY], business.pk)
        self.assertEqual(LogisticsEnrollmentToken.objects.count(), 0)

    def test_passwords_are_absent_from_application_decision_session_and_html(self):
        self.submit()
        application = LogisticsApplication.objects.get()
        self.assertFalse({"password", "password1", "password2"} & set(application.__dict__))
        self.assertNotIn(
            PASSWORD, json.dumps(LogisticsApplication.objects.values().get(), default=str)
        )
        self.assertNotIn(
            PASSWORD, json.dumps(LogisticsApplicationDecision.objects.values().get(), default=str)
        )
        self.assertNotIn(PASSWORD, json.dumps(dict(self.client.session), default=str))
        self.assertNotContains(self.client.get(reverse("agent_dashboard")), PASSWORD)
        self.assertEqual(
            set(LogisticsApplicationForm().fields), set(LogisticsApplication.MATERIAL_FIELDS)
        )

    def test_password_validation_confirmation_and_csrf(self):
        for changes in (
            {"password1": "", "password2": ""},
            {"password1": "123", "password2": "123"},
            {"password2": "does-not-match"},
            {"password1": "password123", "password2": "password123"},
        ):
            with self.subTest(changes=changes):
                response = self.submit(**changes)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertNotIn("value=", response.context["form"]["password1"].as_widget())
        self.assertEqual(LogisticsApplication.objects.count(), 0)
        self.assertEqual(TaskIOUser.objects.count(), 0)
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            csrf_client.post(reverse("logistics_application_create"), self.payload()).status_code,
            403,
        )

    def test_pending_dashboard_shows_payment_cta_and_no_operational_data(self):
        self.submit()
        response = self.client.get(reverse("agent_dashboard"))
        self.assertTemplateUsed(response, "logistics/pending_checkout_dashboard.html")
        self.assertTrue(response.context["logistics_dashboard"])
        self.assertEqual(response.context["current_business"].pk, Business.objects.get().pk)
        self.assertContains(response, "Account successfully created")
        self.assertContains(response, "annual Logistics subscription is required")
        self.assertContains(response, "Continue to payment")
        self.assertContains(
            response,
            reverse("logistics_application_checkout", args=[LogisticsApplication.objects.get().pk]),
        )
        for action in ("Register Parcel", "Create Shipment", "View Parcels", "Active parcels"):
            self.assertNotContains(response, action)
        self.assertNotIn("parcel_count", response.context)

    def test_pending_owner_dashboard_remains_available_when_offering_activated(self):
        self.submit()
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        response = self.client.get(reverse("agent_dashboard"))
        self.assertContains(response, "Continue to payment")
        self.assertFalse(Business.objects.get().subscription.can_view_workspace)

    def test_unpaid_read_write_and_dashboard_post_remain_guarded(self):
        self.submit()
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        business = Business.objects.get()
        for module in ("parcels", "shipments", "tracking", "clients", "invoicing"):
            self.assertFalse(business_can_access_module(business, module, access="read"))
            self.assertFalse(business_can_access_module(business, module, access="write"))
        for name in (
            "logistics_parcel_list",
            "logistics_parcel_register",
            "logistics_shipment_list",
            "logistics_shipment_create",
        ):
            for method in (self.client.get, self.client.post):
                self.assertNotEqual(method(reverse(name)).status_code, 200)
        response = self.client.post(
            reverse("agent_dashboard"),
            {"onboarding_action": "select_journey", "selected_journey": "parcel_tracking"},
        )
        self.assertTemplateUsed(response, "logistics/pending_checkout_dashboard.html")
        self.assertFalse(business.subscription.can_modify_workspace)

    def test_payment_cta_uses_existing_checkout_entry_without_choices(self):
        self.submit()
        application = LogisticsApplication.objects.get()
        with mock.patch(
            "apps.logistics.views.checkout_for_application",
            return_value="https://checkout.stripe.test/annual",
        ) as checkout:
            response = self.client.post(
                reverse("logistics_application_checkout", args=[application.pk])
            )
        self.assertEqual(response.url, "https://checkout.stripe.test/annual")
        self.assertEqual(checkout.call_args.args, (application.pk,))
        self.assertEqual(checkout.call_args.kwargs["user"].pk, application.enrolled_user_id)
        self.assertEqual(
            BusinessSubscription.objects.get().status, BusinessSubscription.Status.PENDING_CHECKOUT
        )

    def test_authenticated_identical_retry_does_not_duplicate_any_records(self):
        self.submit()
        response = self.submit()
        self.assertRedirects(response, reverse("agent_dashboard"))
        for model in (
            TaskIOUser,
            SaaSUserProfile,
            Business,
            BusinessUser,
            BusinessSubscription,
            LogisticsApplication,
            LogisticsApplicationDecision,
        ):
            self.assertEqual(model.objects.count(), 1, model.__name__)

    def test_anonymous_duplicate_post_does_not_claim_existing_account(self):
        self.submit()
        stranger = Client()
        response = stranger.post(reverse("logistics_application_create"), self.payload())
        self.assertRedirects(response, reverse("logistics_application_received"))
        self.assertNotIn("_auth_user_id", stranger.session)
        self.assertEqual(TaskIOUser.objects.count(), 1)
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(LogisticsApplication.objects.filter(converted_at__isnull=False).count(), 1)

    def test_existing_email_needs_no_new_password_and_is_not_claimed(self):
        user = TaskIOUser.objects.create_user(email="applicant@example.com", password=PASSWORD)
        old_hash = user.password
        response = self.submit(email="APPLICANT@EXAMPLE.COM", password1="", password2="")
        self.assertRedirects(response, reverse("logistics_application_received"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(self.client.get(response.url), "Sign in to Motionmate")
        self.assertEqual(Business.objects.count(), 0)
        self.assertEqual(BusinessUser.objects.count(), 0)
        self.assertEqual(SaaSUserProfile.objects.count(), 0)
        user.refresh_from_db()
        self.assertEqual(user.password, old_hash)
        self.assertEqual(LogisticsApplication.objects.get().enrolled_user_id, None)
        form = LogisticsSignupForm(self.payload(password1="ignored", password2="different"))
        self.assertTrue(form.is_valid())
        self.assertIsNone(form.new_account_password)
        self.assertNotIn("password1", form.cleaned_data)

    def test_existing_account_choice_collects_no_new_credentials_and_retains_token_path(self):
        response = self.submit(use_existing_account="on", password1="", password2="")
        self.assertRedirects(response, reverse("logistics_application_received"))
        application = LogisticsApplication.objects.get()
        self.assertEqual(TaskIOUser.objects.count(), 0)
        token = self.approve_and_issue(application)
        result = enroll_application(token, password=PASSWORD)
        self.assertEqual(result.business.vertical, "LOGISTICS")

    def test_existing_user_secure_enrollment_still_requires_authentication(self):
        user = TaskIOUser.objects.create_user(email="applicant@example.com", password=PASSWORD)
        self.submit(password1="", password2="")
        token = self.approve_and_issue(LogisticsApplication.objects.get())
        with self.assertRaises(PermissionDenied):
            enroll_application(token, password=PASSWORD)
        result = enroll_application(token, authenticated_user=user)
        self.assertEqual(result.user.pk, user.pk)
        self.assertEqual(result.business.vertical, "LOGISTICS")

    def test_existing_active_workspace_conflict_remains_protected_even_when_logged_in(self):
        user = TaskIOUser.objects.create_user(email="applicant@example.com", password=PASSWORD)
        business = Business.objects.create(name="Existing", slug="existing-service")
        BusinessUser.objects.create(user=user, business=business, role=BusinessUser.Role.OWNER)
        self.client.force_login(user)
        response = self.submit(password1="", password2="")
        self.assertRedirects(response, reverse("logistics_application_received"))
        application = LogisticsApplication.objects.get()
        token = self.approve_and_issue(application)
        with self.assertRaises(ValidationError):
            enroll_application(token, authenticated_user=user)
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessUser.objects.count(), 1)
        application.refresh_from_db()
        self.assertIsNone(application.converted_at)

    def test_identity_race_never_reuses_or_logs_in_existing_user(self):
        original = enroll_new_pilot_application

        def race(application_id, *, password):
            TaskIOUser.objects.create_user(
                email="applicant@example.com", password="Unrelated-password-123"
            )
            return original(application_id, password=password)

        with mock.patch("apps.logistics.views.enroll_new_pilot_application", side_effect=race):
            response = self.submit()
        self.assertRedirects(response, reverse("logistics_application_received"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(TaskIOUser.objects.count(), 1)
        self.assertEqual(Business.objects.count(), 0)
        self.assertFalse(TaskIOUser.objects.get().check_password(PASSWORD))

    def test_conversion_failure_rolls_back_and_same_session_can_retry(self):
        with mock.patch(
            "apps.logistics.enrollment.BusinessSubscription.objects.create",
            side_effect=ValidationError("Unavailable"),
        ):
            response = self.submit()
        self.assertRedirects(response, reverse("logistics_application_received"))
        for model in (TaskIOUser, SaaSUserProfile, Business, BusinessUser, BusinessSubscription):
            self.assertEqual(model.objects.count(), 0)
        self.assertEqual(LogisticsApplication.objects.count(), 1)
        self.assertIsNone(LogisticsApplication.objects.get().converted_at)
        self.assertRedirects(self.submit(), reverse("agent_dashboard"))
        self.assertEqual(LogisticsApplication.objects.count(), 1)

    def test_direct_entry_rejects_replay_manual_approval_and_stale_revision(self):
        self.submit()
        application = LogisticsApplication.objects.get()
        with self.assertRaises(PermissionDenied):
            enroll_new_pilot_application(application.pk, password=PASSWORD)
        other = LogisticsApplication.objects.create(
            **application_data(email="second@example.com", business_name="Second")
        )
        self.approve_and_issue(other)
        with self.assertRaises(PermissionDenied):
            enroll_new_pilot_application(other.pk, password=PASSWORD)
        LogisticsApplication.objects.filter(pk=other.pk).update(approved_revision=0)
        with self.assertRaises(ValidationError):
            enroll_new_pilot_application(other.pk, password=PASSWORD)
        self.assertEqual(Business.objects.count(), 1)

    @override_settings(LOGISTICS_AUTO_APPROVE_ALL=False)
    def test_strict_review_does_not_provision_and_original_enrollment_still_works(self):
        response = self.submit(monthly_parcel_estimate=10000)
        self.assertRedirects(response, reverse("logistics_application_received"))
        self.assertNotIn("password1", LogisticsSignupForm().fields)
        application = LogisticsApplication.objects.get()
        self.assertEqual(application.status, "UNDER_REVIEW")
        self.assertEqual(TaskIOUser.objects.count(), 0)
        self.assertNotIn("_auth_user_id", self.client.session)
        token = self.approve_and_issue(application)
        result = enroll_application(token, password=PASSWORD)
        self.assertEqual(result.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)

    @override_settings(LOGISTICS_AUTO_APPROVE_ALL=False)
    def test_strict_auto_approved_application_still_requires_enrollment(self):
        response = self.submit()
        self.assertRedirects(response, reverse("logistics_application_received"))
        application = LogisticsApplication.objects.get()
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(TaskIOUser.objects.count(), 0)
        with self.assertRaises(PermissionDenied):
            enroll_new_pilot_application(application.pk, password=PASSWORD)

    def test_pending_non_owner_cannot_reach_payment_dashboard(self):
        self.submit()
        member = TaskIOUser.objects.create_user(email="staff@example.com", password=PASSWORD)
        BusinessUser.objects.create(
            user=member, business=Business.objects.get(), role=BusinessUser.Role.STAFF
        )
        self.client.force_login(member)
        self.assertEqual(self.client.get(reverse("agent_dashboard")).status_code, 403)

    def test_service_pending_checkout_dashboard_behavior_is_unchanged(self):
        user = TaskIOUser.objects.create_user(email="service@example.com", password=PASSWORD)
        business = Business.objects.create(name="Services", slug="service-pending")
        BusinessUser.objects.create(user=user, business=business, role=BusinessUser.Role.OWNER)
        BusinessSubscription.objects.create(
            business=business,
            plan=ClarivoPlan.objects.get(slug="pro"),
            status=BusinessSubscription.Status.PENDING_CHECKOUT,
        )
        self.client.force_login(user)
        self.assertRedirects(
            self.client.get(reverse("agent_dashboard")), reverse("billing_checkout_cancelled")
        )
