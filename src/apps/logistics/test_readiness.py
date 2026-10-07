import json
import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.cache import caches
from django.core.checks import run_checks
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.business_data_inventory import build_business_data_inventory
from apps.businesses.business_data_purge import BusinessPurgeError, purge_business
from apps.businesses.models import (
    Business,
    BusinessDataOperation,
    BusinessSubscription,
    ClarivoPlan,
)
from apps.businesses.onboarding import get_onboarding_status
from apps.businesses.test_logistics_billing import stripe_settings
from apps.crm.models import Client

from .checks import check_logistics_deployment, check_logistics_plan
from .enrollment import enroll_application, inspect_enrollment_link
from .inventory import application_inventory
from .models import LogisticsApplication, Parcel, ParcelEvent, Shipment
from .parcel_services import change_parcel_status, parcels_for_business, register_parcel
from .policy import LogisticsEligibilityPolicy, LogisticsUsageReviewPolicy
from .public_tracking import allow_tracking_lookup, lookup_public_tracking
from .shipment_services import (
    assign_parcel,
    change_shipment_status,
    create_shipment,
    generate_manifest,
)
from .test_checkout import TEST_PRICE, LogisticsCheckoutFixture
from .tests import PILOT_POLICY, application_data
from .usage import logistics_operational_summary


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, **stripe_settings())
class LogisticsReadinessFlowTests(LogisticsCheckoutFixture, TestCase):
    def create_application(self):
        # Keep the reviewed/token enrollment path covered alongside direct signup.
        response = self.client.post(
            reverse("logistics_application_create"),
            {**application_data(), "use_existing_account": "on"},
        )
        self.assertRedirects(response, reverse("logistics_application_received"))
        application = LogisticsApplication.objects.get()
        self.assertEqual(application.status, "APPROVED")
        self.assertEqual(application.approved_revision, application.revision)
        self.assertEqual(application.decisions.count(), 1)
        return application

    def command(self, name, **options):
        output = StringIO()
        call_command(name, business_id=self.business.pk, stdout=output, **options)
        return output.getvalue()

    def test_application_to_paid_workspace_parcels_shipments_and_closure(self):
        self.assertEqual(self.business.vertical, "LOGISTICS")
        self.assertEqual(self.subscription.status, "pending_checkout")
        self.assertEqual(self.subscription.billing_interval, "yearly")
        self.assertIsNone(self.subscription.trial_start)
        self.assertFalse(self.subscription.has_access)
        self.login()
        self.assertRedirects(
            self.client.get(reverse("logistics_parcel_list")), reverse("business_subscription")
        )
        response = self.client.post(
            reverse("logistics_application_checkout", args=[self.application.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://checkout.stripe.test/logistics")
        self.assertNotIn(
            "trial_period_days", self.sessions.create.call_args.kwargs["subscription_data"]
        )
        # Return URLs and even a provider-completed session cannot activate access.
        self.client.get(reverse("billing_checkout_success"))
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "pending_checkout")
        self.assertEqual(self.webhook().status_code, 200)
        self.assertEqual(self.webhook().status_code, 200)
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.has_access)
        self.assertEqual(self.subscription.provider_customer_id, "cus_logistics")
        self.assertEqual(self.subscription.provider_subscription_id, "sub_logistics")
        self.assertEqual(self.client.get(reverse("agent_dashboard")).status_code, 200)
        onboarding = get_onboarding_status(user=self.user, business=self.business)
        self.assertTrue(onboarding["visible"])
        self.assertEqual(self.client.get(reverse("staff_client_create")).status_code, 200)
        customer = Client.objects.create(
            business=self.business,
            first_name="Pilot",
            last_name="Customer",
            email="PRIVATE@example.test",
            phone="PRIVATE-PHONE",
            street_address="PRIVATE-ADDRESS",
        )
        response = self.client.post(
            reverse("logistics_parcel_register"),
            {
                "client": customer.pk,
                "origin": "PRIVATE-ORIGIN",
                "destination": "PRIVATE-DESTINATION",
                "package_description": "PRIVATE-PACKAGE",
                "quantity": 1,
                "idempotency_key": uuid.uuid4(),
            },
        )
        self.assertEqual(response.status_code, 302)
        parcel = Parcel.objects.get(business=self.business)
        self.assertEqual(ParcelEvent.objects.filter(parcel=parcel).count(), 1)
        change_parcel_status(
            business=self.business,
            parcel=parcel,
            actor=self.user,
            status="RECEIVED",
            public_message="Parcel received.",
            internal_note="PRIVATE-NOTE",
        )
        projection = lookup_public_tracking(parcel.tracking_code)
        self.assertEqual(projection["status"], "RECEIVED")
        self.assertNotIn("PRIVATE", json.dumps(projection))
        public = self.client.post(
            reverse("logistics_public_tracking"), {"tracking_code": parcel.tracking_code}
        )
        self.assertEqual(public.status_code, 200)
        self.assertNotContains(public, "PRIVATE")
        shipment = create_shipment(
            business=self.business, actor=self.user, origin="Miami", destination="Sint Maarten"
        )
        assign_parcel(business=self.business, shipment=shipment, parcel=parcel, actor=self.user)
        for state in ("READY", "IN_TRANSIT", "ARRIVED"):
            change_shipment_status(
                business=self.business, shipment=shipment, actor=self.user, status=state
            )
        for state in ("READY", "DELIVERED"):
            change_parcel_status(
                business=self.business,
                parcel=parcel,
                actor=self.user,
                status=state,
                public_message=f"Parcel {state.lower()}.",
            )
        change_shipment_status(
            business=self.business, shipment=shipment, actor=self.user, status="COMPLETED"
        )
        manifest = generate_manifest(business=self.business, shipment=shipment, actor=self.user)
        self.assertEqual(manifest["parcel_count"], 1)
        self.assertEqual(manifest["parcels"][0]["tracking_code"], parcel.tracking_code)
        self.assertEqual(
            self.client.get(reverse("logistics_shipment_manifest", args=[shipment.pk])).status_code,
            200,
        )
        summary = json.loads(self.command("inspect_business_data", output_format="json"))
        self.assertEqual(summary["logistics"]["usage"]["completed_shipments"], 1)
        self.assertEqual(summary["logistics"]["usage"]["delivered_parcels_this_month"], 1)
        self.command(
            "deactivate_business",
            execute=True,
            confirm_business_id=self.business.pk,
            reason_reference="PILOT-QA",
        )
        self.assertTrue(Parcel.objects.filter(pk=parcel.pk).exists())
        self.assertTrue(Shipment.objects.filter(pk=shipment.pk).exists())
        self.assertIsNone(lookup_public_tracking(parcel.tracking_code))
        with self.assertRaises(PermissionDenied):
            parcels_for_business(business=self.business, actor=self.user)
        self.assertIn("stripe_references_present", self.command("purge_business"))
        with self.assertRaisesMessage(CommandError, "stripe_references_present"):
            self.command(
                "purge_business",
                execute=True,
                confirm_business_id=self.business.pk,
                reason_reference="PILOT-QA",
            )
        self.assertTrue(
            LogisticsApplication.objects.filter(
                pk=self.application.pk, business=self.business
            ).exists()
        )

    def test_unpaid_converted_tenant_purge_retains_application_decisions_grants_and_users(self):
        self.application.refresh_from_db()
        token = self.application.enrollment_tokens.get()
        decisions = list(self.application.decisions.values())
        self.command(
            "deactivate_business",
            execute=True,
            confirm_business_id=self.business.pk,
            reason_reference="PILOT-QA",
        )
        preview = self.command("purge_business", delete_eligible_users=True)
        self.assertIn("logistics_application", preview)
        self.assertIsNotNone(LogisticsApplication.objects.get(pk=self.application.pk).business_id)
        self.command(
            "purge_business",
            execute=True,
            confirm_business_id=self.business.pk,
            reason_reference="PILOT-QA",
            delete_eligible_users=True,
        )
        self.application.refresh_from_db()
        token.refresh_from_db()
        self.assertIsNone(self.application.business_id)
        self.assertEqual(self.application.business_id_snapshot, self.business.pk)
        self.assertEqual(self.application.enrolled_user_id, self.user.pk)
        self.assertEqual(list(self.application.decisions.values()), decisions)
        self.assertIsNotNone(token.revoked_at)
        self.assertTrue(TaskIOUser.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(
            BusinessDataOperation.objects.filter(
                business_id_snapshot=self.business.pk, mode="purge", status="completed"
            ).exists()
        )
        inventory = application_inventory(self.application.pk)
        self.assertTrue(inventory["business_purged"])
        self.assertFalse(inventory["subscription_link_present"])
        with self.assertRaises(ProtectedError):
            self.user.delete()
        self.login()
        self.assertEqual(
            self.client.post(
                reverse("logistics_application_checkout", args=[self.application.pk])
            ).status_code,
            409,
        )

    def test_retention_release_rolls_back_with_failed_purge(self):
        self.command(
            "deactivate_business",
            execute=True,
            confirm_business_id=self.business.pk,
            reason_reference="PILOT-QA",
        )
        before = list(self.application.enrollment_tokens.values())
        with patch(
            "apps.businesses.business_data_purge._verify_purge_complete", side_effect=RuntimeError
        ):
            with self.assertRaises(BusinessPurgeError):
                purge_business(business_id=self.business.pk, reason_reference="PILOT-QA")
        self.application.refresh_from_db()
        self.assertEqual(self.application.business_id, self.business.pk)
        self.assertEqual(list(self.application.enrollment_tokens.values()), before)
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())
        self.assertTrue(
            BusinessDataOperation.objects.filter(mode="purge", status="failed").exists()
        )

    def test_purged_conversion_cannot_issue_access_through_an_old_enrollment_grant(self):
        from .enrollment import _digest, issue_enrollment_link

        # A second legacy grant with no revoked_at must also remain unusable.
        secret = "legacy-grant-secret-" + "a" * 40
        self.application.enrollment_tokens.create(
            token_digest=_digest(secret),
            application_revision=1,
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.command(
            "deactivate_business",
            execute=True,
            confirm_business_id=self.business.pk,
            reason_reference="PILOT-QA",
        )
        purge_business(business_id=self.business.pk, reason_reference="PILOT-QA")
        for action in (
            lambda: inspect_enrollment_link(secret),
            lambda: enroll_application(secret, authenticated_user=self.user),
            lambda: issue_enrollment_link(
                self.application.pk, actor=self.actor, expected_revision=1
            ),
        ):
            with self.assertRaises(ValidationError):
                action()
        self.assertFalse(Business.objects.filter(pk=self.business.pk).exists())

    def test_conversion_snapshot_cannot_be_client_forged_or_overwritten_by_purge(self):
        self.application.refresh_from_db()
        self.application.business_id_snapshot = self.business.pk + 100
        with self.assertRaises(ValidationError):
            self.application.save()
        self.command(
            "deactivate_business",
            execute=True,
            confirm_business_id=self.business.pk,
            reason_reference="PILOT-QA",
        )
        LogisticsApplication.objects.filter(pk=self.application.pk).update(
            business_id_snapshot=self.business.pk + 100
        )
        for engine in (
            "django.contrib.sessions.backends.db",
            "django.contrib.sessions.backends.signed_cookies",
        ):
            with self.subTest(session_engine=engine), override_settings(SESSION_ENGINE=engine):
                inventory = build_business_data_inventory(self.business)
                self.assertTrue(inventory.summary.cross_tenant_integrity_blocker_count)
                self.assertTrue(
                    any(
                        check.check_code == "cross_tenant_logistics_conversion_snapshot"
                        and check.affected_count == 1
                        for check in inventory.integrity_checks
                    )
                )
        with self.assertRaises(BusinessPurgeError) as error:
            purge_business(business_id=self.business.pk, reason_reference="PILOT-QA")
        self.assertEqual(error.exception.error_code, "cross_tenant_integrity_blockers")
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())


@override_settings(
    LOGISTICS_DEPLOYMENT_CHECKS_ENABLED=True,
    LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY,
    LOGISTICS_USAGE_REVIEW_POLICY=LogisticsUsageReviewPolicy(),
    LOGISTICS_TRACKING_CACHE_ALIAS="logistics_tracking",
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "logistics_tracking": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": "redis://127.0.0.1:6379/1",
        },
    },
    **stripe_settings(),
)
class LogisticsDeploymentChecksTests(TestCase):
    def setUp(self):
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.regional_prices = {
            currency: {"currency": currency.upper(), "yearly": str(TEST_PRICE)}
            for currency in ("usd", "eur")
        }
        plan.save(update_fields=["is_active", "regional_prices"])

    def checks(self):
        # Availability of the optional client dependency is tested separately;
        # readiness checks are static and must not contact a cache/provider.
        with patch("apps.logistics.checks.find_spec", return_value=object()):
            return run_checks(
                tags=["logistics"], include_deployment_checks=True, databases=["default"]
            )

    def test_configured_pilot_has_no_errors_and_checks_make_no_provider_calls(self):
        with patch("apps.logistics.billing.configure_stripe_sdk") as sdk:
            issues = self.checks()
        self.assertFalse([issue for issue in issues if issue.id.startswith("logistics.E")])
        self.assertEqual({issue.id for issue in issues}, {"logistics.W001", "logistics.W002"})
        sdk.assert_not_called()

    def test_checks_are_opt_in_and_leave_service_deployment_checks_unchanged(self):
        with override_settings(LOGISTICS_DEPLOYMENT_CHECKS_ENABLED=False, STRIPE_ENABLED=False):
            self.assertEqual(check_logistics_deployment(None), [])
            self.assertEqual(check_logistics_plan(None, databases=["default"]), [])
        self.assertFalse(run_checks(tags=["logistics"], databases=["default"]))

    def test_missing_payment_price_and_plan_activation_fail_closed(self):
        cases = (
            ({"STRIPE_ENABLED": False}, "logistics.E001"),
            ({"STRIPE_SECRET_KEY": ""}, "logistics.E002"),
            (
                {"STRIPE_PRICE_ID_MAP": stripe_settings(logistics=False)["STRIPE_PRICE_ID_MAP"]},
                "logistics.E011",
            ),
        )
        for settings_change, code in cases:
            with self.subTest(code=code), override_settings(**settings_change):
                self.assertIn(code, {issue.id for issue in self.checks()})
        ClarivoPlan.objects.filter(slug="logistics").update(is_active=False)
        self.assertIn("logistics.E010", {issue.id for issue in self.checks()})

    def test_unpriced_currency_and_pending_migrations_are_reported(self):
        ClarivoPlan.objects.filter(slug="logistics").update(regional_prices={})
        self.assertIn("logistics.E012", {issue.id for issue in self.checks()})
        with patch(
            "django.db.migrations.executor.MigrationExecutor.migration_plan",
            return_value=[object()],
        ):
            self.assertIn("logistics.E009", {issue.id for issue in self.checks()})

    def test_allowlist_and_typed_thresholds_are_required(self):
        with override_settings(LOGISTICS_ELIGIBILITY_POLICY=LogisticsEligibilityPolicy()):
            self.assertIn("logistics.E003", {issue.id for issue in self.checks()})
        with override_settings(LOGISTICS_ELIGIBILITY_POLICY={"auto_approve_monthly_parcels": 9000}):
            self.assertIn("logistics.E004", {issue.id for issue in self.checks()})

    def test_local_cache_missing_client_and_invalid_token_lifetime_are_reported(self):
        with override_settings(LOGISTICS_TRACKING_CACHE_ALIAS="default"):
            self.assertIn("logistics.E006", {issue.id for issue in self.checks()})
        with patch("apps.logistics.checks.find_spec", return_value=None):
            self.assertIn(
                "logistics.E007", {issue.id for issue in check_logistics_deployment(None)}
            )
        with patch("apps.logistics.checks.TOKEN_LIFETIME", timedelta(0)):
            self.assertIn("logistics.E005", {issue.id for issue in self.checks()})

    @override_settings(LOGISTICS_TRACKING_CLIENT_IP_MODE="heroku")
    def test_heroku_proxy_contract_requires_platform_environment(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIn("logistics.E015", {issue.id for issue in self.checks()})
        with patch.dict("os.environ", {"DYNO": "web.1"}):
            self.assertNotIn("logistics.E015", {issue.id for issue in self.checks()})
            self.assertNotIn("logistics.W002", {issue.id for issue in self.checks()})

    def test_tracking_uses_configured_shared_cache_alias_and_failure_denies(self):
        shared = caches["logistics_tracking"]
        with patch.object(shared, "add", return_value=True) as add:
            self.assertTrue(allow_tracking_lookup("192.0.2.1"))
        self.assertTrue(add.called)
        with patch.object(shared, "add", side_effect=RuntimeError):
            self.assertFalse(allow_tracking_lookup("192.0.2.1"))
        with override_settings(LOGISTICS_TRACKING_CACHE_ALIAS="missing"):
            self.assertFalse(allow_tracking_lookup("192.0.2.1"))


@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY, **stripe_settings())
class LogisticsPerformanceSanityTests(LogisticsCheckoutFixture, TestCase):
    def setUp(self):
        super().setUp()
        BusinessSubscription.objects.filter(pk=self.subscription.pk).update(
            status="active", current_period_end=timezone.now() + timedelta(days=365)
        )
        self.customer = Client.objects.create(
            business=self.business, first_name="Pilot", last_name="Customer"
        )
        self.shipment = create_shipment(
            business=self.business, actor=self.user, origin="Miami", destination="Sint Maarten"
        )

    def add_parcel(self):
        parcel = register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            origin="Miami",
            destination="Sint Maarten",
            package_description="Books",
        )
        assign_parcel(
            business=self.business, actor=self.user, shipment=self.shipment, parcel=parcel
        )
        return parcel

    def queries(self, action):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            action()
        return len(captured)

    def test_manifest_inspection_and_usage_queries_do_not_grow_per_parcel(self):
        self.add_parcel()
        actions = (
            lambda: generate_manifest(
                business=self.business, actor=self.user, shipment=self.shipment
            ),
            lambda: logistics_operational_summary(business=self.business),
            lambda: build_business_data_inventory(self.business),
        )
        before = [self.queries(action) for action in actions]
        for _ in range(5):
            self.add_parcel()
        self.assertEqual(before, [self.queries(action) for action in actions])
        self.assertLessEqual(before[1], 10)

    def test_public_timeline_query_count_does_not_grow_per_event(self):
        parcel = self.add_parcel()
        before = self.queries(lambda: lookup_public_tracking(parcel.tracking_code))
        from .parcel_services import record_parcel_event

        for _ in range(8):
            record_parcel_event(
                business=self.business, actor=self.user, parcel=parcel, public_message="Update."
            )
        self.assertEqual(before, self.queries(lambda: lookup_public_tracking(parcel.tracking_code)))
        self.assertLessEqual(before, 4)

    def test_dashboard_and_operational_pages_have_no_per_row_queries(self):
        parcel = self.add_parcel()
        self.login()
        urls = [
            reverse("agent_dashboard"),
            reverse("logistics_parcel_list"),
            reverse("logistics_parcel_detail", args=[parcel.pk]),
            reverse("logistics_shipment_detail", args=[self.shipment.pk]),
            reverse("logistics_shipment_manifest", args=[self.shipment.pk]),
        ]
        actions = [lambda url=url: self.client.get(url) for url in urls]
        for action in actions:
            self.assertEqual(action().status_code, 200)
        before = [self.queries(action) for action in actions]
        for _ in range(5):
            self.add_parcel()
        self.assertEqual(before, [self.queries(action) for action in actions])
