import io
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pypdfium2 as pdfium
import zxingcpp
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.billings.models import Invoice
from apps.billings.payment_services import record_invoice_payment
from apps.billings.services import calculate_tax_amount
from apps.businesses.models import Business, DemoSeedRecord, DemoSeedRun, SubscriptionNotification
from apps.crm.models import Client

from . import test_test_lab as foundation_tests
from .location_access import locations_for
from .location_access_services import select_work_location
from .models import (
    LogisticsCreditApproval,
    LogisticsLocationAssignment,
    LogisticsTestLabAudit,
    Parcel,
    ParcelEvent,
    Shipment,
)
from .parcel_policy import ALLOWED_TRANSITIONS
from .parcel_services import parcels_for_business, record_parcel_event
from .scan import resolve_scanned_parcel
from .shipment_services import generate_manifest
from .shipping_labels import render_shipping_label_pdf
from .test_lab import OWNED_MODELS, owned_objects
from .test_lab_dataset import MODELS, digest, execute_dataset
from .test_lab_scenarios import EXPECTED_COUNTS, SHIPMENTS


@override_settings(
    DEBUG=True,
    MOTIONMATE_ENVIRONMENT="local",
    LOGISTICS_LOCAL_BILLING_BYPASS=True,
    LOGISTICS_TEST_LAB_ENABLED=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class LogisticsTestLabDatasetTests(TestCase):
    # Reuse the normal encrypted Block 06A provisioner, never recreate identities.
    setUp = foundation_tests.LogisticsTestLabTests.setUp
    command = foundation_tests.LogisticsTestLabTests.command
    execute = foundation_tests.LogisticsTestLabTests.execute
    decrypt = foundation_tests.LogisticsTestLabTests.decrypt
    provision = foundation_tests.LogisticsTestLabTests.provision

    def data_command(self, **options):
        output = io.StringIO()
        call_command(
            "seed_logistics_test_lab",
            environment="local",
            business_id=self.business.pk,
            stdout=output,
            **options,
        )
        return json.loads(output.getvalue())

    def seed_data(self, **options):
        return self.data_command(
            execute=True,
            confirm_business_id=self.business.pk,
            confirm_database=self.identity,
            reason_reference="TEST-06B",
            **options,
        )

    def records(self, model):
        return model.objects.filter(
            pk__in=[
                entry["pk"]
                for entry in self.seed.planned_counts["dataset"]["records"].values()
                if entry["model"] == model._meta.label
            ]
        )

    def foundation_snapshot(self):
        return {
            model._meta.label: {
                obj.pk: digest(obj)
                for obj in model.objects.filter(
                    pk__in=list(
                        map(
                            int,
                            self.seed.owned_records.filter(
                                model_label=model._meta.label
                            ).values_list("object_pk", flat=True),
                        )
                    )
                )
            }
            for model in OWNED_MODELS
        }

    def test_preview_and_inspect_make_zero_writes(self):
        self.provision()
        for options in ({}, {"inspect": True}):
            connection.queries_log.clear()
            with CaptureQueriesContext(connection) as captured:
                result = self.data_command(**options)
            self.assertGreater(len(captured), 0)
            self.assertIn("zero writes", result["mode"])
            self.assertFalse(
                any(
                    query["sql"]
                    .lstrip()
                    .upper()
                    .startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
                    for query in captured
                )
            )
        self.assertFalse(Parcel.objects.exists())

    def assignment_snapshot(self):
        return list(LogisticsLocationAssignment.objects.order_by("pk").values())

    def test_fresh_foundation_tracks_all_nine_assignments(self):
        self.provision()
        assignments = self.assignment_snapshot()
        self.assertEqual(len(assignments), 9)
        self.assertEqual(
            set(
                self.seed.owned_records.filter(
                    model_label=LogisticsLocationAssignment._meta.label
                ).values_list("object_pk", flat=True)
            ),
            {str(row["id"]) for row in assignments},
        )
        self.seed_data()
        self.assertEqual(self.assignment_snapshot(), assignments)

    def test_existing_admin_contexts_preserved_without_adoption_and_repeat_refused(self):
        service = Business.objects.create(pk=133, name="Retained service", slug="service-133")
        other = Business.objects.create(
            name="Retained logistics", slug="other", vertical="LOGISTICS"
        )
        clients = [
            Client.objects.create(business=b, first_name="Retained", last_name="Client")
            for b in (service, other)
        ]
        unrelated = [digest(obj) for obj in (service, other, *clients)]
        self.provision()
        for name, code in (("owner", "DM-HUB"), ("admin", "SXM-PORT")):
            select_work_location(
                business=self.business, actor=self.users[name], location=self.sites[code]
            )
        before = self.assignment_snapshot()
        foundation = self.foundation_snapshot()
        ownership = list(self.seed.owned_records.order_by("pk").values())
        # Full cleanup remains strict: these contexts are preserved, not adopted.
        with self.assertRaisesMessage(
            CommandError, "Unowned logistics.LogisticsLocationAssignment"
        ):
            owned_objects(self.business, self.seed)
        with CaptureQueriesContext(connection) as queries:
            self.data_command()
        self.assertFalse(
            any(
                q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for q in queries
            )
        )

        def select_admin_only(**kwargs):
            self.assertIn(kwargs["actor"], [self.users[n] for n in ("owner", "admin", "manager")])
            return select_work_location(**kwargs)

        with patch(
            "apps.logistics.test_lab_dataset.select_work_location", side_effect=select_admin_only
        ):
            self.seed_data()
        self.assertEqual(self.assignment_snapshot(), before)
        self.assertEqual(self.foundation_snapshot(), foundation)
        self.assertEqual(
            list(
                self.seed.owned_records.filter(pk__in=[r["id"] for r in ownership])
                .order_by("pk")
                .values()
            ),
            ownership,
        )
        self.assertEqual(
            self.seed.owned_records.filter(
                model_label=LogisticsLocationAssignment._meta.label
            ).count(),
            9,
        )
        with self.assertRaisesMessage(CommandError, "already exists"):
            self.seed_data()
        self.assertEqual(self.assignment_snapshot(), before)
        self.assertEqual(LogisticsTestLabAudit.objects.filter(action="dataset-seed").count(), 1)
        self.seed_data(reset=True, confirm_test_financial_data=True)
        self.assertEqual(self.assignment_snapshot(), before)
        self.assertEqual(self.foundation_snapshot(), foundation)
        with self.assertRaisesMessage(
            CommandError, "Unowned logistics.LogisticsLocationAssignment"
        ):
            owned_objects(self.business, self.seed)
        for obj, expected in zip((service, other, *clients), unrelated, strict=True):
            obj.refresh_from_db()
            self.assertEqual(digest(obj), expected)
        self.assertFalse(Parcel.objects.filter(business_id__in=(133, other.pk)).exists())

    def test_missing_staff_assignment_ownership_remains_fail_closed(self):
        self.provision()
        assignment = LogisticsLocationAssignment.objects.get(membership__user=self.users["miami"])
        self.seed.owned_records.filter(
            model_label=assignment._meta.label, object_pk=str(assignment.pk)
        ).delete()
        before = self.assignment_snapshot()
        for action in (self.data_command, self.seed_data):
            with self.assertRaisesMessage(
                CommandError, f"LogisticsLocationAssignment {assignment.pk}"
            ):
                action()
        self.assertEqual(self.assignment_snapshot(), before)
        self.assertFalse(Parcel.objects.exists())

    def test_ambiguous_admin_context_and_other_seed_claim_refused(self):
        self.provision()
        select_work_location(
            business=self.business, actor=self.users["owner"], location=self.sites["DM-HUB"]
        )
        context = LogisticsLocationAssignment.objects.get(
            membership__user=self.users["owner"], location=self.sites["DM-HUB"]
        )
        other = Business.objects.create(name="Other", slug="other")
        for changes in (
            {"can_operate": True},
            {"is_work_context": False},
            {"business_id": other.pk},
        ):
            LogisticsLocationAssignment.objects.filter(pk=context.pk).update(**changes)
            before = self.assignment_snapshot()
            with self.assertRaisesMessage(
                CommandError, f"LogisticsLocationAssignment {context.pk}"
            ):
                self.seed_data()
            self.assertEqual(self.assignment_snapshot(), before)
            LogisticsLocationAssignment.objects.filter(pk=context.pk).update(
                can_operate=False, is_work_context=True, business=self.business
            )
        other_seed = DemoSeedRun.objects.create(business=other)
        DemoSeedRecord.objects.create(
            seed_run=other_seed, model_label=context._meta.label, object_pk=str(context.pk)
        )
        with self.assertRaisesMessage(CommandError, "Another seed claims"):
            self.seed_data()
        self.assertFalse(Parcel.objects.exists())

    def test_changed_staff_selection_refused_without_editing_assignments(self):
        self.provision()
        select_work_location(
            business=self.business, actor=self.users["regional"], location=self.sites["SXM-PORT"]
        )
        before = self.assignment_snapshot()
        with self.assertRaisesMessage(CommandError, "worker work location changed"):
            self.seed_data()
        self.assertEqual(self.assignment_snapshot(), before)
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(LogisticsTestLabAudit.objects.filter(action="dataset-seed").exists())

    def test_counts_relationships_states_attribution_invoices_and_foundation_unchanged(self):
        self.provision()
        before = self.foundation_snapshot()
        result = self.seed_data()
        self.seed.refresh_from_db()
        self.assertEqual(result["counts"], EXPECTED_COUNTS)
        self.assertEqual(self.foundation_snapshot(), before)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(set(result["shipment_states"]), set(Shipment.Status.values))
        self.assertEqual(result["transport_modes"], {"SEA": 5, "ROAD": 3, "AIR": 2})
        self.assertEqual(
            result["parcel_states"],
            {
                "DELIVERED": 9,
                "READY": 1,
                "IN_TRANSIT": 6,
                "ARRIVED": 6,
                "RECEIVED": 12,
                "REGISTERED": 4,
                "CANCELLED": 2,
            },
        )
        self.assertEqual(self.records(Client).count(), 12)
        for obj in self.records(Parcel):
            self.assertRegex(obj.tracking_code, r"^MM-PCL-[A-HJKM-NP-Z2-9]{39}$")
            self.assertEqual(obj.business_id, self.business.pk)
            self.assertEqual(obj.client.business_id, self.business.pk)
            self.assertNotEqual(obj.client.company_name, obj.sender_name)
            self.assertNotEqual(obj.client.company_name, obj.recipient_name)
            self.assertTrue(obj.sender_address_line_1)
            self.assertTrue(obj.recipient_address_line_1)
            self.assertEqual(obj.sender_country_code, obj.origin_location.country_code)
            self.assertEqual(obj.recipient_country_code, obj.destination_location.country_code)
            events = list(obj.events.order_by("timestamp", "pk"))
            previous = "REGISTERED"
            for index, event in enumerate(events):
                self.assertIsNotNone(event.actor_id)
                self.assertIsNotNone(event.operational_location_id)
                self.assertEqual(event.business_id, self.business.pk)
                self.assertIn(event.operational_location, locations_for(self.business, event.actor))
                if index:
                    self.assertEqual(event.previous_status, previous)
                    if event.status:
                        self.assertIn(event.status, ALLOWED_TRANSITIONS[previous])
                previous = event.resulting_status
            self.assertEqual(previous, obj.current_status)
        for worker, codes in (
            ("miami", {"MIA-HUB"}),
            ("sxm-port", {"SXM-PORT"}),
            ("sxm-warehouse", {"SXM-DC"}),
            ("dominica", {"DM-HUB"}),
            ("regional", {"MIA-HUB"}),
        ):
            self.assertEqual(
                set(
                    ParcelEvent.objects.filter(actor=self.users[worker]).values_list(
                        "operational_location__code", flat=True
                    )
                ),
                codes,
            )
        for invoice in self.records(Invoice):
            self.assertIn(invoice.status, ("DRAFT", "SENT"))
            self.assertEqual(invoice.email_send_count, 0)
            lines = list(invoice.lines.all())
            self.assertEqual(len(lines), 2)
            subtotal = sum((line.line_total for line in lines), Decimal("0"))
            self.assertEqual(invoice.subtotal, subtotal)
            self.assertEqual(
                invoice.tax,
                calculate_tax_amount(subtotal=subtotal, tax_rate=self.business.tax_rate),
            )
            self.assertEqual(invoice.total, subtotal + invoice.tax)
            for line in lines:
                charge = line.logistics_charge
                self.assertEqual(charge.client_id, invoice.client_id)
                self.assertEqual(charge.quantity, line.quantity)
                self.assertEqual(charge.unit_price, line.unit_price)
                self.assertEqual(charge.parcel_id, line.parcel_id)
                self.assertEqual(charge.shipment_id, line.shipment_id)
        for story in SHIPMENTS:
            entry = self.seed.planned_counts["dataset"]["records"][f"shipment/{story[0]}"]
            shipment = Shipment.objects.get(pk=entry["pk"])
            self.assertEqual(shipment.status, story[4])
            self.assertLess(shipment.departure_at, shipment.estimated_arrival_at)
            if shipment.status in ("IN_TRANSIT", "ARRIVED", "COMPLETED"):
                self.assertLess(shipment.departure_at, timezone.now())
            if shipment.status in ("ARRIVED", "COMPLETED"):
                self.assertLess(shipment.estimated_arrival_at, timezone.now())
            manifest = generate_manifest(
                business=self.business, shipment=shipment, actor=self.users["owner"]
            )
            self.assertEqual(manifest["parcel_count"], 0 if story[4] == "CANCELLED" else story[5])
            if shipment.status == "COMPLETED":
                self.assertFalse(shipment.parcels.exclude(current_status="DELIVERED").exists())
            if shipment.status in ("READY", "IN_TRANSIT", "ARRIVED"):
                expected = {"READY": "RECEIVED", "IN_TRANSIT": "IN_TRANSIT", "ARRIVED": "ARRIVED"}[
                    shipment.status
                ]
                self.assertFalse(shipment.parcels.exclude(current_status=expected).exists())
        owned_objects(self.business, self.seed)

    def test_multileg_locations_and_transition_history(self):
        self.provision()
        self.seed_data()
        for obj in Parcel.objects.filter(internal_reference__startswith="LAB/miami-sxm-dominica"):
            history = list(
                obj.events.filter(event_type="STATUS")
                .order_by("timestamp", "pk")
                .values_list("status", "operational_location__code")
            )
            self.assertEqual(
                history,
                [
                    ("REGISTERED", "MIA-HUB"),
                    ("RECEIVED", "MIA-HUB"),
                    ("IN_TRANSIT", "MIA-HUB"),
                    ("ARRIVED", "SXM-PORT"),
                    ("HOLD", "SXM-PORT"),
                    ("IN_TRANSIT", "SXM-PORT"),
                    ("ARRIVED", "DM-HUB"),
                    ("READY", "DM-HUB"),
                    *(
                        ([("DELIVERED", "DM-HUB")])
                        if obj.internal_reference.endswith("school")
                        else []
                    ),
                ],
            )
            self.assertFalse(obj.events.exclude(location_override_reason="").exists())

    def test_every_label_decodes_qr_and_code128_at_203_and_300_dpi(self):
        self.provision()
        self.seed_data()
        for obj in Parcel.objects.all():
            pdf = render_shipping_label_pdf(obj, current_business=self.business)
            with pdfium.PdfDocument(pdf) as document:
                self.assertEqual(len(document), 1)
                page = document[0]
                for dpi in (203, 300):
                    bitmap = page.render(scale=dpi / 72)
                    try:
                        symbols = zxingcpp.read_barcodes(bitmap.to_pil())
                        self.assertEqual(
                            {str(symbol.format) for symbol in symbols}, {"QR Code", "Code 128"}
                        )
                        self.assertEqual({symbol.text for symbol in symbols}, {obj.tracking_code})
                        self.assertEqual(
                            resolve_scanned_parcel(
                                business=self.business,
                                actor=self.users["owner"],
                                code=obj.tracking_code,
                            ).pk,
                            obj.pk,
                        )
                    finally:
                        bitmap.close()
                page.close()

    def test_duplicate_refused_then_reset_preserves_foundation_and_reseed_has_same_keys(self):
        self.provision()
        before = self.foundation_snapshot()
        self.seed_data()
        self.seed.refresh_from_db()
        manifest = self.seed.planned_counts["dataset"]["records"]
        old_codes = set(Parcel.objects.values_list("tracking_code", flat=True))
        with self.assertRaisesMessage(CommandError, "already exists"):
            self.seed_data()
        connection.queries_log.clear()
        with CaptureQueriesContext(connection) as captured:
            preview = self.data_command(reset=True)
        self.assertGreater(len(captured), 0)
        self.assertEqual(preview["counts"], EXPECTED_COUNTS)
        self.assertFalse(
            any(
                query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                for query in captured
            )
        )
        with self.assertRaisesMessage(CommandError, "confirm-test-financial-data"):
            self.seed_data(reset=True)
        self.seed_data(reset=True, confirm_test_financial_data=True)
        self.seed.refresh_from_db()
        self.assertEqual(self.foundation_snapshot(), before)
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(Invoice.objects.exists())
        self.assertEqual(self.business.memberships.count(), 9)
        self.assertEqual(LogisticsTestLabAudit.objects.filter(action="dataset-reset").count(), 1)
        self.seed_data()
        self.seed.refresh_from_db()
        self.assertEqual(set(self.seed.planned_counts["dataset"]["records"]), set(manifest))
        self.assertFalse(set(Parcel.objects.values_list("tracking_code", flat=True)) & old_codes)

    def test_changed_invoice_and_owned_record_reset_refusal(self):
        self.provision()
        self.seed_data()
        invoice = Invoice.objects.first()
        invoice.status = "SENT"
        invoice.save()
        with self.assertRaisesMessage(CommandError, "Fixture changed"):
            self.seed_data(reset=True, confirm_test_financial_data=True)
        self.assertEqual(Parcel.objects.count(), 40)

    def test_issued_fixture_without_provenance_cannot_reset(self):
        self.provision()
        self.seed_data()
        self.seed.refresh_from_db()
        del self.seed.planned_counts["dataset"]["fixture_issued_invoice_ids"]
        self.seed.save(update_fields=["planned_counts"])
        with self.assertRaisesMessage(CommandError, "unowned financial evidence"):
            self.seed_data(reset=True, confirm_test_financial_data=True)
        self.assertEqual((Parcel.objects.count(), Invoice.objects.count()), (40, 12))

    def test_dispatched_fixture_is_retained_even_with_matching_manifest_digest(self):
        self.provision()
        self.seed_data()
        self.seed.refresh_from_db()
        invoice = Invoice.objects.filter(status="SENT").first()
        invoice.emailed_at = timezone.now()
        invoice.emailed_to = "fictional@example.test"
        invoice.email_send_count = 1
        invoice.save()
        # Exercise the independent dispatch guard even if the manifest were
        # resnapshotted. Normal dispatch is already rejected as a changed row.
        for entry in self.seed.planned_counts["dataset"]["records"].values():
            if entry["model"] == Invoice._meta.label and entry["pk"] == invoice.pk:
                entry["digest"] = digest(invoice)
        self.seed.save(update_fields=["planned_counts"])
        with self.assertRaisesMessage(CommandError, "Financial retention"):
            self.seed_data(reset=True, confirm_test_financial_data=True)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())
        self.assertEqual(Parcel.objects.count(), 40)

    def test_genuine_unowned_credit_blocks_fixture_reset(self):
        self.provision()
        self.seed_data()
        existing = LogisticsCreditApproval.objects.first()
        fields = {
            field.attname: getattr(existing, field.attname)
            for field in existing._meta.concrete_fields
            if not field.primary_key
        }
        fields.update(
            idempotency_key=uuid4(),
            reason_reference="Retain operator-approved credit",
            expires_at=existing.expires_at + timedelta(days=1),
        )
        approval = LogisticsCreditApproval(**fields)
        approval._domain_save(force_insert=True)
        with self.assertRaisesMessage(CommandError, "Unowned logistics.LogisticsCreditApproval"):
            self.seed_data(reset=True, confirm_test_financial_data=True)
        self.assertTrue(LogisticsCreditApproval.objects.filter(pk=approval.pk).exists())
        self.assertEqual(Parcel.objects.count(), 40)

    def test_real_receipt_dependency_blocks_fixture_reset(self):
        self.provision()
        self.seed_data()
        invoice = Invoice.objects.filter(status="SENT").first()
        receipt = record_invoice_payment(
            business=self.business,
            actor=self.users["owner"],
            invoice=invoice,
            amount="1.00",
            currency=invoice.currency_code,
            method="CASH",
            reference="RETAIN-OPERATOR-RECEIPT",
            idempotency_key=uuid4(),
        )
        # Both the receipt and its audit entry are retained dependencies; the
        # model registry may encounter either one first.
        with self.assertRaisesRegex(
            CommandError,
            r"Unowned (crm.ActivityLog|billings.InvoicePayment) depends on dataset; reset refused\.",
        ):
            self.seed_data(reset=True, confirm_test_financial_data=True)
        self.assertTrue(invoice.payments.filter(pk=receipt.pk).exists())
        self.assertEqual(Parcel.objects.count(), 40)

    def test_unowned_events_block_reset_and_whole_lab_cleanup(self):
        self.provision()
        self.seed_data()
        obj = Parcel.objects.filter(origin_location=self.sites["MIA-HUB"]).first()
        record_parcel_event(
            business=self.business,
            parcel=obj,
            actor=self.users["owner"],
            internal_note="Operator real follow-up",
        )
        for action in (
            lambda: self.seed_data(reset=True, confirm_test_financial_data=True),
            lambda: self.command(cleanup=True, business_id=self.business.pk),
        ):
            with self.assertRaisesMessage(CommandError, "Unowned"):
                action()
        self.assertEqual(ParcelEvent.objects.count(), 180)

    def test_missing_and_cross_tenant_ownership_refused(self):
        self.provision()
        self.seed_data()
        self.seed.refresh_from_db()
        entry = next(
            entry
            for entry in self.seed.planned_counts["dataset"]["records"].values()
            if entry["model"] == Client._meta.label
        )
        other = Business.objects.create(name="Customer tenant", slug="other-customer")
        Client.objects.filter(pk=entry["pk"]).update(business=other)
        with self.assertRaises(CommandError):
            self.seed_data(reset=True, confirm_test_financial_data=True)
        self.assertEqual(Parcel.objects.count(), 40)

    def test_environment_production_customer_133_and_confirmation_rejections(self):
        self.provision()
        for runtime in ("production", "prod", "unknown", "development", "staging"):
            with (
                self.subTest(runtime=runtime),
                override_settings(MOTIONMATE_ENVIRONMENT=runtime),
                patch.dict("os.environ", {"ENV": runtime}),
                self.assertRaises(CommandError),
            ):
                self.seed_data()
        for kwargs in (
            {"confirm_business_id": self.business.pk + 1},
            {"business_id": 133, "confirm_business_id": 133},
            {"confirm_database": "wrong"},
            {"reason_reference": None},
        ):
            params = dict(
                environment="local",
                business_id=self.business.pk,
                confirm_business_id=self.business.pk,
                confirm_database=self.identity,
                reason_reference="TEST",
            )
            params.update(kwargs)
            with self.assertRaises(CommandError):
                execute_dataset(**params)
        other = Business.objects.create(
            name="Existing Customer", slug="existing-customer", vertical="LOGISTICS"
        )
        with self.assertRaises(CommandError):
            call_command(
                "seed_logistics_test_lab",
                environment="local",
                business_id=other.pk,
                stdout=io.StringIO(),
            )
        self.assertFalse(Parcel.objects.exists())

    def test_location_tenant_scope_and_unassigned_actor(self):
        self.provision()
        self.seed_data()
        own = self.business
        self.assertEqual(
            parcels_for_business(business=own, actor=self.users["unassigned"]).count(), 0
        )
        for obj in parcels_for_business(business=own, actor=self.users["dominica"]):
            self.assertEqual(obj.destination_location.code, "DM-HUB")
        other = Business.objects.create(name="Other customer", slug="another-customer")
        with self.assertRaises(PermissionDenied):
            parcels_for_business(business=other, actor=self.users["miami"])
        obj = Parcel.objects.filter(origin_location=self.sites["MIA-HUB"]).first()
        with self.assertRaises(PermissionDenied):
            record_parcel_event(
                business=own,
                parcel=obj,
                actor=self.users["dominica"],
                internal_note="Unauthorized site",
            )

    def test_air_fallback_and_unsupported_profile_are_not_overwritten(self):
        self.provision()
        profile = self.business.logistics_profile
        profile.transportation_modes = ["SEA", "ROAD"]
        profile.save()
        before = digest(profile)
        preview = self.data_command()
        self.assertFalse(preview["air_supported"])
        self.seed_data()
        profile.refresh_from_db()
        self.assertEqual(digest(profile), before)
        self.assertFalse(Shipment.objects.filter(transport_mode="AIR").exists())

    def test_disabled_entitlement_and_changed_grants_refuse_without_writes(self):
        self.provision()
        with override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False):
            with self.assertRaises(CommandError):
                self.data_command()
        assignment = (
            self.users["miami"]
            .business_memberships.get(business=self.business)
            .logistics_location_assignments.first()
        )
        assignment.can_operate = False
        assignment.save()
        with self.assertRaisesMessage(CommandError, "grants changed"):
            self.seed_data()
        self.assertFalse(Parcel.objects.exists())

    def test_domain_failure_rolls_back_dataset_foundation_and_audit(self):
        self.provision()
        before = self.foundation_snapshot()
        with (
            patch(
                "apps.logistics.test_lab_dataset.invoice_charges",
                side_effect=CommandError("Injected billing failure"),
            ),
            self.assertRaisesMessage(CommandError, "Injected"),
        ):
            self.seed_data()
        self.assertEqual(self.foundation_snapshot(), before)
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(Client.objects.exists())
        self.assertFalse(LogisticsTestLabAudit.objects.filter(action="dataset-seed").exists())
        self.assertFalse(self.seed.owned_records.filter(model_label__in=MODELS).exists())

    def test_foundation_cleanup_keeps_existing_financial_gates(self):
        self.provision()
        self.seed_data()
        with self.assertRaisesMessage(CommandError, "test_financial_data_confirmation_required"):
            self.command(cleanup=True, business_id=self.business.pk)
        self.assertEqual(Invoice.objects.count(), 12)
        self.assertEqual(self.business.memberships.count(), 9)

    def test_normal_billing_metadata_and_unrelated_financial_records_are_preserved(self):
        self.provision()
        client = Client.objects.create(
            business=self.business, first_name="Existing", last_name="Customer"
        )
        invoice = Invoice.objects.create(
            business=self.business, client=client, invoice_number="RETAIN-001", status="PAID"
        )
        notification = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.business.subscription,
            notification_type="subscription_activated",
            deduplication_key="existing-activation",
            recipient_user=self.users["owner"],
            status="CANCELLED",
        )
        originals = {obj._meta.label: digest(obj) for obj in (client, invoice, notification)}
        self.assertEqual(self.seed_data()["counts"], EXPECTED_COUNTS)
        self.seed_data(reset=True, confirm_test_financial_data=True)
        for obj in (client, invoice, notification):
            obj.refresh_from_db()
            self.assertEqual(digest(obj), originals[obj._meta.label])
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)
