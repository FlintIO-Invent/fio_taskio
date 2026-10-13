"""Read-only reconstruction, financial truth, capability/privacy and bounded queries."""

import json
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice, InvoicePayment
from apps.billings.payment_services import adjust_invoice_payment, record_invoice_payment
from apps.billings.services import change_invoice_status
from apps.businesses.models import BusinessUser
from apps.crm.models import ActivityLog

from . import test_financial_coverage as fixtures
from .billing_services import correct_charge
from .location_access_services import (
    enable_location_operations,
    select_work_location,
    set_location_assignment,
)
from .location_test_support import approve_test_site
from .models import LogisticsCharge, LogisticsLocation, Parcel, ParcelEvent
from .parcel_services import change_parcel_status
from .shipment_services import assign_parcel, remove_parcel
from .workflow_summary import FinancialState, resolve_parcel_workflow, resolve_parcel_workflows


class ParcelWorkflowSummaryTests(TestCase):
    setUp = fixtures.FinancialCoverageTests.setUp
    parcel = fixtures.FinancialCoverageTests.parcel
    shipment = fixtures.FinancialCoverageTests.shipment
    charge = fixtures.FinancialCoverageTests.charge
    bill = fixtures.FinancialCoverageTests.bill
    cargo = fixtures.FinancialCoverageTests.cargo

    def summary(self, parcel, **options):
        return resolve_parcel_workflow(
            business=self.business, actor=self.user, parcel=parcel, **options
        )

    def issue(self, invoice):
        return change_invoice_status(
            business=self.business, actor=self.user, invoice=invoice, status="SENT"
        )

    def receipt(self, invoice, amount=None, **fields):
        invoice.refresh_from_db()
        return record_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            amount=invoice.total if amount is None else amount,
            currency=invoice.currency_code,
            method="BANK_TRANSFER",
            reference=f"SECRET-BANK-{uuid.uuid4()}",
            idempotency_key=uuid.uuid4(),
            **fields,
        )

    def move(self, parcel, status):
        result = change_parcel_status(
            business=self.business, actor=self.user, parcel=parcel, status=status
        )
        parcel.refresh_from_db()
        return result

    def test_interrupted_registration_detects_missing_evidence_without_repair_writes(self):
        parcel = self.parcel()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM logistics_parcelevent WHERE parcel_id = %s", [parcel.pk])
        summary = self.summary(parcel)
        self.assertEqual(summary.tracking_code, parcel.tracking_code)
        self.assertFalse(summary.operational["evidence_complete"])
        self.assertEqual(summary.completed_steps, ())
        self.assertEqual(
            summary.executable_actions,
            tuple(
                action for action in summary.executable_actions if action["kind"] != "OPERATIONAL"
            ),
        )
        self.assertEqual(summary.history[0]["kind"], "PARCEL_CREATED")
        self.assertFalse(ParcelEvent.objects.filter(parcel=parcel).exists())
        self.assertTrue(summary.issues)

    def test_missing_charge_invoice_and_payment_are_distinct(self):
        parcel = self.parcel()
        self.assertEqual(self.summary(parcel).financial["state"], "UNKNOWN")
        charge = self.charge(parcel=parcel, unit_price=100)
        summary = self.summary(parcel)
        self.assertEqual(summary.financial["state"], "UNINVOICED")
        self.assertEqual(
            summary.financial["totals_by_currency"]["unbilled"], {"USD": Decimal("100")}
        )
        self.assertIn("GENERATE_INVOICE", {action["code"] for action in summary.executable_actions})
        invoice = self.bill(charge)
        self.assertEqual(self.summary(parcel).financial["state"], "UNPAID")
        self.issue(invoice)
        summary = self.summary(parcel)
        self.assertEqual(
            summary.financial["totals_by_currency"]["outstanding"], {"USD": Decimal("100")}
        )
        self.assertFalse(summary.financial["clearance"]["cleared"])

    def test_partial_full_receipts_and_transport_remain_independent(self):
        parcel = self.parcel()
        self.move(parcel, "RECEIVED")
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        partial = self.receipt(invoice, 40)
        summary = self.summary(parcel)
        self.assertEqual(summary.financial["state"], "PARTIAL")
        self.assertNotIn("MARK_IN_TRANSIT", {item["code"] for item in summary.executable_actions})
        self.assertIn("MARK_IN_TRANSIT", {item["code"] for item in summary.candidate_actions})
        second = self.receipt(invoice, 60)
        summary = self.summary(parcel)
        self.assertEqual(summary.financial["state"], "PAID")
        self.assertIn("MARK_IN_TRANSIT", {item["code"] for item in summary.executable_actions})
        self.move(parcel, "IN_TRANSIT")
        adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            payment=second,
            kind="REFUND",
            amount=20,
            reference="REF-TRANSIT",
            reason_reference="CASE-TRANSIT",
            idempotency_key=uuid.uuid4(),
        )
        summary = self.summary(parcel)
        self.assertEqual(summary.operational["state"], "IN_TRANSIT")
        self.assertEqual(summary.financial["state"], "PARTIAL")
        self.assertEqual(
            summary.financial["totals_by_currency"]["outstanding"], {"USD": Decimal("20")}
        )
        self.assertTrue(
            any(
                item["source_id"] == partial.pk and item["kind"] == "PAYMENT_RECEIPT"
                for item in summary.history
            )
        )
        self.move(parcel, "ARRIVED")
        self.move(parcel, "READY")
        self.assertNotIn(
            "MARK_DELIVERED", {item["code"] for item in self.summary(parcel).executable_actions}
        )

    def test_frozen_shipment_freight_and_shared_invoice_bulk_totals_are_not_allocated_or_doubled(
        self,
    ):
        ship, a, b = self.shipment(), self.parcel(), self.parcel()
        self.cargo(ship, a, b)
        freight = self.charge(shipment=ship, description="Freight", unit_price=150)
        direct = self.charge(parcel=a, unit_price=25)
        invoice = self.bill(freight, direct)
        self.issue(invoice)
        self.receipt(invoice, 100)
        batch = resolve_parcel_workflows(
            business=self.business, actor=self.user, parcel_ids=[a.pk, b.pk, a.pk]
        )
        self.assertEqual(batch.financial_totals["charges"], {"USD": Decimal("175")})
        self.assertEqual(batch.financial_totals["verified_net_paid"], {"USD": Decimal("100")})
        self.assertEqual(batch.financial_totals["outstanding"], {"USD": Decimal("75")})
        for summary in batch.summaries:
            self.assertEqual(summary.financial["state"], "PARTIAL")
            self.assertTrue(summary.financial["invoices"][0]["shared"])
            self.assertEqual(
                summary.financial["invoices"][0]["allocation"],
                "FULL_INVOICE_BALANCE_NO_PARCEL_ALLOCATION",
            )
        remove_parcel(business=self.business, actor=self.user, shipment=ship, parcel=b)
        self.assertTrue(
            any(row["id"] == freight.pk for row in self.summary(b).financial["charges"])
        )
        newcomer = self.parcel()
        assign_parcel(business=self.business, actor=self.user, shipment=ship, parcel=newcomer)
        self.assertEqual(self.summary(newcomer).financial["state"], "UNKNOWN")

    def test_several_invoices_and_parcels_keep_distinct_obligations(self):
        a, b = self.parcel(), self.parcel()
        shared = self.bill(self.charge(parcel=a), self.charge(parcel=b))
        separate = self.bill(self.charge(parcel=a, description="Insurance"))
        self.issue(shared)
        self.issue(separate)
        self.receipt(shared)
        self.assertEqual(self.summary(a).financial["state"], "PARTIAL")
        self.assertEqual(self.summary(b).financial["state"], "PAID")
        self.receipt(separate)
        batch = resolve_parcel_workflows(
            business=self.business, actor=self.user, parcel_ids=[a.pk, b.pk]
        )
        self.assertEqual(batch.financial_totals["verified_net_paid"], {"USD": Decimal("75")})
        self.assertTrue(all(item.financial["clearance"]["cleared"] for item in batch.summaries))

    def test_cancel_reissue_and_corrected_charge_history_is_retained(self):
        parcel = self.parcel()
        original = self.charge(parcel=parcel)
        first = self.bill(original)
        self.issue(first)
        change_invoice_status(
            business=self.business, actor=self.user, invoice=first, status="CANCELLED"
        )
        self.assertEqual(self.summary(parcel).financial["state"], "UNINVOICED")
        replacement = correct_charge(
            business=self.business,
            actor=self.user,
            charge=original,
            unit_price=30,
            reason_reference="CASE-CORRECTION",
            idempotency_key=uuid.uuid4(),
        )
        second = self.bill(replacement)
        self.issue(second)
        self.receipt(second)
        summary = self.summary(parcel)
        self.assertEqual(summary.financial["state"], "PAID")
        self.assertEqual(summary.financial["totals_by_currency"]["charges"], {"USD": Decimal("30")})
        self.assertEqual(
            {row["id"] for row in summary.financial["invoices"]}, {first.pk, second.pk}
        )
        kinds = {item["kind"] for item in summary.history}
        self.assertTrue(
            {"CHARGE_CREATED", "CHARGE_VOIDED", "INVOICE_BINDING", "PAYMENT_RECEIPT"}.issubset(
                kinds
            )
        )
        self.assertTrue(
            any(
                item["kind"] == "CHARGE_VOIDED" and item["actor"]["id"] == self.user.pk
                for item in summary.history
            )
        )

    def test_timeline_stable_ordering_and_authoritative_actor_location(self):
        parcel = self.parcel()
        site = approve_test_site(business=self.business, membership=self.membership, parcel=parcel)
        self.move(parcel, "RECEIVED")
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        receipt = self.receipt(invoice)
        stamp = timezone.now() - timedelta(days=1)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE logistics_parcelevent SET timestamp = %s WHERE parcel_id = %s",
                [stamp, parcel.pk],
            )
            cursor.execute(
                "UPDATE billings_invoicepayment SET recorded_at = %s WHERE id = %s",
                [stamp, receipt.pk],
            )
        summary = self.summary(parcel)
        self.assertEqual(
            [item["timestamp"] for item in summary.history],
            sorted(item["timestamp"] for item in summary.history),
        )
        received = next(
            item
            for item in summary.history
            if item["source"] == "logistics.ParcelEvent" and item["label"] == "Received"
        )
        self.assertEqual(
            (received["actor"]["id"], received["location"]["id"]), (self.user.pk, site.pk)
        )
        self.assertEqual(summary.history, self.summary(parcel).history)

    def test_removed_shipment_membership_is_reconstructed_without_current_assignment(self):
        parcel, ship = self.parcel(), self.shipment()
        self.cargo(ship, parcel)
        remove_parcel(business=self.business, actor=self.user, shipment=ship, parcel=parcel)
        summary = self.summary(parcel)
        self.assertIsNone(summary.shipment)
        labels = [item["label"] for item in summary.history if item["kind"] == "SHIPMENT_EVENT"]
        self.assertTrue(any("assign" in label for label in labels))
        self.assertTrue(any("remove" in label for label in labels))

    def test_foreign_or_malformed_shipment_history_is_not_trusted_or_disclosed(self):
        parcel, ship = self.parcel(), self.shipment()
        self.cargo(ship, parcel)
        foreign = LogisticsLocation.objects.create(
            business=self.other,
            code="SECRET-SITE",
            name="Secret site",
            location_type="HUB",
            country_code="US",
        )
        ship.refresh_from_db()
        entries = ship.operation_history
        assignment = next(entry for entry in entries if entry.get("action") == "assign")
        assignment.update(location_id=foreign.pk, location_code=foreign.code)
        entries.append(
            {**assignment, "business_id": self.other.pk, "new_state": "SECRET-FOREIGN-STATE"}
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE logistics_shipment SET operation_history = %s WHERE id = %s",
                [json.dumps(entries), ship.pk],
            )
        summary = self.summary(parcel)
        self.assertTrue(summary.issues)
        self.assertNotIn("SECRET-SITE", str(summary.to_dict()))
        self.assertNotIn("SECRET-FOREIGN-STATE", str(summary.to_dict()))
        self.assertFalse(any(item["kind"] == "OPERATIONAL" for item in summary.executable_actions))
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE logistics_shipment SET operation_history = %s WHERE id = %s",
                [json.dumps({"bad": "history"}), ship.pk],
            )
        self.assertTrue(self.summary(parcel).issues)

    def test_fake_credit_notes_roles_logs_and_paid_status_never_approve_credit(self):
        parcel = self.parcel(internal_notes="Credit approved by owner")
        self.customer.notes = "CREDIT_APPROVED: government customer"
        self.customer.client_type = "BUSINESS"
        self.customer.save()
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        change_invoice_status(
            business=self.business, actor=self.user, invoice=invoice, status="PAID"
        )
        ActivityLog.objects.create(
            business=self.business,
            actor=self.user,
            client=self.customer,
            action_type="STATUS_CHANGED",
            summary="Credit approved",
            payload={"invoice_id": invoice.pk, "credit_approved": True},
        )
        self.move(parcel, "RECEIVED")
        for required in (False, True):
            summary = self.summary(parcel, require_credit_evidence=required)
            self.assertEqual(summary.financial["state"], "UNKNOWN")
            self.assertFalse(summary.financial["clearance"]["cleared"])
            self.assertNotIn(
                "MARK_IN_TRANSIT", {item["code"] for item in summary.executable_actions}
            )
        self.assertEqual(FinancialState.CREDIT_APPROVED.value, "CREDIT_APPROVED")
        self.assertFalse(InvoicePayment.objects.exists())

    def test_required_credit_evidence_is_missing_even_with_an_accounting_actor(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        self.receipt(invoice)
        self.assertEqual(self.summary(parcel).financial["state"], "PAID")
        restricted = self.summary(parcel, require_credit_evidence=True)
        self.assertEqual(restricted.financial["state"], "UNKNOWN")
        self.assertFalse(restricted.financial["clearance"]["cleared"])

    def test_destination_staff_gets_only_clearance_without_financial_history(self):
        parcel = self.parcel()
        staff = TaskIOUser.objects.create_user(email="summary-destination@example.test")
        member = BusinessUser.objects.create(business=self.business, user=staff, role="staff")
        approve_test_site(business=self.business, membership=member, parcel=parcel)
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        self.receipt(invoice)
        summary = resolve_parcel_workflow(business=self.business, actor=staff, parcel=parcel)
        self.assertEqual(summary.financial["visibility"], "CLEARANCE_ONLY")
        self.assertTrue(summary.financial["clearance"]["cleared"])
        self.assertIsNone(summary.financial["state"])
        self.assertEqual(
            (
                summary.financial["charges"],
                summary.financial["invoices"],
                summary.financial["totals_by_currency"],
            ),
            ((), (), {}),
        )
        self.assertFalse(any(item["source"].startswith("billings.") for item in summary.history))
        self.assertNotIn("SECRET-BANK", str(summary.to_dict()))
        self.assertNotIn(invoice.invoice_number, str(summary.to_dict()))
        self.client.force_login(staff)
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertContains(response, "Accounting clearance confirmed")
        self.assertNotContains(response, invoice.invoice_number)

    def test_cross_tenant_unassigned_anonymous_and_service_access_are_denied(self):
        parcel = self.parcel()
        for business, actor in (
            (self.other, self.user),
            (self.business, self.other_user),
            (self.business, None),
            (self.service, self.user),
        ):
            with self.assertRaises(PermissionDenied):
                resolve_parcel_workflow(business=business, actor=actor, parcel=parcel)
        staff = TaskIOUser.objects.create_user(email="unassigned-summary@example.test")
        BusinessUser.objects.create(business=self.business, user=staff, role="staff")
        with self.assertRaises(PermissionDenied):
            resolve_parcel_workflow(business=self.business, actor=staff, parcel=parcel)

    def test_read_only_grants_do_not_turn_candidate_steps_into_actions(self):
        parcel = self.parcel()
        staff = TaskIOUser.objects.create_user(email="readonly-summary@example.test")
        member = BusinessUser.objects.create(business=self.business, user=staff, role="staff")
        site = approve_test_site(business=self.business, membership=member, parcel=parcel)
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=member,
            location=site,
            can_operate=False,
        )
        summary = resolve_parcel_workflow(business=self.business, actor=staff, parcel=parcel)
        self.assertTrue(summary.candidate_actions)
        self.assertEqual(summary.executable_actions, ())

    def test_operating_staff_retains_scoped_charge_and_invoice_entry_without_private_summary(self):
        parcel = self.parcel()
        staff = TaskIOUser.objects.create_user(email="billing-summary-staff@example.test")
        member = BusinessUser.objects.create(business=self.business, user=staff, role="staff")
        site = approve_test_site(business=self.business, membership=member, parcel=parcel)
        self.charge(parcel=parcel)
        summary = resolve_parcel_workflow(business=self.business, actor=staff, parcel=parcel)
        codes = {action["code"] for action in summary.executable_actions}
        self.assertTrue({"ADD_CHARGE", "GENERATE_INVOICE"}.issubset(codes))
        self.assertEqual(summary.financial["visibility"], "CLEARANCE_ONLY")
        self.assertEqual(summary.financial["charges"], ())
        self.assertEqual(summary.financial["invoices"], ())
        self.assertFalse(
            any(code.startswith(("RECORD_PAYMENT", "ISSUE_INVOICE")) for code in codes)
        )
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=member,
            location=site,
            can_operate=False,
        )
        readonly = resolve_parcel_workflow(business=self.business, actor=staff, parcel=parcel)
        self.assertFalse(readonly.executable_actions)

    def test_resolver_is_read_only_and_batch_query_count_does_not_grow_per_parcel(self):
        ship = self.shipment()
        parcels = [self.parcel() for _ in range(20)]
        self.cargo(ship, *parcels)
        invoice = self.bill(self.charge(shipment=ship, unit_price=500))
        self.issue(invoice)
        self.receipt(invoice)
        before = [
            model.objects.count()
            for model in (
                Parcel,
                ParcelEvent,
                LogisticsCharge,
                Invoice,
                InvoicePayment,
                ActivityLog,
            )
        ]
        counts = []
        for selected in ([parcels[0].pk], [item.pk for item in parcels]):
            with CaptureQueriesContext(connection) as captured:
                batch = resolve_parcel_workflows(
                    business=self.business,
                    actor=self.user,
                    parcel_ids=selected,
                    include_history=False,
                )
            counts.append(len(captured))
            self.assertFalse(
                any(
                    query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                    for query in captured
                )
            )
            self.assertEqual(batch.financial_totals["verified_net_paid"], {"USD": Decimal("500")})
        self.assertLessEqual(counts[1], counts[0] + 2, counts)
        self.assertLess(counts[1], 60, counts)
        self.assertEqual(
            before,
            [
                model.objects.count()
                for model in (
                    Parcel,
                    ParcelEvent,
                    LogisticsCharge,
                    Invoice,
                    InvoicePayment,
                    ActivityLog,
                )
            ],
        )
        self.query_counts = counts

    def test_batch_input_limit_and_empty_results(self):
        self.assertEqual(
            resolve_parcel_workflows(
                business=self.business, actor=self.user, parcel_ids=[]
            ).summaries,
            (),
        )
        with self.assertRaises(ValidationError):
            resolve_parcel_workflows(
                business=self.business, actor=self.user, parcel_ids=range(1, 102)
            )

    def test_history_omission_retains_financial_completed_steps_and_candidate_actions(self):
        parcel, ship = self.parcel(), self.shipment()
        self.cargo(ship, parcel)
        charge = self.charge(shipment=ship)
        candidate = f"GENERATE_SHIPMENT_INVOICE_{ship.pk}"
        self.assertIn(candidate, {item["code"] for item in self.summary(parcel).executable_actions})
        invoice = self.bill(charge)
        self.issue(invoice)
        self.receipt(invoice)
        full, compact = self.summary(parcel), self.summary(parcel, include_history=False)
        codes = {"CHARGES_RECORDED", "INVOICED", "PAYMENT_RECORDED", "FINANCIALLY_CLEARED"}
        self.assertTrue(codes.issubset({item["code"] for item in full.completed_steps}))
        self.assertTrue(codes.issubset({item["code"] for item in compact.completed_steps}))
        self.assertEqual(compact.history, ())

    def test_issued_invoice_summary_preserves_currency_and_tax_after_defaults_change(self):
        self.business.tax_rate = Decimal("10")
        self.business.save()
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        self.receipt(invoice, 50)
        self.business.currency, self.business.tax_rate = "EUR", Decimal("20")
        self.business.save()
        summary = self.summary(parcel)
        row = summary.financial["invoices"][0]
        self.assertEqual(
            (row["currency"], row["total"], row["outstanding"]),
            ("USD", Decimal("110"), Decimal("60")),
        )
        self.assertEqual(
            summary.financial["totals_by_currency"]["charges"], {"USD": Decimal("100")}
        )
        self.assertEqual(summary.financial["state"], "PARTIAL")

    def test_corrupt_foreign_invoice_relationship_fails_closed_without_private_data(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        foreign = Invoice.objects.create(
            business=self.other, client=self.other_customer, invoice_number="FOREIGN-SECRET"
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE billings_invoiceline SET invoice_id = %s WHERE invoice_id = %s",
                [foreign.pk, invoice.pk],
            )
        summary = self.summary(parcel)
        self.assertEqual(summary.financial["state"], "UNKNOWN")
        self.assertFalse(summary.financial["clearance"]["cleared"])
        self.assertNotIn("FOREIGN-SECRET", str(summary.to_dict()))

    def test_missing_sibling_charge_membership_blocks_clearance_for_shared_invoice(self):
        a, b = self.parcel(), self.parcel()
        own, sibling = self.charge(parcel=a), self.charge(parcel=b)
        invoice = self.bill(own, sibling)
        self.issue(invoice)
        self.receipt(invoice)
        self.assertEqual(self.summary(a).financial["state"], "PAID")
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM logistics_logisticschargeparcel WHERE charge_id = %s", [sibling.pk]
            )
        summary = self.summary(a)
        self.assertEqual(summary.financial["state"], "UNKNOWN")
        self.assertFalse(summary.financial["clearance"]["cleared"])
        self.assertFalse(summary.financial["invoices"][0]["evidence_verified"])
        self.assertEqual(summary.financial["totals_by_currency"]["verified_net_paid"], {})

    def test_unlinked_direct_invoice_reference_and_ledger_are_preserved_without_clearance(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        self.receipt(invoice, 10)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE billings_invoiceline SET charge_source_id = NULL WHERE invoice_id = %s",
                [invoice.pk],
            )
        summary = self.summary(parcel)
        self.assertEqual(summary.financial["state"], "UNKNOWN")
        self.assertFalse(summary.financial["clearance"]["cleared"])
        row = summary.financial["invoices"][0]
        self.assertEqual(
            (row["id"], row["net_paid"], row["outstanding"]),
            (invoice.pk, Decimal("10"), Decimal("15")),
        )
        self.assertFalse(row["evidence_verified"])
        self.assertTrue(
            any(entry["source"] == "billings.InvoicePayment" for entry in summary.history)
        )

    def test_extra_shared_invoice_sources_are_validated_with_bounded_bulk_queries(self):
        parcels = [self.parcel() for _ in range(20)]
        invoice = self.bill(*(self.charge(parcel=parcel) for parcel in parcels))
        self.issue(invoice)
        self.receipt(invoice)
        counts = []
        for ids in ([parcels[0].pk], [parcel.pk for parcel in parcels]):
            with CaptureQueriesContext(connection) as captured:
                batch = resolve_parcel_workflows(
                    business=self.business, actor=self.user, parcel_ids=ids, include_history=False
                )
            counts.append(len(captured))
            self.assertTrue(
                all(summary.financial["state"] == "PAID" for summary in batch.summaries)
            )
            self.assertEqual(batch.financial_totals["verified_net_paid"], {"USD": Decimal("500")})
        self.assertLessEqual(counts[1], counts[0] + 2, counts)
        self.assertLess(counts[0], 65, counts)

    def test_update_form_cannot_use_fake_credit_or_missing_payment_to_depart_or_deliver(self):
        parcel = self.parcel()
        self.move(parcel, "RECEIVED")
        url = reverse("logistics_parcel_update", args=[parcel.pk])

        def data(status):
            return {
                "status": status,
                "expected_status": parcel.current_status,
                "idempotency_key": str(uuid.uuid4()),
                "credit_approved": "yes",
            }

        blocked = self.client.post(url, data("IN_TRANSIT"))
        self.assertContains(blocked, "financial clearance")
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "RECEIVED")
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        payment = self.receipt(invoice)
        self.assertEqual(self.client.post(url, data("IN_TRANSIT")).status_code, 302)
        parcel.refresh_from_db()
        self.move(parcel, "ARRIVED")
        self.move(parcel, "READY")
        adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            payment=payment,
            amount=1,
            kind="REFUND",
            reference="DELIVERY-REFUND",
            reason_reference="CASE-DELIVERY",
            idempotency_key=uuid.uuid4(),
        )
        blocked = self.client.post(url, data("DELIVERED"))
        self.assertContains(blocked, "financial clearance")
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "READY")

    def test_existing_audited_admin_route_override_requires_actual_financial_clearance(self):
        source = approve_test_site(business=self.business, membership=self.membership)
        select_work_location(business=self.business, actor=self.user, location=source)
        enable_location_operations(business=self.business, actor=self.user)
        parcel = self.parcel(origin_location=source, destination_location=source)
        self.move(parcel, "RECEIVED")
        alternative = LogisticsLocation.objects.create(
            business=self.business,
            code="REROUTE",
            name="Reroute",
            location_type="HUB",
            country_code="US",
        )
        select_work_location(business=self.business, actor=self.user, location=alternative)
        data = {
            "status": "IN_TRANSIT",
            "expected_status": "RECEIVED",
            "idempotency_key": str(uuid.uuid4()),
            "location_override_reason": "CASE-APPROVED-REROUTE",
        }
        url = reverse("logistics_parcel_update", args=[parcel.pk])
        self.assertContains(self.client.post(url, data), "financial clearance")
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        self.receipt(invoice)
        self.assertNotIn(
            "MARK_IN_TRANSIT", {item["code"] for item in self.summary(parcel).executable_actions}
        )
        self.assertEqual(self.client.post(url, data).status_code, 302)
        event = parcel.events.get(status="IN_TRANSIT")
        self.assertEqual(event.location_override_reason, "CASE-APPROVED-REROUTE")
        self.assertEqual(event.operational_location_id, alternative.pk)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "workflow-public",
            }
        },
        LOGISTICS_TRACKING_REQUIRE_SHARED_CACHE=False,
        LOGISTICS_TRACKING_CLIENT_IP_MODE="direct",
    )
    def test_detail_dashboard_scan_share_contract_and_public_tracking_has_no_finance(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        self.receipt(invoice)
        detail = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertContains(detail, "Parcel journey")
        self.assertEqual(detail.context["workflow_summary"].financial["state"], "PAID")
        scan = self.client.post(
            reverse("logistics_parcel_scan"), {"tracking_code": parcel.tracking_code}
        )
        self.assertEqual(scan.context["workflow_summary"].financial["state"], "PAID")
        dashboard = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(
            dashboard.context["parcels_requiring_attention"][0].workflow_summary.financial["state"],
            "PAID",
        )
        self.client.logout()
        public = self.client.post(
            reverse("logistics_public_tracking"), {"tracking_code": parcel.tracking_code}
        )
        self.assertNotContains(public, invoice.invoice_number)
        self.assertNotContains(public, "SECRET-BANK")
        self.assertNotContains(public, "Parcel journey")

    def test_scan_does_not_accept_missing_payment_or_fake_credit_for_departure(self):
        parcel = self.parcel()
        self.move(parcel, "RECEIVED")
        data = {
            "status": "IN_TRANSIT",
            "expected_status": "RECEIVED",
            "idempotency_key": str(uuid.uuid4()),
            "credit_approved": "true",
        }
        response = self.client.post(reverse("logistics_parcel_scan_action", args=[parcel.pk]), data)
        self.assertEqual(response.status_code, 400)
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "RECEIVED")
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        self.receipt(invoice)
        response = self.client.post(reverse("logistics_parcel_scan_action", args=[parcel.pk]), data)
        self.assertEqual(response.status_code, 302)
