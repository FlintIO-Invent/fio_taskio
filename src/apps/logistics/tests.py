import json
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from pydantic import ValidationError as ConfigurationValidationError

from apps.accounts.models import TaskIOUser
from apps.businesses.business_data_inventory import find_unregistered_direct_business_relations
from apps.businesses.models import Business, BusinessSubscription

from .eligibility import ReasonCode, RelationshipSignals, evaluate_eligibility
from .forms import LogisticsApplicationForm
from .inventory import application_inventory
from .models import LogisticsApplication, LogisticsApplicationDecision
from .policy import LogisticsEligibilityPolicy
from .services import reevaluate_application, review_application

PILOT_POLICY = LogisticsEligibilityPolicy(supported_territories=("Netherlands",))


def application_data(**changes):
    values = {
        "business_name": "Pilot Parcel Company",
        "trading_name": "",
        "contact_first_name": "Jane",
        "contact_last_name": "Doe",
        "email": "applicant@example.com",
        "phone": "+31 20 123 4567",
        "whatsapp": "",
        "country": "Netherlands",
        "business_address": "Herengracht 1, 1015 AB Amsterdam",
        "registration_number": "KVK12345",
        "website": "",
        "preferred_currency": "EUR",
        "timezone": "Europe/Amsterdam",
        "operation_type": "COURIER",
        "routes": "Amsterdam to Rotterdam",
        "monthly_parcel_estimate": 800,
        "expected_staff_count": 5,
        "location_count": 1,
        "current_process_method": "SPREADSHEETS",
        "current_process_details": "",
        "customer_tracking_needed": True,
        "manifest_needed": True,
        "api_integration_needed": False,
        "custom_workflow": False,
        "custom_workflow_details": "",
        "multi_jurisdiction": False,
        "custom_pricing_requested": False,
        "operational_notes": "",
    }
    values.update(changes)
    return values


class EligibilityTests(SimpleTestCase):
    def test_simple_application_and_middle_band_approve_at_boundaries(self):
        for volume in (0, 1000, 1001, 2500, 5000):
            with self.subTest(volume=volume):
                decision = evaluate_eligibility(
                    application_data(monthly_parcel_estimate=volume), PILOT_POLICY
                )
                self.assertEqual(decision.result, "APPROVED")
                self.assertEqual(decision.reason_codes, ())
                self.assertEqual(decision.resource_classification, "STANDARD")

    def test_all_review_triggers_have_stable_machine_readable_reasons(self):
        cases = (
            ({"monthly_parcel_estimate": 5001}, ReasonCode.HIGH_MONTHLY_VOLUME),
            ({"expected_staff_count": 11}, ReasonCode.HIGH_STAFF_COUNT),
            ({"location_count": 2}, ReasonCode.MULTI_BRANCH),
            (
                {"custom_workflow": True, "custom_workflow_details": "Special process"},
                ReasonCode.CUSTOM_WORKFLOW,
            ),
            ({"custom_workflow_details": "Special process"}, ReasonCode.CUSTOM_WORKFLOW),
            ({"multi_jurisdiction": True}, ReasonCode.MULTI_JURISDICTION),
            ({"api_integration_needed": True}, ReasonCode.API_INTEGRATION_REQUIRED),
            ({"custom_pricing_requested": True}, ReasonCode.CUSTOM_PRICING_REQUESTED),
            ({"registration_number": ""}, ReasonCode.INCOMPLETE_BUSINESS_REGISTRATION),
            ({"country": "Unknown territory"}, ReasonCode.UNSUPPORTED_TERRITORY),
            ({"monthly_parcel_estimate": 10000}, ReasonCode.HIGH_RESOURCE_INTENSITY),
            ({"operation_type": "OTHER"}, ReasonCode.HIGH_RESOURCE_INTENSITY),
            ({"current_process_method": "OTHER"}, ReasonCode.HIGH_RESOURCE_INTENSITY),
        )
        for changes, reason in cases:
            with self.subTest(reason=reason, changes=changes):
                decision = evaluate_eligibility(application_data(**changes), PILOT_POLICY)
                self.assertEqual(decision.result, "UNDER_REVIEW")
                self.assertIn(reason, decision.reason_codes)

    def test_middle_band_with_complexity_and_unknown_process_review(self):
        decision = evaluate_eligibility(
            application_data(monthly_parcel_estimate=1001, api_integration_needed=True),
            PILOT_POLICY,
        )
        self.assertEqual(decision.result, "UNDER_REVIEW")
        self.assertIn("HIGH_RESOURCE_INTENSITY", decision.reason_codes)
        unknown = evaluate_eligibility(application_data(operation_type="OTHER"), PILOT_POLICY)
        self.assertEqual(unknown.resource_classification, "UNKNOWN")

    def test_relationships_review_without_exposing_or_merging_identity(self):
        for signals, reason in (
            (RelationshipSignals(existing_user=True), ReasonCode.EXISTING_MOTIONMATE_RELATIONSHIP),
            (RelationshipSignals(existing_business=True), ReasonCode.POSSIBLE_DUPLICATE),
            (RelationshipSignals(duplicate_application=True), ReasonCode.POSSIBLE_DUPLICATE),
        ):
            decision = evaluate_eligibility(application_data(), PILOT_POLICY, signals)
            self.assertEqual(decision.result, "UNDER_REVIEW")
            self.assertIn(reason, decision.reason_codes)

    def test_configured_thresholds_and_registration_policy_apply(self):
        policy = LogisticsEligibilityPolicy(
            supported_territories=("Netherlands",),
            auto_approve_staff_count=12,
            auto_approve_location_count=2,
            registration_required_for_auto_approval=False,
        )
        decision = evaluate_eligibility(
            application_data(expected_staff_count=12, location_count=2, registration_number=""),
            policy,
        )
        self.assertEqual(decision.result, "APPROVED")

    def test_empty_territory_configuration_reviews_and_country_normalization_is_stable(self):
        self.assertEqual(
            evaluate_eligibility(application_data(), LogisticsEligibilityPolicy()).result,
            "UNDER_REVIEW",
        )
        decision = evaluate_eligibility(application_data(country="  NETHERLANDS  "), PILOT_POLICY)
        self.assertEqual(decision.result, "APPROVED")

    def test_evaluation_is_deterministic_and_reason_order_is_stable(self):
        inputs = application_data(
            monthly_parcel_estimate=10000, api_integration_needed=True, expected_staff_count=50
        )
        first = evaluate_eligibility(inputs, PILOT_POLICY)
        self.assertEqual(first, evaluate_eligibility(inputs, PILOT_POLICY))
        self.assertEqual(
            first.reason_codes,
            (
                "HIGH_MONTHLY_VOLUME",
                "HIGH_STAFF_COUNT",
                "API_INTEGRATION_REQUIRED",
                "HIGH_RESOURCE_INTENSITY",
            ),
        )

    def test_invalid_config_is_rejected_and_environment_pattern_is_typed(self):
        with self.assertRaises(ConfigurationValidationError):
            LogisticsEligibilityPolicy(auto_approve_monthly_parcels=6000)
        with self.assertRaises(ConfigurationValidationError):
            LogisticsEligibilityPolicy(auto_approve_location_count=0)
        from config import Settings

        config = Settings(
            _env_file=None,
            logistics_supported_territories='["Netherlands", "Sint Maarten"]',
            logistics_auto_approve_staff_count="12",
        )
        self.assertEqual(config.logistics_supported_territories, ["Netherlands", "Sint Maarten"])
        self.assertEqual(config.logistics_auto_approve_staff_count, 12)


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY)
class ApplicationLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reviewer = TaskIOUser.objects.create_user(
            email="reviewer@example.com", password="testpass123", is_staff=True
        )
        cls.reviewer.user_permissions.add(
            Permission.objects.get(codename="change_logisticsapplication")
        )

    def create_application(self, **changes):
        return LogisticsApplication.objects.create(**application_data(**changes))

    def test_model_statuses_are_application_only_and_simple_submission_approves(self):
        self.assertEqual(
            set(LogisticsApplication.Status.values),
            {"SUBMITTED", "APPROVED", "UNDER_REVIEW", "DECLINED", "WITHDRAWN"},
        )
        application = self.create_application()
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(application.approved_revision, 1)
        self.assertEqual(application.evaluated_revision, 1)
        self.assertEqual(application.decisions.count(), 1)
        self.assertFalse(
            any(
                "payment" in field.name or "subscription" in field.name
                for field in application._meta.fields
            )
        )

    def test_reason_config_and_operational_input_snapshots_persist(self):
        application = self.create_application(
            monthly_parcel_estimate=6000, api_integration_needed=True
        )
        self.assertEqual(application.status, "UNDER_REVIEW")
        self.assertIn("HIGH_MONTHLY_VOLUME", application.reason_codes)
        self.assertEqual(application.rule_version, "pilot-v1")
        self.assertEqual(application.threshold_snapshot, PILOT_POLICY.model_dump(mode="json"))
        decision = application.decisions.get()
        self.assertEqual(decision.reason_codes, application.reason_codes)
        self.assertEqual(decision.application_revision, 1)
        self.assertEqual(decision.evaluated_inputs["monthly_parcel_estimate"], 6000)
        self.assertNotIn("email", decision.evaluated_inputs)
        self.assertNotIn("business_address", decision.evaluated_inputs)
        self.assertIsNotNone(decision.evaluated_at)

    def test_existing_user_email_reviews_case_insensitively(self):
        TaskIOUser.objects.create_user(email="Applicant@Example.com", password="testpass123")
        application = self.create_application(email="APPLICANT@example.com")
        self.assertEqual(application.status, "UNDER_REVIEW")
        self.assertIn("EXISTING_MOTIONMATE_RELATIONSHIP", application.reason_codes)

    def test_existing_business_and_trading_name_review(self):
        Business.objects.create(name="Existing parcel company", slug="existing-parcel")
        application = self.create_application(trading_name="Existing Parcel Company")
        self.assertEqual(application.status, "UNDER_REVIEW")
        self.assertIn("POSSIBLE_DUPLICATE", application.reason_codes)

    def test_duplicate_email_name_and_company_number_review(self):
        self.create_application()
        cases = (
            {"business_name": "Other Company", "registration_number": "OTHER"},
            {
                "email": "other@example.com",
                "business_name": "Pilot, Parcel Company!",
                "registration_number": "OTHER",
            },
            {
                "email": "other@example.com",
                "business_name": "Other Company",
                "registration_number": "KVK 12345",
            },
        )
        for changes in cases:
            with self.subTest(changes=changes):
                application = self.create_application(**changes)
                self.assertEqual(application.status, "UNDER_REVIEW")
                self.assertIn("POSSIBLE_DUPLICATE", application.reason_codes)

    def test_declined_application_does_not_block_new_submission(self):
        application = self.create_application()
        review_application(
            application.pk,
            result="DECLINED",
            actor=self.reviewer,
            reason="Applicant requested closure",
            expected_revision=1,
        )
        self.assertEqual(self.create_application().status, "APPROVED")

    def test_manual_approve_and_decline_record_actor_time_reason_and_revision(self):
        application = self.create_application(api_integration_needed=True)
        approved = review_application(
            application.pk,
            result="APPROVED",
            actor=self.reviewer,
            reason="Integration scope reviewed",
            expected_revision=1,
        )
        application.refresh_from_db()
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(application.approved_revision, 1)
        self.assertEqual(approved.evaluated_result, "UNDER_REVIEW")
        self.assertEqual(approved.source, "MANUAL")
        self.assertEqual(approved.actor, self.reviewer)
        self.assertEqual(approved.actor_identifier, self.reviewer.pk)
        self.assertEqual(approved.override_reason, "Integration scope reviewed")
        self.assertIsNotNone(approved.evaluated_at)
        declined = review_application(
            application.pk,
            result="DECLINED",
            actor=self.reviewer,
            reason="Unable to support requested scope",
            expected_revision=1,
        )
        application.refresh_from_db()
        self.assertEqual(application.status, "DECLINED")
        self.assertIsNone(application.approved_revision)
        self.assertEqual(declined.result, "DECLINED")
        self.assertEqual(application.decisions.count(), 3)

    def test_material_edit_after_manual_approval_reevaluates_and_clears_approval(self):
        application = self.create_application(monthly_parcel_estimate=6000)
        review_application(
            application.pk,
            result="APPROVED",
            actor=self.reviewer,
            reason="Pilot exception",
            expected_revision=1,
        )
        application.refresh_from_db()
        application.monthly_parcel_estimate = 10000
        application.save(update_fields=["monthly_parcel_estimate"])
        self.assertEqual(application.revision, 2)
        self.assertEqual(application.evaluated_revision, 2)
        self.assertEqual(application.status, "UNDER_REVIEW")
        self.assertIsNone(application.approved_revision)
        self.assertEqual(application.decisions.count(), 3)
        self.assertEqual(application.decisions.first().source, "AUTOMATIC")

    def test_simple_material_edit_approves_only_new_revision(self):
        application = self.create_application()
        application.phone = "+31 20 234 5678"
        application.save()
        self.assertEqual(application.revision, 2)
        self.assertEqual(application.approved_revision, 2)
        self.assertEqual(application.decisions.count(), 2)

    def test_unchanged_save_does_not_create_another_evaluation(self):
        application = self.create_application()
        application.save()
        self.assertEqual(application.revision, 1)
        self.assertEqual(application.decisions.count(), 1)

    def test_partial_save_does_not_persist_ignored_identity_edits(self):
        application = self.create_application()
        application.email = "unsaved@example.com"
        application.phone = "+31 20 234 5678"
        application.save(update_fields=["phone"])
        self.assertEqual(application.email, "applicant@example.com")
        self.assertEqual(application.normalized_email, "applicant@example.com")

    def test_reevaluation_uses_new_config_without_rewriting_history(self):
        application = self.create_application()
        policy = LogisticsEligibilityPolicy(
            rule_version="pilot-v2",
            supported_territories=("Netherlands",),
            auto_approve_staff_count=3,
        )
        with override_settings(LOGISTICS_ELIGIBILITY_POLICY=policy):
            reevaluate_application(application.pk, expected_revision=1)
        application.refresh_from_db()
        self.assertEqual(application.status, "UNDER_REVIEW")
        self.assertEqual(application.rule_version, "pilot-v2")
        self.assertEqual(application.decisions.last().rule_version, "pilot-v1")

    def test_manual_review_requires_permission_reason_and_current_revision(self):
        application = self.create_application()
        ordinary = TaskIOUser.objects.create_user(
            email="ordinary@example.com", password="testpass123"
        )
        with self.assertRaises(PermissionDenied):
            review_application(
                application.pk,
                result="APPROVED",
                actor=ordinary,
                reason="Review",
                expected_revision=1,
            )
        with self.assertRaises(ValidationError):
            review_application(
                application.pk,
                result="APPROVED",
                actor=self.reviewer,
                reason=" ",
                expected_revision=1,
            )
        with self.assertRaises(ValidationError):
            review_application(
                application.pk,
                result="APPROVED",
                actor=self.reviewer,
                reason="Review",
                expected_revision=2,
            )
        self.assertEqual(application.decisions.count(), 1)

    def test_direct_decision_injection_and_history_edits_are_rejected(self):
        application = self.create_application(api_integration_needed=True)
        application.status = "APPROVED"
        with self.assertRaises(ValidationError):
            application.save()
        with self.assertRaises(ValidationError):
            self.create_application(status="APPROVED")
        decision = application.decisions.get()
        decision.result = "APPROVED"
        with self.assertRaises(ValidationError):
            decision.save()

    def test_withdrawal_is_audited_and_terminal_without_provisioning(self):
        application = self.create_application()
        decision = review_application(
            application.pk,
            result="WITHDRAWN",
            actor=self.reviewer,
            reason="Applicant withdrew",
            expected_revision=1,
        )
        application.refresh_from_db()
        self.assertEqual(application.status, "WITHDRAWN")
        self.assertIsNone(application.approved_revision)
        self.assertEqual(decision.override_reason, "Applicant withdrew")
        with self.assertRaises(ValidationError):
            reevaluate_application(application.pk)
        application.phone = "+31 20 234 5678"
        with self.assertRaises(ValidationError):
            application.save()
        self.assertEqual(self.create_application().status, "APPROVED")

    def test_reviewer_initiated_reevaluation_records_actor_without_manual_override(self):
        application = self.create_application()
        decision = reevaluate_application(application.pk, actor=self.reviewer, expected_revision=1)
        self.assertEqual(decision.source, "AUTOMATIC")
        self.assertEqual(decision.actor_identifier, self.reviewer.pk)
        self.assertEqual(decision.override_reason, "")

    def test_failed_evaluation_rolls_back_submission_and_history(self):
        with mock.patch(
            "apps.logistics.services.evaluate_eligibility", side_effect=RuntimeError("Rule failure")
        ):
            with self.assertRaises(RuntimeError):
                self.create_application()
        self.assertEqual(LogisticsApplication.objects.count(), 0)
        self.assertEqual(LogisticsApplicationDecision.objects.count(), 0)

    def test_inventory_is_read_only_and_not_a_business_purge_link(self):
        application = self.create_application()
        inventory = application_inventory(application.pk)
        self.assertFalse(inventory["business_purge_owns_application"])
        self.assertFalse(inventory["business_link_present"])
        self.assertEqual(inventory["decision_count"], 1)
        self.assertEqual(find_unregistered_direct_business_relations(), ())
        output = StringIO()
        call_command("inspect_logistics_application", application_id=application.pk, stdout=output)
        self.assertEqual(json.loads(output.getvalue())["application_id"], str(application.pk))
        self.assertNotIn(application.email, output.getvalue())
        with self.assertRaises(ProtectedError):
            application.delete()


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY)
class PublicAndAdminTests(TestCase):
    def test_public_page_is_anonymous_and_includes_csrf(self):
        response = self.client.get(reverse("logistics_application_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "Apply for Motionmate Logistics")

    def test_public_submission_creates_no_account_tenant_subscription_or_checkout(self):
        before = (
            TaskIOUser.objects.count(),
            Business.objects.count(),
            BusinessSubscription.objects.count(),
        )
        with mock.patch(
            "apps.businesses.stripe_checkout._stripe_create_checkout_session"
        ) as checkout:
            response = self.client.post(
                reverse("logistics_application_create"), application_data(), follow=True
            )
        checkout.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Application received")
        self.assertEqual(
            (
                TaskIOUser.objects.count(),
                Business.objects.count(),
                BusinessSubscription.objects.count(),
            ),
            before,
        )
        self.assertEqual(LogisticsApplication.objects.get().status, "APPROVED")

    def test_decision_injection_is_ignored_and_public_response_is_indistinguishable(self):
        first = self.client.post(
            reverse("logistics_application_create"), application_data(), follow=True
        )
        payload = application_data(
            monthly_parcel_estimate=10000,
            status="APPROVED",
            approved_revision=999,
            decision_result="APPROVED",
            reason_codes="[]",
            rule_version="bypass",
        )
        second = self.client.post(reverse("logistics_application_create"), payload, follow=True)
        application = LogisticsApplication.objects.order_by("-created_at").first()
        self.assertEqual(application.status, "UNDER_REVIEW")
        self.assertIsNone(application.approved_revision)
        self.assertEqual(application.rule_version, "pilot-v1")
        self.assertEqual(first.content, second.content)
        self.assertNotContains(second, "HIGH_MONTHLY_VOLUME")
        self.assertNotContains(second, "POSSIBLE_DUPLICATE")

    def test_existing_email_relationship_is_not_publicly_disclosed(self):
        TaskIOUser.objects.create_user(email="applicant@example.com", password="testpass123")
        response = self.client.post(
            reverse("logistics_application_create"), application_data(), follow=True
        )
        self.assertContains(response, "Application received")
        self.assertNotContains(response, "EXISTING_MOTIONMATE_RELATIONSHIP")
        self.assertEqual(TaskIOUser.objects.count(), 1)

    def test_csrf_validation_and_required_fields_reject_invalid_intake(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(reverse("logistics_application_create"), application_data())
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            reverse("logistics_application_create"),
            application_data(email="not-an-email", timezone="Invalid/Timezone"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(LogisticsApplication.objects.count(), 0)

    def test_optional_registration_accepts_intake_but_reviews(self):
        self.client.post(
            reverse("logistics_application_create"), application_data(registration_number="")
        )
        application = LogisticsApplication.objects.get()
        self.assertIn("INCOMPLETE_BUSINESS_REGISTRATION", application.reason_codes)

    def test_form_contains_only_application_input_fields(self):
        self.assertEqual(
            set(LogisticsApplicationForm().fields), set(LogisticsApplication.MATERIAL_FIELDS)
        )

    def test_admin_review_approve_decline_and_reevaluate(self):
        reviewer = TaskIOUser.objects.create_user(
            email="reviewer@example.com", password="testpass123", is_staff=True
        )
        reviewer.user_permissions.add(
            Permission.objects.get(codename="change_logisticsapplication")
        )
        application = LogisticsApplication.objects.create(
            **application_data(api_integration_needed=True)
        )
        self.client.force_login(reviewer)
        change_url = reverse("admin:logistics_logisticsapplication_change", args=[application.pk])
        review_url = reverse("admin:logistics_logisticsapplication_review", args=[application.pk])
        self.assertContains(self.client.get(change_url), "Review decision")
        self.assertContains(self.client.get(review_url), "API_INTEGRATION_REQUIRED")
        for action, expected in (
            ("APPROVED", "APPROVED"),
            ("DECLINED", "DECLINED"),
            ("REEVALUATE", "UNDER_REVIEW"),
        ):
            response = self.client.post(
                review_url,
                {"action": action, "reason": "Reviewed operation", "expected_revision": 1},
            )
            self.assertEqual(response.status_code, 302)
            application.refresh_from_db()
            self.assertEqual(application.status, expected)
        self.assertEqual(application.decisions.count(), 4)

    def test_admin_review_enforces_permissions_reason_and_revision(self):
        application = LogisticsApplication.objects.create(**application_data())
        user = TaskIOUser.objects.create_user(
            email="staff@example.com", password="testpass123", is_staff=True
        )
        self.client.force_login(user)
        url = reverse("admin:logistics_logisticsapplication_review", args=[application.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="change_logisticsapplication"))
        response = self.client.post(
            url, {"action": "DECLINED", "reason": "", "expected_revision": 1}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application.decisions.count(), 1)
        response = self.client.post(
            url, {"action": "DECLINED", "reason": "Review", "expected_revision": 99}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Application details changed")
        self.assertEqual(application.decisions.count(), 1)

    def test_withdrawn_details_are_read_only_in_admin(self):
        reviewer = TaskIOUser.objects.create_user(
            email="withdraw-reviewer@example.com", password="testpass123", is_staff=True
        )
        reviewer.user_permissions.add(
            Permission.objects.get(codename="change_logisticsapplication")
        )
        application = LogisticsApplication.objects.create(**application_data())
        review_application(
            application.pk,
            result="WITHDRAWN",
            actor=reviewer,
            reason="Applicant withdrew",
            expected_revision=1,
        )
        self.client.force_login(reviewer)
        url = reverse("admin:logistics_logisticsapplication_change", args=[application.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="business_name"')
        formset = response.context["inline_admin_formsets"][0].formset
        post_data = {field.html_name: field.value() for field in formset.management_form}
        for inline_form in formset.initial_forms:
            post_data.update(
                {field.html_name: field.value() for field in inline_form.hidden_fields()}
            )
        post_data.update({"business_name": "Injected new name", "_save": "Save"})
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        application.refresh_from_db()
        self.assertEqual(application.business_name, "Pilot Parcel Company")
        self.assertEqual(application.status, "WITHDRAWN")
