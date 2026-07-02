from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.businesses.models import (
    Business,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
)
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY, MULTI_WORKSPACE_EMAIL_MESSAGE

from .models import SaaSUserProfile


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
    def test_get_renders_business_registration_page(self):
        response = self.client.get(reverse("register_business"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Register your business")
        self.assertContains(response, "Owner login email")
        self.assertContains(
            response,
            "Use the email address you want to sign in with. This will become the workspace owner login for this business.",
        )
        self.assertContains(
            response,
            "Use the public contact or billing email for the business. It can be different from the owner login email.",
        )

    def test_post_creates_user_business_membership_trial_subscription_and_logs_in(self):
        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "owner@example.com",
                "business_name": "Acme Freight",
                "business_email": "hello@acmefreight.com",
                "country": "Sint Maarten",
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

        self.assertRedirects(response, reverse("business_settings"))
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertEqual(user.company_name, "Acme Freight")
        self.assertEqual(business.email, "hello@acmefreight.com")
        self.assertEqual(business.country, "Sint Maarten")
        self.assertEqual(membership.role, BusinessUser.Role.OWNER)
        self.assertEqual(subscription.plan.slug, "pro")
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)
        self.assertIsNotNone(subscription.trial_start)
        self.assertIsNotNone(subscription.trial_end)
        self.assertEqual(subscription.trial_end - subscription.trial_start, timedelta(days=14))
        self.assertLessEqual(subscription.trial_start, timezone.now())
        self.assertEqual(profile.workspace_name, "Acme Freight")
        self.assertEqual(profile.billing_email, "hello@acmefreight.com")
        self.assertEqual(int(self.client.session[CURRENT_BUSINESS_SESSION_KEY]), business.id)
        self.assertContains(response, "14-day trial")

    def test_post_generates_unique_slug_for_duplicate_business_names(self):
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
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Business.objects.filter(slug="acme-freight-2").exists())

    def test_post_falls_back_to_first_active_plan_when_pro_is_unavailable(self):
        ClarivoPlan.objects.filter(slug="pro").update(is_active=False)

        response = self.client.post(
            reverse("register_business"),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "starter-owner@example.com",
                "business_name": "Starter Workspace",
                "business_email": "hello@starter.test",
                "country": "Sint Maarten",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            follow=True,
        )

        business = Business.objects.get(name="Starter Workspace")
        subscription = BusinessSubscription.objects.get(business=business)

        self.assertRedirects(response, reverse("business_settings"))
        self.assertEqual(subscription.plan.slug, "starter")
        self.assertEqual(subscription.status, BusinessSubscription.Status.TRIALING)

    def test_post_keeps_registration_working_when_no_active_plan_exists(self):
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
            follow=True,
        )

        business = Business.objects.get(name="No Plan Workspace")

        self.assertRedirects(response, reverse("business_settings"))
        self.assertFalse(BusinessSubscription.objects.filter(business=business).exists())
        self.assertContains(response, "Subscription setup is pending")


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
        self.assertTrue(
            any(alternative[1] == "text/html" for alternative in message.alternatives)
        )
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
        self.assertTrue(
            any(alternative[1] == "text/html" for alternative in message.alternatives)
        )
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
