import json
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import QuerySet
from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice
from apps.businesses.admin import BusinessAdmin, LogisticsApplicationLinkFilter
from apps.businesses.business_data_inventory import (
    FuturePurgeReadiness,
    build_business_data_inventory,
)
from apps.businesses.business_data_purge import (
    BusinessPurgeError,
    plan_business_purge,
    purge_business,
)
from apps.businesses.models import (
    Business,
    BusinessDataOperation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    DemoSeedRecord,
    DemoSeedRun,
)
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client

from .demo import LOGISTICS_DEMO_COUNTS
from .inventory import application_inventory
from .models import LogisticsApplication, Parcel, ParcelEvent, Shipment
from .parcel_services import parcels_for_business, record_parcel_event, register_parcel
from .policy import LogisticsEligibilityPolicy, LogisticsUsageReviewPolicy
from .public_tracking import lookup_public_tracking
from .shipment_services import assign_parcel, create_shipment, shipments_for_business
from .tests import application_data
from .usage import logistics_operational_summary, logistics_threshold_summary, logistics_usage


class LogisticsOperationsTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Demo courier", slug="ops-courier", vertical="LOGISTICS"
        )
        self.other = Business.objects.create(
            name="Other courier", slug="ops-other", vertical="LOGISTICS"
        )
        self.service = Business.objects.create(name="Service", slug="ops-service")
        plan = ClarivoPlan.objects.get(slug="logistics")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        for business in (self.business, self.other):
            BusinessSubscription.objects.create(
                business=business, plan=plan, status="active", billing_interval="yearly"
            )
        BusinessSubscription.objects.create(
            business=self.service, plan=ClarivoPlan.objects.get(slug="pro"), status="active"
        )
        self.user = TaskIOUser.objects.create_user(email="ops@example.test", password="testpass123")
        self.other_user = TaskIOUser.objects.create_user(
            email="ops-other@example.test", password="testpass123"
        )
        self.member = BusinessUser.objects.create(
            business=self.business, user=self.user, role="owner"
        )
        BusinessUser.objects.create(business=self.other, user=self.other_user, role="owner")
        self.genuine = Client.objects.create(
            business=self.business,
            first_name="Real",
            last_name="Customer",
            email="private@example.test",
        )

    def command(self, name="seed_logistics_demo_data", **options):
        output = StringIO()
        call_command(name, stdout=output, **{"business_id": self.business.pk, **options})
        return output.getvalue()

    def seed(self):
        self.command(execute=True)
        return DemoSeedRun.objects.get(business=self.business)

    def parcel(self, *, business=None, customer=None, actor=None):
        return register_parcel(
            business=business or self.business,
            client=customer or self.genuine,
            actor=actor or self.user,
            origin="Miami",
            destination="Sint Maarten",
            package_description="Genuine books",
        )

    def link_application(self):
        application = LogisticsApplication.objects.create(**application_data())
        LogisticsApplication.objects.filter(pk=application.pk).update(
            business=self.business,
            enrolled_user=self.user,
            converted_at=datetime(2026, 1, 1, tzinfo=UTC),
            converted_revision=application.revision,
        )
        application.refresh_from_db()
        return application

    def inactive(self):
        Business.objects.filter(pk=self.business.pk).update(is_active=False)

    def test_seed_is_dry_run_by_default_and_rejects_service_and_missing_business(self):
        self.assertIn("DRY RUN ONLY", self.command())
        self.assertFalse(DemoSeedRun.objects.exists())
        self.assertFalse(Parcel.objects.exists())
        for business_id in (self.service.pk, 999999, -1):
            with self.subTest(business_id=business_id), self.assertRaises(CommandError):
                self.command(business_id=business_id, execute=True)
        self.assertEqual(Client.objects.count(), 1)

    def test_seed_owns_every_created_record_and_replay_cannot_append(self):
        seed = self.seed()
        counts = {
            "clients": Client.objects.filter(business=self.business)
            .exclude(pk=self.genuine.pk)
            .count(),
            "parcels": Parcel.objects.filter(business=self.business).count(),
            "parcel_events": ParcelEvent.objects.filter(business=self.business).count(),
            "shipments": Shipment.objects.filter(business=self.business).count(),
        }
        self.assertEqual(counts, LOGISTICS_DEMO_COUNTS)
        self.assertEqual(seed.owned_records.count(), sum(counts.values()))
        self.assertFalse(Parcel.objects.filter(business=self.other).exists())
        self.assertFalse(Parcel.objects.exclude(created_by=self.user).exists())
        self.assertFalse(ParcelEvent.objects.exclude(actor=self.user).exists())
        self.assertFalse(Shipment.objects.exclude(created_by=self.user).exists())
        self.assertEqual(Parcel.objects.filter(shipment__isnull=False).count(), 12)
        self.assertEqual(
            set(Shipment.objects.values_list("status", flat=True)),
            set(Shipment.Status.values),
        )
        for model in (Parcel, ParcelEvent, Shipment):
            self.assertEqual(
                set(
                    seed.owned_records.filter(model_label=model._meta.label).values_list(
                        "object_pk", flat=True
                    )
                ),
                {str(pk) for pk in model.objects.values_list("pk", flat=True)},
            )
        with self.assertRaises(CommandError):
            self.command(execute=True)
        self.assertEqual(Parcel.objects.count(), LOGISTICS_DEMO_COUNTS["parcels"])
        self.genuine.refresh_from_db()
        self.assertEqual(self.genuine.email, "private@example.test")

    def test_seed_requires_existing_operator_and_domain_access(self):
        with self.assertRaises(CommandError):
            self.command(actor_id=self.other_user.pk, execute=True)
        self.business.subscription.status = "pending_checkout"
        self.business.subscription.save(update_fields=["status"])
        with self.assertRaises(CommandError):
            self.command(execute=True)
        self.assertFalse(DemoSeedRun.objects.exists())
        self.assertEqual(TaskIOUser.objects.count(), 2)

    def test_seed_failure_rolls_back_clients_and_ownership(self):
        with patch("apps.logistics.demo.create_shipment", side_effect=ValidationError("failed")):
            with self.assertRaises(CommandError):
                self.command(execute=True)
        self.assertEqual(Client.objects.count(), 1)
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(ParcelEvent.objects.exists())
        self.assertFalse(DemoSeedRun.objects.exists())

    def test_reset_preview_then_execute_preserves_genuine_data_and_can_reseed(self):
        self.seed()
        genuine_parcel = self.parcel()
        genuine_shipment = create_shipment(
            business=self.business, actor=self.user, origin="Real", destination="Real"
        )
        self.assertIn("RESET PREVIEW ONLY", self.command(reset_demo=True))
        self.assertEqual(Parcel.objects.count(), LOGISTICS_DEMO_COUNTS["parcels"] + 1)
        self.command(reset_demo=True, execute=True)
        self.assertEqual(list(Parcel.objects.values_list("pk", flat=True)), [genuine_parcel.pk])
        self.assertEqual(list(Shipment.objects.values_list("pk", flat=True)), [genuine_shipment.pk])
        self.assertEqual(ParcelEvent.objects.count(), 1)
        self.assertEqual(list(Client.objects.values_list("pk", flat=True)), [self.genuine.pk])
        self.assertFalse(DemoSeedRun.objects.exists())
        self.assertFalse(DemoSeedRecord.objects.exists())
        self.seed()
        self.assertEqual(Parcel.objects.count(), LOGISTICS_DEMO_COUNTS["parcels"] + 1)

    def test_reset_blocks_genuine_event_on_demo_parcel(self):
        seed = self.seed()
        parcel = Parcel.objects.first()
        event = record_parcel_event(
            business=self.business,
            parcel=parcel,
            actor=self.user,
            internal_note="Real operational history",
        )
        for execute in (False, True):
            with self.assertRaisesMessage(CommandError, "genuine or untracked"):
                self.command(reset_demo=True, execute=execute)
        self.assertTrue(ParcelEvent.objects.filter(pk=event.pk).exists())
        self.assertEqual(seed.owned_records.count(), sum(LOGISTICS_DEMO_COUNTS.values()))

    def test_reset_blocks_genuine_parcel_on_demo_client_or_shipment(self):
        self.seed()
        customer = Client.objects.filter(business=self.business).exclude(pk=self.genuine.pk).first()
        real = self.parcel(customer=customer)
        with self.assertRaisesMessage(CommandError, "genuine or untracked"):
            self.command(reset_demo=True, execute=True)
        self.assertTrue(Parcel.objects.filter(pk=real.pk).exists())
        # Move only the client relation in a corruption fixture, then create an
        # inbound dependency on the demo draft shipment instead.
        QuerySet(model=Parcel, using="default").filter(pk=real.pk).update(client=self.genuine)
        draft = Shipment.objects.get(status="DRAFT")
        assign_parcel(business=self.business, shipment=draft, parcel=real, actor=self.user)
        with self.assertRaisesMessage(CommandError, "genuine or untracked"):
            self.command(reset_demo=True, execute=True)

    def test_reset_blocks_outbound_attachment_to_genuine_shipment(self):
        self.seed()
        shipment = create_shipment(
            business=self.business, actor=self.user, origin="Real", destination="Real"
        )
        parcel = Parcel.objects.filter(current_status="REGISTERED", shipment__isnull=True).first()
        assign_parcel(business=self.business, shipment=shipment, parcel=parcel, actor=self.user)
        with self.assertRaisesMessage(CommandError, "genuine shipment"):
            self.command(reset_demo=True, execute=True)
        self.assertTrue(Shipment.objects.filter(pk=shipment.pk).exists())

    def test_reset_preserves_genuine_crm_dependents(self):
        self.seed()
        customer = Client.objects.filter(business=self.business).exclude(pk=self.genuine.pk).first()
        invoice = Invoice.objects.create(
            business=self.business, client=customer, invoice_number="REAL-1"
        )
        with self.assertRaisesMessage(CommandError, "genuine or untracked"):
            self.command(reset_demo=True, execute=True)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_reset_rejects_cross_tenant_tracking_and_other_seed_claims(self):
        seed = self.seed()
        foreign = Client.objects.create(business=self.other, first_name="Other", last_name="Real")
        record = DemoSeedRecord.objects.create(
            seed_run=seed, model_label="crm.Client", object_pk=str(foreign.pk)
        )
        with self.assertRaisesMessage(CommandError, "does not belong"):
            self.command(reset_demo=True, execute=True)
        record.delete()
        other_seed = DemoSeedRun.objects.create(business=self.other)
        DemoSeedRecord.objects.create(
            seed_run=other_seed,
            model_label="logistics.Parcel",
            object_pk=str(Parcel.objects.first().pk),
        )
        with self.assertRaisesMessage(CommandError, "also claims"):
            self.command(reset_demo=True, execute=True)
        self.assertTrue(Client.objects.filter(pk=foreign.pk).exists())

    def test_reset_does_not_adopt_service_seed_metadata_and_works_when_inactive(self):
        seed = DemoSeedRun.objects.create(business=self.business)
        DemoSeedRecord.objects.create(seed_run=seed, model_label="crm.Lead", object_pk="1")
        with self.assertRaisesMessage(CommandError, "unsupported"):
            self.command(reset_demo=True, execute=True)
        seed.delete()
        self.seed()
        self.inactive()
        self.command(reset_demo=True, execute=True)
        self.assertFalse(Parcel.objects.exists())
        self.assertTrue(Client.objects.filter(pk=self.genuine.pk).exists())

    def test_inspection_is_private_additive_and_includes_counts_plan_statuses(self):
        self.seed()
        application = self.link_application()
        output = self.command("inspect_business_data", output_format="json")
        inventory = json.loads(output)
        self.assertEqual(inventory["selected_business"]["vertical"], "LOGISTICS")
        summary = inventory["logistics"]
        self.assertEqual(summary["plan"], "logistics")
        self.assertEqual(summary["billing_interval"], "yearly")
        self.assertEqual(summary["application"]["id"], str(application.pk))
        self.assertEqual(summary["usage"]["parcels"], LOGISTICS_DEMO_COUNTS["parcels"])
        self.assertEqual(summary["usage"]["parcel_events"], LOGISTICS_DEMO_COUNTS["parcel_events"])
        self.assertEqual(summary["usage"]["active_shipments"], 4)
        self.assertEqual(summary["usage"]["completed_shipments"], 1)
        self.assertEqual(summary["usage"]["parcel_status_summary"]["DELIVERED"], 3)
        for private in (application.email, application.business_address, self.genuine.email):
            self.assertNotIn(private, output)
        self.assertIn("Logistics operational summary", self.command("inspect_business_data"))
        service = json.loads(
            self.command("inspect_business_data", business_id=self.service.pk, output_format="json")
        )
        self.assertEqual(service["selected_business"]["vertical"], "SERVICE")
        self.assertNotIn("logistics", service)
        self.assertIn("billing_assessment", service)

    def test_application_inspection_shows_linked_subscription_without_secret_data(self):
        application = self.link_application()
        summary = application_inventory(application.pk)
        self.assertEqual(summary["business_vertical"], "LOGISTICS")
        self.assertTrue(summary["business_is_active"])
        self.assertEqual(summary["subscription_interval"], "yearly")
        self.assertEqual(summary["subscription_plan"], "logistics")
        self.assertNotIn(application.email, json.dumps(summary))

    def test_deactivation_preserves_records_and_stops_operations_and_tracking(self):
        self.seed()
        self.link_application()
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        key = session.session_key
        parcel = Parcel.objects.first()
        self.assertIsNotNone(lookup_public_tracking(parcel.tracking_code))
        models = (
            Client,
            Parcel,
            ParcelEvent,
            Shipment,
            DemoSeedRun,
            DemoSeedRecord,
            LogisticsApplication,
        )
        before = {model: model.objects.count() for model in models}
        subscription = BusinessSubscription.objects.filter(business=self.business).values().get()
        self.command(
            "deactivate_business",
            execute=True,
            confirm_business_id=self.business.pk,
            reason_reference="OPS-10",
        )
        self.assertEqual(before, {model: model.objects.count() for model in models})
        self.assertEqual(
            subscription, BusinessSubscription.objects.filter(business=self.business).values().get()
        )
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        for reader in (parcels_for_business, shipments_for_business):
            with self.assertRaises(PermissionDenied):
                reader(business=self.business, actor=self.user)
        self.assertIsNone(lookup_public_tracking(parcel.tracking_code))

    def test_inventory_counts_metadata_and_retained_application_history(self):
        self.seed()
        application = self.link_application()
        self.inactive()
        inventory = build_business_data_inventory(self.business)
        counts = {row.key: row.total_count for row in inventory.records}
        self.assertEqual(
            {
                key: counts[key]
                for key in ("parcels", "parcel_events", "shipments", "demo_seed_records")
            },
            {
                **{
                    key: LOGISTICS_DEMO_COUNTS[key]
                    for key in ("parcels", "parcel_events", "shipments")
                },
                "demo_seed_records": sum(LOGISTICS_DEMO_COUNTS.values()),
            },
        )
        self.assertEqual(counts["logistics_application_decisions"], application.decisions.count())
        self.assertIn("logistics_enrollment_tokens", counts)
        self.assertEqual(
            inventory.summary.future_purge_readiness,
            FuturePurgeReadiness.READY_FOR_PLANNING,
        )
        result = purge_business(business_id=self.business.pk, reason_reference="OPS-10")
        self.assertEqual(result.deletion_counts["logistics_application_links_released"], 1)
        application.refresh_from_db()
        self.assertIsNone(application.business_id)
        self.assertEqual(application.business_id_snapshot, self.business.pk)
        self.assertFalse(Parcel.objects.exists())

    def test_purge_deletes_all_operational_and_demo_records_preserving_shared_users(self):
        self.seed()
        BusinessUser.objects.create(
            business=self.service, user=self.user, role="owner", is_active=False
        )
        self.inactive()
        self.assertIn("DRY RUN ONLY", self.command("purge_business"))
        self.assertEqual(Parcel.objects.count(), LOGISTICS_DEMO_COUNTS["parcels"])
        result = purge_business(
            business_id=self.business.pk, reason_reference="OPS-10", delete_eligible_users=True
        )
        self.assertEqual(
            result.deletion_counts["demo_seed_records"], sum(LOGISTICS_DEMO_COUNTS.values())
        )
        self.assertEqual(
            result.deletion_counts["parcel_events"], LOGISTICS_DEMO_COUNTS["parcel_events"]
        )
        self.assertFalse(Business.objects.filter(pk=self.business.pk).exists())
        for model in (Parcel, ParcelEvent, Shipment, DemoSeedRun, DemoSeedRecord):
            self.assertFalse(model.objects.exists())
        self.assertTrue(TaskIOUser.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(Business.objects.filter(pk=self.other.pk).exists())

    def test_purge_preserves_user_referenced_by_retained_application_history(self):
        application = LogisticsApplication.objects.create(**application_data())
        application.decisions.update(actor=self.user, actor_identifier=self.user.pk)
        self.inactive()
        plan = plan_business_purge(self.business.pk, delete_eligible_users=True)
        decision = next(row for row in plan.user_decisions if row.user_id == self.user.pk)
        self.assertFalse(decision.delete)
        self.assertIn("retained_logistics_application_references", decision.reason_codes)
        purge_business(
            business_id=self.business.pk, reason_reference="OPS-10", delete_eligible_users=True
        )
        self.assertTrue(TaskIOUser.objects.filter(pk=self.user.pk).exists())
        self.assertEqual(application.decisions.get().actor_id, self.user.pk)

    def test_purge_confirmation_and_reason_are_mandatory(self):
        self.seed()
        self.inactive()
        for options in (
            {"execute": True},
            {"execute": True, "confirm_business_id": self.other.pk, "reason_reference": "OPS-10"},
            {"execute": True, "confirm_business_id": self.business.pk},
        ):
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.command("purge_business", **options)
        self.assertEqual(Parcel.objects.count(), LOGISTICS_DEMO_COUNTS["parcels"])

    def test_active_stripe_and_financial_guards_apply_to_logistics(self):
        self.seed()
        with self.assertRaises(BusinessPurgeError) as error:
            purge_business(business_id=self.business.pk, reason_reference="OPS-10")
        self.assertEqual(error.exception.error_code, "business_active")
        self.inactive()
        subscription = self.business.subscription
        subscription.provider_customer_id = "cus_private"
        subscription.save(update_fields=["provider_customer_id"])
        with self.assertRaises(BusinessPurgeError) as error:
            purge_business(business_id=self.business.pk, reason_reference="OPS-10")
        self.assertEqual(error.exception.error_code, "stripe_references_present")
        subscription.provider_customer_id = ""
        subscription.save(update_fields=["provider_customer_id"])
        Invoice.objects.create(business=self.business, client=self.genuine, invoice_number="REAL-2")
        with self.assertRaises(BusinessPurgeError) as error:
            purge_business(business_id=self.business.pk, reason_reference="OPS-10")
        self.assertEqual(error.exception.error_code, "test_financial_data_confirmation_required")
        self.assertEqual(Parcel.objects.count(), LOGISTICS_DEMO_COUNTS["parcels"])

    def test_purge_rollback_preserves_operations_and_metadata_and_records_failure(self):
        self.seed()
        self.inactive()
        with patch(
            "apps.businesses.business_data_purge._verify_purge_complete",
            side_effect=RuntimeError("fail verification"),
        ):
            with self.assertRaises(BusinessPurgeError):
                purge_business(business_id=self.business.pk, reason_reference="OPS-10")
        self.assertEqual(Parcel.objects.count(), LOGISTICS_DEMO_COUNTS["parcels"])
        self.assertEqual(ParcelEvent.objects.count(), LOGISTICS_DEMO_COUNTS["parcel_events"])
        self.assertEqual(DemoSeedRecord.objects.count(), sum(LOGISTICS_DEMO_COUNTS.values()))
        self.assertTrue(Business.objects.filter(pk=self.business.pk).exists())
        self.assertEqual(
            BusinessDataOperation.objects.get().status, BusinessDataOperation.Status.FAILED
        )

    def test_cross_tenant_dependencies_block_purge(self):
        self.seed()
        foreign = Client.objects.create(business=self.other, first_name="Other", last_name="Real")
        real = self.parcel(business=self.other, customer=foreign, actor=self.other_user)
        QuerySet(model=Parcel, using="default").filter(pk=real.pk).update(
            shipment=Shipment.objects.first()
        )
        self.inactive()
        with self.assertRaises(BusinessPurgeError) as error:
            purge_business(business_id=self.business.pk, reason_reference="OPS-10")
        self.assertEqual(error.exception.error_code, "cross_tenant_integrity_blockers")
        self.assertTrue(Parcel.objects.filter(pk=real.pk).exists())

    def test_usage_is_tenant_scoped_includes_active_seats_and_client_states(self):
        self.seed()
        self.command(business_id=self.other.pk, execute=True)
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        self.genuine.client_status = "ARCHIVED"
        self.genuine.save(update_fields=["client_status"])
        usage = logistics_usage(business=self.business)
        self.assertEqual(usage["parcels"], LOGISTICS_DEMO_COUNTS["parcels"])
        self.assertEqual(usage["monthly_parcels"], LOGISTICS_DEMO_COUNTS["parcels"])
        self.assertEqual(usage["monthly_parcel_events"], LOGISTICS_DEMO_COUNTS["parcel_events"])
        self.assertEqual(usage["active_users"], 0)
        self.assertEqual(usage["active_clients"], LOGISTICS_DEMO_COUNTS["clients"])
        self.assertEqual(usage["active_shipments"], 4)
        self.assertEqual(usage["delivered_parcels_this_month"], 3)
        self.assertEqual(usage["average_events_per_parcel"], 4.15)
        self.assertIsNone(usage["reported_locations"])
        self.member.is_active = True
        self.member.save(update_fields=["is_active"])
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(logistics_usage(business=self.business)["active_users"], 0)
        with self.assertRaises(ValidationError):
            logistics_usage(business=self.service)

    def test_month_boundaries_use_business_timezone_and_events_not_registration_for_deliveries(
        self,
    ):
        self.seed()
        self.business.timezone = "America/Curacao"
        self.business.save(update_fields=["timezone"])
        start = datetime(2026, 10, 1, 4, tzinfo=UTC)
        end = datetime(2026, 11, 1, 4, tzinfo=UTC)
        # Domain bypasses are restricted to fixtures for clock-boundary coverage.
        QuerySet(model=Parcel, using="default").update(created_at=datetime(2026, 9, 1, tzinfo=UTC))
        QuerySet(model=ParcelEvent, using="default").update(
            timestamp=datetime(2026, 9, 1, tzinfo=UTC)
        )
        items = list(Parcel.objects.order_by("pk"))
        for parcel, date in zip(
            items[:3], (datetime(2026, 10, 1, 3, 59, tzinfo=UTC), start, end), strict=True
        ):
            QuerySet(model=Parcel, using="default").filter(pk=parcel.pk).update(created_at=date)
        delivered = ParcelEvent.objects.filter(status="DELIVERED").first()
        QuerySet(model=ParcelEvent, using="default").filter(pk=delivered.pk).update(timestamp=start)
        usage = logistics_usage(business=self.business, now=datetime(2026, 10, 15, tzinfo=UTC))
        self.assertEqual(usage["monthly_parcels"], 1)
        self.assertEqual(usage["monthly_parcel_events"], 1)
        self.assertEqual(usage["delivered_parcels_this_month"], 1)
        self.assertEqual(usage["month"], "2026-10")

    @override_settings(
        LOGISTICS_ELIGIBILITY_POLICY=LogisticsEligibilityPolicy(
            auto_approve_monthly_parcels=25,
            review_above_monthly_parcels=50,
            high_resource_monthly_parcels=75,
            auto_approve_staff_count=1,
        ),
        LOGISTICS_USAGE_REVIEW_POLICY=LogisticsUsageReviewPolicy(
            approaching_ratio=0.8, monthly_event_review_threshold=20
        ),
    )
    def test_threshold_visibility_is_review_only_and_does_not_change_approval_billing_or_access(
        self,
    ):
        self.seed()
        application = self.link_application()
        subscription_before = (
            BusinessSubscription.objects.filter(business=self.business).values().get()
        )
        decisions_before = list(application.decisions.values())
        application_before = LogisticsApplication.objects.filter(pk=application.pk).values().get()
        summary = logistics_operational_summary(business=self.business)
        signals = {row["source"]: row for row in summary["threshold_review"]["signals"]}
        self.assertEqual(signals["approval_auto_volume"]["state"], "approaching")
        self.assertEqual(signals["operational_event_review"]["state"], "exceeded")
        self.assertTrue(summary["threshold_review"]["review_required"])
        self.assertFalse(summary["threshold_review"]["commercial_plan_limits"])
        self.assertEqual(
            subscription_before,
            BusinessSubscription.objects.filter(business=self.business).values().get(),
        )
        self.assertEqual(decisions_before, list(application.decisions.values()))
        self.assertEqual(
            application_before,
            LogisticsApplication.objects.filter(pk=application.pk).values().get(),
        )
        self.assertTrue(parcels_for_business(business=self.business, actor=self.user).exists())
        self.assertIsNotNone(lookup_public_tracking(Parcel.objects.first().tracking_code))

    def test_unconfigured_event_threshold_is_visible_without_inventing_a_limit(self):
        usage = logistics_usage(business=self.business)
        summary = logistics_threshold_summary(usage=usage)
        events = next(row for row in summary["signals"] if row["metric"] == "monthly_parcel_events")
        self.assertIsNone(events["threshold"])
        self.assertEqual(events["state"], "not_configured")

    def test_admin_counts_are_bounded_and_link_filter_works(self):
        self.seed()
        self.command(business_id=self.other.pk, execute=True)
        application = self.link_application()
        request = RequestFactory().get("/admin/")
        request.user = self.user
        model_admin = BusinessAdmin(Business, AdminSite())
        with self.assertNumQueries(1):
            rows = list(model_admin.get_queryset(request).order_by("pk"))
            for row in rows:
                model_admin.logistics_parcel_count(row)
                model_admin.logistics_shipment_count(row)
                model_admin.logistics_application_link(row)
                model_admin.subscription_plan(row)
        selected = next(row for row in rows if row.pk == self.business.pk)
        self.assertEqual(selected._parcel_count, LOGISTICS_DEMO_COUNTS["parcels"])
        self.assertEqual(selected._shipment_count, LOGISTICS_DEMO_COUNTS["shipments"])
        self.assertEqual(model_admin.logistics_application_link(selected), str(application.pk))
        link_filter = LogisticsApplicationLinkFilter(
            request, {"logistics_application_link": ["linked"]}, Business, model_admin
        )
        self.assertEqual(
            list(link_filter.queryset(request, Business.objects.all())), [self.business]
        )
        self.assertIn("threshold_review", model_admin.logistics_resource_summary(selected))
