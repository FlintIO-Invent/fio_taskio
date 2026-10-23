"""Refund cards project authorized ledger/settlement data without changing it."""

import uuid
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.billings.models import Invoice, InvoiceLine, InvoicePayment
from apps.billings.payment_services import adjust_invoice_payment, record_invoice_payment
from apps.billings.services import change_invoice_status

from . import test_cancellation_settlement as fixtures


class LogisticsDashboardRefundTests(TestCase):
    setUp = fixtures.CancellationSettlementTests.setUp
    parcel = fixtures.CancellationSettlementTests.parcel
    shipment = fixtures.CancellationSettlementTests.shipment
    charge = fixtures.CancellationSettlementTests.charge
    bill = fixtures.CancellationSettlementTests.bill
    issue = fixtures.CancellationSettlementTests.issue
    receipt = fixtures.CancellationSettlementTests.receipt
    prepare = fixtures.CancellationSettlementTests.prepare
    settle = fixtures.CancellationSettlementTests.settle
    refund = fixtures.CancellationSettlementTests.refund

    def refundable(self):
        parcel, charge, invoice, receipt = self.prepare(paid=True)
        self.business.cancellation_service_charge = Decimal("20")
        self.business.save(update_fields=["cancellation_service_charge"])
        settlement = self.settle(parcel)
        return invoice, receipt, settlement.credits.get()

    def dashboard(self):
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.status_code, 200)
        return response

    def manual_invoice(self, business=None, client=None, actor=None):
        invoice = Invoice.objects.create(
            business=business or self.business,
            client=client or self.customer,
            invoice_number=f"REF-{uuid.uuid4().hex}",
            subtotal=100,
            total=100,
        )
        InvoiceLine.objects.create(
            invoice=invoice, description="Service", quantity=1, unit_price=100
        )
        change_invoice_status(
            business=invoice.business, actor=actor or self.user, invoice=invoice, status="SENT"
        )
        invoice.refresh_from_db()
        return invoice

    def test_due_and_partially_recorded_refunds_use_authoritative_amounts(self):
        invoice, receipt, credit = self.refundable()
        response = self.dashboard()
        totals = response.context["refund_currency_totals"][0]
        self.assertEqual(totals["refund_due_total"], Decimal("80.00"))
        self.assertEqual(totals["refund_due_invoice_count"], 1)
        self.assertEqual(totals["recorded_refund_total"], 0)
        key = uuid.uuid4()
        self.refund(invoice, receipt, credit, 30, key=key)
        self.refund(invoice, receipt, credit, 30, key=key)
        count = InvoicePayment.objects.count()
        response = self.dashboard()
        totals = response.context["refund_currency_totals"][0]
        self.assertEqual(totals["refund_due_total"], Decimal("50.00"))
        self.assertEqual(totals["recorded_refund_total"], Decimal("30.00"))
        self.assertEqual(totals["recorded_refund_count"], 1)
        self.assertContains(response, "Refund due")
        self.assertContains(response, "Refund recorded")
        self.assertEqual(InvoicePayment.objects.count(), count)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "PAID")

    def test_completed_refunds_remain_visible_on_cancelled_invoices(self):
        invoice = self.manual_invoice()
        receipt = self.receipt(invoice)
        adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            payment=receipt,
            kind="REFUND",
            amount=100,
            reference="FULL-RETURN",
            reason_reference="Refund",
            idempotency_key=uuid.uuid4(),
        )
        change_invoice_status(
            business=self.business, actor=self.user, invoice=invoice, status="CANCELLED"
        )
        response = self.dashboard()
        totals = response.context["refund_currency_totals"][0]
        self.assertEqual(totals["refund_due_total"], 0)
        self.assertEqual(totals["recorded_refund_total"], Decimal("100.00"))
        self.assertEqual(response.context["refund_review_invoice_count"], 0)

    def test_receipts_and_reversals_are_not_refunds(self):
        _, _, invoice, receipt = self.prepare()
        adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            payment=receipt,
            kind="REVERSAL",
            amount=100,
            reference="REV-ONLY",
            reason_reference="Reconciliation",
            idempotency_key=uuid.uuid4(),
        )
        response = self.dashboard()
        self.assertEqual(response.context["refund_currency_totals"], [])
        self.assertContains(response, "No refunds due or recorded")

    def test_saved_currencies_are_never_added_together(self):
        self.refundable()
        self.business.currency = "EUR"
        self.business.save(update_fields=["currency", "updated_at"])
        invoice, receipt, credit = self.refundable()
        self.refund(invoice, receipt, credit, 80)
        totals = {
            row["currency"]: row for row in self.dashboard().context["refund_currency_totals"]
        }
        self.assertEqual(set(totals), {"USD", "EUR"})
        self.assertEqual(totals["USD"]["refund_due_total"], Decimal("80.00"))
        self.assertEqual(totals["USD"]["recorded_refund_total"], 0)
        self.assertEqual(totals["EUR"]["refund_due_total"], 0)
        self.assertEqual(totals["EUR"]["recorded_refund_total"], Decimal("80.00"))
        self.assertEqual(totals["USD"]["billing_business"].currency, "USD")
        self.assertEqual(totals["EUR"]["billing_business"].currency, "EUR")

    def test_inconsistent_refund_history_is_reported_without_trusted_totals(self):
        invoice, receipt, credit = self.refundable()
        refund = self.refund(invoice, receipt, credit, 30)
        # Simulate old/corrupt ledger data without relaxing append-only services.
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE billings_invoicepayment SET currency = %s WHERE id = %s", ["EUR", refund.pk]
            )
        response = self.dashboard()
        self.assertEqual(response.context["refund_currency_totals"], [])
        self.assertEqual(response.context["refund_review_invoice_count"], 1)
        self.assertContains(response, "excluded from these amounts")

    def test_other_tenant_refunds_are_excluded(self):
        invoice = self.manual_invoice(
            business=self.other,
            client=self.other_customer,
            actor=self.other_user,
        )
        receipt = record_invoice_payment(
            business=self.other,
            actor=self.other_user,
            invoice=invoice,
            amount=100,
            currency=invoice.currency_code,
            method="CASH",
            reference="FOREIGN-CASH",
            idempotency_key=uuid.uuid4(),
        )
        adjust_invoice_payment(
            business=self.other,
            actor=self.other_user,
            invoice=invoice,
            payment=receipt,
            kind="REFUND",
            amount=99,
            reference="FOREIGN-RETURN",
            reason_reference="Refund",
            idempotency_key=uuid.uuid4(),
        )
        self.assertEqual(self.dashboard().context["refund_currency_totals"], [])

    def test_empty_refund_card_does_not_invent_statuses(self):
        response = self.dashboard()
        self.assertEqual(response.context["refund_currency_totals"], [])
        self.assertEqual(response.context["refund_review_invoice_count"], 0)
        self.assertContains(response, 'id="logistics-refunds"')
        self.assertNotContains(response, "Refund pending")
