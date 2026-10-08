from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import mock, skipUnless

from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import SaaSUserProfile, TaskIOUser
from apps.businesses.business_data_inventory import (
    build_business_data_inventory,
    find_unregistered_direct_business_relations,
)
from apps.businesses.business_data_purge import (
    plan_business_purge,
    purge_business,
)
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import business_can_access_module

from .enrollment import (
    enroll_application,
    inspect_enrollment_link,
    issue_enrollment_link,
    revoke_enrollment_links,
)
from .inventory import application_inventory
from .models import LogisticsApplication, LogisticsEnrollmentToken, LogisticsProfile
from .services import review_application
from .tests import PILOT_POLICY, application_data

PASSWORD = "Logistics-Secure-Password-9284"


def reviewer():
    user = TaskIOUser.objects.create_user(
        email="reviewer@example.com", password=PASSWORD, is_staff=True
    )
    user.user_permissions.add(Permission.objects.get(codename="change_logisticsapplication"))
    return user


def approve(application, actor):
    review_application(
        application.pk,
        result="APPROVED",
        actor=actor,
        reason="Identity and application reviewed",
        expected_revision=application.revision,
    )
    application.refresh_from_db()


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY)
class EnrollmentTests(TestCase):
    def setUp(self):
        self.reviewer = reviewer()
        self.application = LogisticsApplication.objects.create(**application_data())
        self.token = issue_enrollment_link(
            self.application.pk, actor=self.reviewer, expected_revision=1
        )

    def enroll(self, **kwargs):
        return enroll_application(self.token, **kwargs)

    def test_grant_is_high_entropy_digest_only_and_bound_to_approval(self):
        grant = self.application.enrollment_tokens.get()
        self.assertGreaterEqual(len(self.token), 43)
        self.assertNotEqual(grant.token_digest, self.token)
        self.assertEqual(grant.application_revision, 1)
        self.assertGreater(grant.expires_at, timezone.now() + timedelta(days=6))
        self.assertIsNone(grant.used_at)
        self.assertEqual(grant.issued_by, self.reviewer)
        self.assertEqual(inspect_enrollment_link(self.token).pk, self.application.pk)

    def test_only_approved_current_revision_can_issue_or_enroll(self):
        for status in ("SUBMITTED", "UNDER_REVIEW", "DECLINED", "WITHDRAWN"):
            with self.subTest(status=status):
                LogisticsApplication.objects.filter(pk=self.application.pk).update(status=status)
                with self.assertRaises(ValidationError):
                    issue_enrollment_link(
                        self.application.pk, actor=self.reviewer, expected_revision=1
                    )
                with self.assertRaises(ValidationError):
                    self.enroll(password=PASSWORD)
        self.assertEqual(Business.objects.count(), 0)

    def test_wrong_approved_and_evaluated_revision_rejected(self):
        for field in ("approved_revision", "evaluated_revision", "revision"):
            with self.subTest(field=field):
                LogisticsApplication.objects.filter(pk=self.application.pk).update(**{field: 2})
                with self.assertRaises(ValidationError):
                    self.enroll(password=PASSWORD)
                LogisticsApplication.objects.filter(pk=self.application.pk).update(**{field: 1})
        with self.assertRaises(ValidationError):
            issue_enrollment_link(self.application.pk, actor=self.reviewer, expected_revision=2)

    def test_material_change_revokes_even_when_new_revision_auto_approved(self):
        self.application.phone = "+31 20 999 0000"
        self.application.save()
        self.assertEqual(self.application.revision, 2)
        self.assertEqual(self.application.status, "APPROVED")
        self.assertIsNotNone(self.application.enrollment_tokens.get().revoked_at)
        with self.assertRaises(ValidationError):
            self.enroll(password=PASSWORD)

    def test_review_reapproval_requires_new_token(self):
        approve(self.application, self.reviewer)
        with self.assertRaises(ValidationError):
            self.enroll(password=PASSWORD)
        token = issue_enrollment_link(self.application.pk, actor=self.reviewer, expected_revision=1)
        self.assertNotEqual(token, self.token)
        self.assertIsNotNone(enroll_application(token, password=PASSWORD).business)

    def test_expired_revoked_replaced_and_invalid_tokens_reject(self):
        LogisticsEnrollmentToken.objects.filter(application=self.application).update(
            expires_at=timezone.now()
        )
        with self.assertRaises(ValidationError):
            self.enroll(password=PASSWORD)
        token = issue_enrollment_link(self.application.pk, actor=self.reviewer, expected_revision=1)
        replacement = issue_enrollment_link(
            self.application.pk, actor=self.reviewer, expected_revision=1
        )
        with self.assertRaises(ValidationError):
            enroll_application(token, password=PASSWORD)
        revoke_enrollment_links(self.application.pk, actor=self.reviewer)
        for value in (replacement, "a" * 43, "short", "a" * 1000):
            with self.subTest(value=value[:10]), self.assertRaises(ValidationError):
                enroll_application(value, password=PASSWORD)

    def test_issuance_and_revocation_require_existing_review_permission(self):
        user = TaskIOUser.objects.create_user(email="unauthorized@example.com")
        for actor in (user, AnonymousUser(), None):
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                issue_enrollment_link(self.application.pk, actor=actor, expected_revision=1)
        with self.assertRaises(PermissionDenied):
            revoke_enrollment_links(self.application.pk, actor=user)

    def test_new_user_provisions_existing_primitives_and_maps_approved_data(self):
        result = self.enroll(password=PASSWORD)
        self.application.refresh_from_db()
        self.assertTrue(result.user.check_password(PASSWORD))
        self.assertEqual(result.user.first_name, "Jane")
        self.assertEqual(result.business.vertical, "LOGISTICS")
        self.assertEqual(result.business.business_type, "")
        self.assertEqual(result.business.name, self.application.business_name)
        self.assertEqual(result.business.email, self.application.email)
        self.assertEqual(result.business.phone, self.application.phone)
        self.assertEqual(result.business.address, self.application.business_address)
        self.assertEqual(result.business.timezone, self.application.timezone)
        self.assertEqual(result.business.currency, "EUR")
        membership = BusinessUser.objects.get(user=result.user, business=result.business)
        self.assertEqual(membership.role, BusinessUser.Role.OWNER)
        self.assertTrue(membership.is_active)
        self.assertEqual(result.user.saas_profile.workspace_name, result.business.name)
        self.assertEqual(self.application.business_id, result.business.pk)
        self.assertEqual(self.application.enrolled_user_id, result.user.pk)
        self.assertEqual(self.application.converted_revision, 1)
        self.assertIsNotNone(self.application.converted_at)
        self.assertEqual(self.application.routes, "Amsterdam to Rotterdam")

    def test_pending_subscription_is_yearly_logistics_no_trial_and_no_access(self):
        result = self.enroll(password=PASSWORD)
        sub = result.subscription
        self.assertEqual(sub.status, "pending_checkout")
        self.assertEqual(sub.plan.family, "LOGISTICS")
        self.assertEqual(sub.billing_interval, "yearly")
        self.assertEqual(sub.billing_currency, "eur")
        self.assertEqual(sub.payment_provider, "stripe")
        self.assertIsNone(sub.trial_start)
        self.assertIsNone(sub.trial_end)
        self.assertEqual(sub.provider_checkout_session_id, "")
        self.assertFalse(sub.has_access)
        # Verify pending is itself sufficient to deny access after offering activation.
        sub.plan.is_active = True
        sub.plan.save(update_fields=["is_active"])
        sub.refresh_from_db()
        self.assertFalse(sub.effective_access_state.can_view_workspace)
        self.assertFalse(sub.effective_access_state.can_modify_workspace)
        for module in (
            "workspace",
            "clients",
            "invoicing",
            "parcels",
            "tracking",
            "shipments",
            "manifests",
        ):
            with self.subTest(module=module):
                self.assertFalse(business_can_access_module(result.business, module))

    def test_existing_email_requires_authentication_and_preserves_credentials(self):
        existing = TaskIOUser.objects.create_user(
            email=self.application.email.upper(), password=PASSWORD
        )
        with self.assertRaises(PermissionDenied):
            self.enroll(password=PASSWORD)
        self.assertEqual(Business.objects.count(), 0)
        result = self.enroll(authenticated_user=existing)
        self.assertEqual(result.user.pk, existing.pk)
        self.assertTrue(result.user.check_password(PASSWORD))
        self.assertEqual(TaskIOUser.objects.count(), 2)
        self.assertTrue(SaaSUserProfile.objects.filter(user=existing).exists())

    def test_existing_profile_not_overwritten(self):
        existing = TaskIOUser.objects.create_user(email=self.application.email, password=PASSWORD)
        profile = SaaSUserProfile.get_or_create_for_user(existing)
        profile.workspace_name = "Previous account settings"
        profile.save()
        self.enroll(authenticated_user=existing)
        profile.refresh_from_db()
        self.assertEqual(profile.workspace_name, "Previous account settings")

    def test_wrong_or_inactive_authenticated_identity_cannot_enroll(self):
        for email, active in (("someone@example.com", True), (self.application.email, False)):
            user = TaskIOUser.objects.create_user(email=email, password=PASSWORD)
            TaskIOUser.objects.filter(pk=user.pk).update(is_active=active)
            with self.assertRaises(PermissionDenied):
                self.enroll(authenticated_user=user)
        self.assertEqual(Business.objects.count(), 0)

    def test_active_workspace_conflict_blocks_without_partial_conversion(self):
        user = TaskIOUser.objects.create_user(email=self.application.email, password=PASSWORD)
        business = Business.objects.create(name="Existing", slug="existing")
        BusinessUser.objects.create(user=user, business=business, role="OWNER")
        with self.assertRaisesMessage(ValidationError, "active workspace"):
            self.enroll(authenticated_user=user)
        self.assertEqual(Business.objects.count(), 1)
        self.application.refresh_from_db()
        self.assertIsNone(self.application.business_id)
        self.assertIsNone(self.application.enrollment_tokens.get().used_at)

    def test_inactive_business_membership_does_not_change_current_conflict_policy(self):
        user = TaskIOUser.objects.create_user(email=self.application.email, password=PASSWORD)
        business = Business.objects.create(name="Inactive", slug="inactive", is_active=False)
        BusinessUser.objects.create(user=user, business=business, role="OWNER")
        self.assertIsNotNone(self.enroll(authenticated_user=user).business)

    def test_authenticated_retry_reuses_every_record_and_anonymous_replay_rejects(self):
        result = self.enroll(password=PASSWORD)
        for _ in range(3):
            retry = self.enroll(authenticated_user=result.user)
            self.assertTrue(retry.reused)
            self.assertEqual(retry.business.pk, result.business.pk)
            self.assertEqual(retry.subscription.pk, result.subscription.pk)
        with self.assertRaises(PermissionDenied):
            self.enroll(password=PASSWORD)
        with self.assertRaises(ValidationError):
            issue_enrollment_link(self.application.pk, actor=self.reviewer, expected_revision=1)
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessUser.objects.count(), 1)
        self.assertEqual(BusinessSubscription.objects.count(), 1)
        self.assertEqual(SaaSUserProfile.objects.count(), 1)

    def test_consumed_link_still_enforces_expiry_and_revocation(self):
        result = self.enroll(password=PASSWORD)
        revoke_enrollment_links(self.application.pk, actor=self.reviewer)
        with self.assertRaises(ValidationError):
            self.enroll(authenticated_user=result.user)
        self.assertEqual(Business.objects.count(), 1)

    def test_late_transaction_failure_leaves_no_partial_conversion_and_is_retryable(self):
        with mock.patch(
            "apps.logistics.enrollment.LogisticsEnrollmentToken.save",
            side_effect=RuntimeError("Write failed"),
        ):
            with self.assertRaises(RuntimeError):
                self.enroll(password=PASSWORD)
        self.assertEqual(TaskIOUser.objects.count(), 1)
        for model in (Business, BusinessUser, BusinessSubscription, SaaSUserProfile):
            self.assertEqual(model.objects.count(), 0)
        self.application.refresh_from_db()
        self.assertIsNone(self.application.business_id)
        self.assertIsNone(self.application.enrollment_tokens.get().used_at)
        self.assertFalse(self.enroll(password=PASSWORD).reused)

    def test_duplicate_user_race_rolls_back_and_requires_authentication(self):
        with mock.patch("apps.logistics.enrollment.get_user_model") as get_user:
            get_user.return_value = TaskIOUser
            with mock.patch.object(
                TaskIOUser.objects, "create_user", side_effect=IntegrityError("duplicate")
            ):
                with self.assertRaisesMessage(ValidationError, "Sign in"):
                    self.enroll(password=PASSWORD)
        self.assertEqual(Business.objects.count(), 0)
        self.assertIsNone(self.application.enrollment_tokens.get().used_at)

    def test_missing_or_wrong_family_offering_rolls_back(self):
        ClarivoPlan.objects.filter(slug="logistics").update(family="SERVICE")
        with self.assertRaises(ValidationError):
            self.enroll(password=PASSWORD)
        self.assertEqual(TaskIOUser.objects.count(), 1)
        self.assertEqual(Business.objects.count(), 0)

    def test_conversion_fields_cannot_be_injected_through_model_save(self):
        business = Business.objects.create(name="Injected", slug="injected")
        self.application.business = business
        with self.assertRaises(ValidationError):
            self.application.save()

    def test_inspection_and_controlled_purge_retain_durable_conversion(self):
        result = self.enroll(password=PASSWORD)
        inventory = application_inventory(self.application.pk)
        self.assertEqual(inventory["business_id"], result.business.pk)
        self.assertEqual(inventory["enrolled_user_id"], result.user.pk)
        self.assertTrue(inventory["subscription_link_present"])
        self.assertEqual(find_unregistered_direct_business_relations(), ())
        records = build_business_data_inventory(result.business).records
        self.assertEqual(
            next(r for r in records if r.key == "logistics_application").total_count, 1
        )
        with self.assertRaises(ProtectedError):
            result.business.delete()
        with self.assertRaises(ProtectedError):
            result.user.delete()
        result.business.is_active = False
        result.business.save(update_fields=["is_active"])
        plan = plan_business_purge(result.business.pk)
        self.assertNotIn("logistics_conversion_protected", plan.blocking_error_codes)
        purge_business(business_id=result.business.pk, reason_reference="block11-test")
        self.application.refresh_from_db()
        self.assertIsNone(self.application.business_id)
        self.assertEqual(self.application.business_id_snapshot, result.business.pk)
        self.assertFalse(Business.objects.filter(pk=result.business.pk).exists())

    def test_public_flow_collects_only_security_data_and_logs_in_pending_owner(self):
        url = reverse("logistics_application_enroll", args=[self.token])
        response = self.client.get(url)
        self.assertEqual(set(response.context["form"].fields), {"password1", "password2"})
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        response = self.client.post(
            url,
            {
                "password1": PASSWORD,
                "password2": PASSWORD,
                "business_name": "Injected",
                "vertical": "SERVICE",
            },
        )
        self.assertRedirects(response, reverse("logistics_enrollment_complete"))
        self.assertEqual(Business.objects.get().name, self.application.business_name)
        self.assertEqual(
            int(self.client.session["_auth_user_id"]),
            TaskIOUser.objects.get(email=self.application.email).pk,
        )
        self.assertRedirects(self.client.post(url, {}), reverse("logistics_enrollment_complete"))
        self.assertEqual(Business.objects.count(), 1)

    def test_existing_owner_password_verification_works_without_workspace_login(self):
        user = TaskIOUser.objects.create_user(email=self.application.email, password=PASSWORD)
        url = reverse("logistics_application_enroll", args=[self.token])
        self.assertEqual(set(self.client.get(url).context["form"].fields), {"password1"})
        self.assertContains(self.client.post(url, {"password1": "wrong"}), "Unable to verify")
        self.assertEqual(Business.objects.count(), 0)
        self.assertRedirects(
            self.client.post(url, {"password1": PASSWORD}), reverse("logistics_enrollment_complete")
        )
        self.assertEqual(BusinessUser.objects.get().user_id, user.pk)

    def test_password_policy_and_csrf_are_enforced(self):
        url = reverse("logistics_application_enroll", args=[self.token])
        self.assertContains(
            self.client.post(url, {"password1": "123", "password2": "123"}), "too short"
        )
        self.assertEqual(Business.objects.count(), 0)
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            csrf_client.post(url, {"password1": PASSWORD, "password2": PASSWORD}).status_code, 403
        )

    def test_admin_issues_only_on_post_and_requires_permission(self):
        url = reverse("admin:logistics_logisticsapplication_enrollment", args=[self.application.pk])
        self.client.force_login(self.reviewer)
        count = LogisticsEnrollmentToken.objects.count()
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(LogisticsEnrollmentToken.objects.count(), count)
        response = self.client.post(url, {"revision": 1, "action": "issue"})
        self.assertContains(response, "Deliver this link privately")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(LogisticsEnrollmentToken.objects.count(), count + 1)
        user = TaskIOUser.objects.create_user(email="staff@example.com", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.post(url, {"revision": 1}).status_code, 403)


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency requires PostgreSQL")
@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY)
class EnrollmentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        # TransactionTestCase flushes migration seed rows between methods.
        ClarivoPlan.objects.get_or_create(
            slug="logistics",
            defaults={"name": "Logistics", "family": "LOGISTICS", "is_active": False},
        )

    def test_same_grant_simultaneous_requests_create_one_conversion(self):
        actor = reviewer()
        user = TaskIOUser.objects.create_user(email="applicant@example.com", password=PASSWORD)
        application = LogisticsApplication.objects.create(**application_data())
        approve(application, actor)
        token = issue_enrollment_link(application.pk, actor=actor, expected_revision=1)
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                identity = TaskIOUser.objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                result = enroll_application(token, authenticated_user=identity)
                return result.business.pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessUser.objects.count(), 1)
        self.assertEqual(BusinessSubscription.objects.count(), 1)
        profile = LogisticsProfile.objects.get()
        self.assertEqual(profile.operating_areas, ["TRANSPORTATION"])
        self.assertEqual(profile.transportation_modes, ["ROAD"])

    def test_different_applications_serialize_existing_identity_workspace_conflict(self):
        actor = reviewer()
        user = TaskIOUser.objects.create_user(email="applicant@example.com", password=PASSWORD)
        tokens = []
        for name in ("First applicant", "Second applicant"):
            application = LogisticsApplication.objects.create(
                **application_data(business_name=name)
            )
            approve(application, actor)
            tokens.append(issue_enrollment_link(application.pk, actor=actor, expected_revision=1))
        barrier = Barrier(2)

        def worker(token):
            close_old_connections()
            try:
                identity = TaskIOUser.objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                try:
                    enroll_application(token, authenticated_user=identity)
                    return "converted"
                except ValidationError:
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, tokens))
        self.assertCountEqual(results, ["converted", "conflict"])
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessSubscription.objects.count(), 1)
        profile = LogisticsProfile.objects.get()
        self.assertEqual(profile.operating_areas, ["TRANSPORTATION"])
        self.assertEqual(profile.transportation_modes, ["ROAD"])
