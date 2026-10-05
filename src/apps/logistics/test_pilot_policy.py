from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, BusinessUser

from .eligibility import evaluate_eligibility
from .enrollment import enroll_application, issue_enrollment_link
from .models import LogisticsApplication, LogisticsApplicationDecision
from .services import reevaluate_application
from .test_enrollment import PASSWORD, reviewer
from .tests import PILOT_POLICY, application_data


class PilotConfigurationTests(SimpleTestCase):
    def test_auto_approval_defaults_on_and_accepts_false_environment_value(self):
        from config import Settings

        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(Settings(_env_file=None).logistics_auto_approve_all)
            with mock.patch.dict("os.environ", {"LOGISTICS_AUTO_APPROVE_ALL": "False"}):
                self.assertFalse(Settings(_env_file=None).logistics_auto_approve_all)


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, LOGISTICS_AUTO_APPROVE_ALL=True)
class PilotApprovalTests(TestCase):
    def submit(self, **changes):
        response = self.client.post(
            reverse("logistics_application_create"),
            {**application_data(**changes), "use_existing_account": "on"},
        )
        self.assertRedirects(response, reverse("logistics_application_received"))
        return LogisticsApplication.objects.latest("created_at")

    def test_secure_enrollment_choice_approves_without_provisioning_or_checkout(self):
        with mock.patch(
            "apps.businesses.stripe_checkout._stripe_create_checkout_session"
        ) as checkout:
            application = self.submit()
        checkout.assert_not_called()
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(application.decision_result, "APPROVED")
        self.assertEqual(application.approved_revision, application.revision)
        self.assertEqual(application.evaluated_revision, application.revision)
        self.assertEqual(application.reason_codes, [])
        self.assertEqual(TaskIOUser.objects.count(), 0)
        self.assertEqual(Business.objects.count(), 0)
        self.assertEqual(BusinessSubscription.objects.count(), 0)
        self.assertEqual(application.enrollment_tokens.count(), 0)

    def test_each_review_trigger_is_advisory_with_audited_strict_result(self):
        cases = (
            ({"monthly_parcel_estimate": 5001}, "HIGH_MONTHLY_VOLUME"),
            ({"expected_staff_count": 11}, "HIGH_STAFF_COUNT"),
            ({"location_count": 2}, "MULTI_BRANCH"),
            (
                {"custom_workflow": True, "custom_workflow_details": "Special process"},
                "CUSTOM_WORKFLOW",
            ),
            ({"custom_workflow_details": "Special process"}, "CUSTOM_WORKFLOW"),
            ({"multi_jurisdiction": True}, "MULTI_JURISDICTION"),
            ({"api_integration_needed": True}, "API_INTEGRATION_REQUIRED"),
            ({"country": "Unknown territory"}, "UNSUPPORTED_TERRITORY"),
            ({"custom_pricing_requested": True}, "CUSTOM_PRICING_REQUESTED"),
            ({"monthly_parcel_estimate": 10000}, "HIGH_RESOURCE_INTENSITY"),
            ({"operation_type": "OTHER"}, "HIGH_RESOURCE_INTENSITY"),
            (
                {"current_process_method": "OTHER", "current_process_details": "Special process"},
                "HIGH_RESOURCE_INTENSITY",
            ),
            ({"registration_number": ""}, "INCOMPLETE_BUSINESS_REGISTRATION"),
        )
        for index, (changes, reason) in enumerate(cases):
            with self.subTest(reason=reason, changes=changes):
                application = self.submit(
                    **{
                        **application_data(
                            business_name=f"Pilot Company {index}",
                            email=f"applicant{index}@example.com",
                            registration_number=f"KVK{index}",
                        ),
                        **changes,
                    }
                )
                self.assertEqual(application.status, "APPROVED")
                self.assertIn(reason, application.reason_codes)
                decision = application.decisions.get()
                strict = evaluate_eligibility(application.material_inputs(), PILOT_POLICY)
                self.assertEqual(decision.result, "APPROVED")
                self.assertEqual(decision.evaluated_result, "UNDER_REVIEW")
                self.assertEqual(decision.source, "AUTOMATIC")
                self.assertEqual(decision.reason_codes, list(strict.reason_codes))
                self.assertEqual(decision.reason_codes, application.reason_codes)
                self.assertEqual(decision.resource_classification, strict.resource_classification)
                self.assertEqual(
                    decision.threshold_snapshot,
                    {**PILOT_POLICY.model_dump(mode="json"), "auto_approve_all": True},
                )
                self.assertEqual(application.threshold_snapshot, decision.threshold_snapshot)
                self.assertEqual(decision.application_revision, application.revision)
                self.assertEqual(decision.rule_version, PILOT_POLICY.rule_version)
                self.assertEqual(decision.evaluated_at, application.evaluated_at)
                self.assertEqual(decision.evaluated_inputs["country"], application.country)

    def test_empty_supported_territories_are_advisory(self):
        with override_settings(LOGISTICS_ELIGIBILITY_POLICY={}):
            application = self.submit()
        self.assertEqual(application.status, "APPROVED")
        self.assertIn("UNSUPPORTED_TERRITORY", application.reason_codes)

    def test_strict_mode_restores_review_and_preserves_pilot_history(self):
        application = self.submit(monthly_parcel_estimate=10000, api_integration_needed=True)
        pilot = application.decisions.get()
        with override_settings(LOGISTICS_AUTO_APPROVE_ALL=False):
            strict = reevaluate_application(application.pk, expected_revision=1)
        application.refresh_from_db()
        self.assertEqual(application.status, "UNDER_REVIEW")
        self.assertIsNone(application.approved_revision)
        self.assertEqual(strict.result, strict.evaluated_result)
        self.assertEqual(strict.reason_codes, pilot.reason_codes)
        self.assertFalse(strict.threshold_snapshot["auto_approve_all"])
        pilot.refresh_from_db()
        self.assertEqual(pilot.result, "APPROVED")
        self.assertTrue(pilot.threshold_snapshot["auto_approve_all"])
        reevaluate_application(application.pk, expected_revision=1)
        application.refresh_from_db()
        self.assertEqual(application.status, "APPROVED")

    def test_invalid_and_incomplete_forms_do_not_create_applications_or_decisions(self):
        for changes in (
            {"email": "invalid"},
            {"business_name": ""},
            {"timezone": "Invalid/Timezone"},
            {"monthly_parcel_estimate": "not-a-number"},
            {"monthly_parcel_estimate": -1},
            {"expected_staff_count": 0},
            {"custom_workflow": True, "custom_workflow_details": ""},
            {"current_process_method": "OTHER", "current_process_details": ""},
        ):
            with self.subTest(changes=changes):
                response = self.client.post(
                    reverse("logistics_application_create"), application_data(**changes)
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertEqual(LogisticsApplication.objects.count(), 0)
        self.assertEqual(LogisticsApplicationDecision.objects.count(), 0)

    def test_pilot_approval_can_enroll_with_existing_pending_annual_flow_and_replay_guards(self):
        application = self.submit(
            monthly_parcel_estimate=10000, api_integration_needed=True, country="Unknown territory"
        )
        token = issue_enrollment_link(application.pk, actor=reviewer(), expected_revision=1)
        result = enroll_application(token, password=PASSWORD)
        self.assertEqual(result.business.vertical, "LOGISTICS")
        self.assertEqual(result.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        self.assertEqual(
            result.subscription.billing_interval, BusinessSubscription.BillingInterval.YEARLY
        )
        self.assertIsNone(result.subscription.trial_end)
        with self.assertRaises(PermissionDenied):
            enroll_application(token, password=PASSWORD)
        retry = enroll_application(token, authenticated_user=result.user)
        self.assertTrue(retry.reused)
        self.assertEqual(retry.business.pk, result.business.pk)
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessSubscription.objects.count(), 1)

    def test_material_edit_auto_approves_new_revision_but_revokes_previous_link(self):
        application = self.submit(monthly_parcel_estimate=10000)
        actor = reviewer()
        token = issue_enrollment_link(application.pk, actor=actor, expected_revision=1)
        application.api_integration_needed = True
        application.save()
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(application.approved_revision, 2)
        with self.assertRaises(ValidationError):
            issue_enrollment_link(application.pk, actor=actor, expected_revision=1)
        with self.assertRaises(ValidationError):
            enroll_application(token, password=PASSWORD)
        self.assertEqual(Business.objects.count(), 0)

    def test_existing_identity_and_workspace_conflicts_still_block_enrollment(self):
        user = TaskIOUser.objects.create_user(email="applicant@example.com", password=PASSWORD)
        business = Business.objects.create(name="Existing", slug="existing")
        BusinessUser.objects.create(user=user, business=business, role="OWNER")
        application = self.submit()
        self.assertEqual(application.status, "APPROVED")
        self.assertIn("EXISTING_MOTIONMATE_RELATIONSHIP", application.reason_codes)
        self.assertTrue(application.decisions.get().relationship_snapshot["existing_user"])
        token = issue_enrollment_link(application.pk, actor=reviewer(), expected_revision=1)
        with self.assertRaises(PermissionDenied):
            enroll_application(token, password=PASSWORD)
        with self.assertRaisesMessage(ValidationError, "active workspace"):
            enroll_application(token, authenticated_user=user)
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessSubscription.objects.count(), 0)
        application.refresh_from_db()
        self.assertIsNone(application.converted_at)
        self.assertIsNone(application.enrollment_tokens.get().used_at)

    def test_admin_manual_decisions_remain_authoritative_and_reevaluation_uses_pilot(self):
        application = self.submit(api_integration_needed=True)
        self.client.force_login(reviewer())
        url = reverse("admin:logistics_logisticsapplication_review", args=[application.pk])
        for action, expected in (
            ("DECLINED", "DECLINED"),
            ("APPROVED", "APPROVED"),
            ("REEVALUATE", "APPROVED"),
            ("WITHDRAWN", "WITHDRAWN"),
        ):
            with self.subTest(action=action):
                response = self.client.post(
                    url, {"action": action, "reason": "Reviewed operation", "expected_revision": 1}
                )
                self.assertEqual(response.status_code, 302)
                application.refresh_from_db()
                self.assertEqual(application.status, expected)
                self.assertEqual(application.decisions.first().evaluated_result, "UNDER_REVIEW")
        with self.assertRaises(ValidationError):
            reevaluate_application(application.pk)
        self.assertEqual(Business.objects.count(), 0)
