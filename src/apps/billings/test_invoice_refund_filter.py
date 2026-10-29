"""Recorded refunds can be filtered independently of invoice lifecycle status."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.logistics import test_cancellation_settlement as cancellation_fixtures

from . import test_payments as fixtures
from .models import InvoiceCancellationCredit, InvoicePayment
from .services import change_invoice_status


class InvoiceRefundFilterTests(TestCase):
    setUp = fixtures.CustomerPaymentTests.setUp
    make_invoice = fixtures.CustomerPaymentTests.make_invoice
    receipt = fixtures.CustomerPaymentTests.receipt
    adjustment = fixtures.CustomerPaymentTests.adjustment

    def filtered(self):
        return self.client.get(reverse("invoice_list"), {"status": "REFUNDED"})

    def test_partial_refunds_show_invoice_once_with_selected_filter(self):
        receipt = self.receipt()
        self.adjustment(receipt, 20)
        self.adjustment(receipt, 10)
        self.make_invoice()

        response = self.filtered()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["invoices"]), [self.invoice])
        self.assertContains(response, "including partial refunds")
        self.assertContains(
            response,
            '<option value="REFUNDED" selected>Refunded</option>',
            html=True,
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "SENT")

    def test_full_refunds_include_cancelled_and_paid_invoices(self):
        cancelled = self.invoice
        receipt = self.receipt()
        self.adjustment(receipt, 100)
        change_invoice_status(
            business=self.business, actor=self.user, invoice=cancelled, status="CANCELLED"
        )
        self.invoice = self.make_invoice()
        receipt = self.receipt()
        change_invoice_status(
            business=self.business, actor=self.user, invoice=self.invoice, status="PAID"
        )
        self.adjustment(receipt, 100)

        response = self.filtered()

        self.assertEqual(list(response.context["invoices"]), [self.invoice, cancelled])
        self.assertEqual(
            [invoice.status for invoice in response.context["invoices"]],
            ["PAID", "CANCELLED"],
        )

    def test_receipts_reversals_and_other_business_refunds_are_excluded(self):
        self.receipt(50)
        reversal = self.receipt(50)
        self.adjustment(reversal, 50, kind="REVERSAL")
        other = self.make_invoice(business=self.other, client=self.other_customer)
        receipt = self.receipt(business=self.other, actor=self.other_user, invoice=other)
        self.adjustment(receipt, 100, business=self.other, actor=self.other_user, invoice=other)

        response = self.filtered()

        self.assertEqual(list(response.context["invoices"]), [])
        self.assertContains(response, "No invoices with recorded refunds found.")
        self.assertNotContains(response, other.invoice_number)

    def test_existing_lifecycle_filters_and_all_remain_available(self):
        draft = self.make_invoice(status="DRAFT")
        receipt = self.receipt()
        self.adjustment(receipt, 15)

        response = self.client.get(reverse("invoice_list"), {"status": "DRAFT"})
        self.assertEqual(list(response.context["invoices"]), [draft])
        response = self.client.get(reverse("invoice_list"), {"status": "SENT"})
        self.assertEqual(list(response.context["invoices"]), [self.invoice])
        response = self.client.get(reverse("invoice_list"))
        self.assertEqual(list(response.context["invoices"]), [draft, self.invoice])
        self.assertContains(response, '<option value="REFUNDED">Refunded</option>', html=True)


class InvoiceRefundDueFilterTests(TestCase):
    setUp = cancellation_fixtures.CancellationSettlementTests.setUp
    parcel = cancellation_fixtures.CancellationSettlementTests.parcel
    shipment = cancellation_fixtures.CancellationSettlementTests.shipment
    charge = cancellation_fixtures.CancellationSettlementTests.charge
    bill = cancellation_fixtures.CancellationSettlementTests.bill
    issue = cancellation_fixtures.CancellationSettlementTests.issue
    receipt = cancellation_fixtures.CancellationSettlementTests.receipt
    prepare = cancellation_fixtures.CancellationSettlementTests.prepare
    settle = cancellation_fixtures.CancellationSettlementTests.settle
    refund = cancellation_fixtures.CancellationSettlementTests.refund

    def filtered(self, status="REFUND_DUE"):
        response = self.client.get(reverse("invoice_list"), {"status": status})
        self.assertEqual(response.status_code, 200)
        return response

    def test_due_refunds_on_sent_and_paid_invoices_are_separate_from_recorded_refunds(self):
        invoices = []
        for paid in (False, True):
            parcel, charge, invoice, _ = self.prepare(paid=paid)
            self.business.cancellation_service_charge = Decimal("20")
            self.business.save(update_fields=["cancellation_service_charge"])
            self.settle(parcel)
            invoices.insert(0, invoice)
        counts = (InvoicePayment.objects.count(), InvoiceCancellationCredit.objects.count())

        response = self.filtered()

        self.assertEqual(list(response.context["invoices"]), invoices)
        self.assertContains(response, "awaiting a recorded return of funds")
        self.assertEqual(list(self.filtered("REFUNDED").context["invoices"]), [])
        self.assertContains(self.filtered("REFUNDED"), 'href="?status=REFUND_DUE"')
        self.assertEqual(
            (InvoicePayment.objects.count(), InvoiceCancellationCredit.objects.count()), counts
        )

    def test_partial_refund_stays_due_until_return_is_fully_recorded(self):
        parcel, charge, invoice, receipt = self.prepare(paid=True)
        self.business.cancellation_service_charge = Decimal("20")
        self.business.save(update_fields=["cancellation_service_charge"])
        settlement = self.settle(parcel)
        credit = settlement.credits.get()
        self.refund(invoice, receipt, credit, 30)

        self.assertEqual(list(self.filtered().context["invoices"]), [invoice])
        self.assertEqual(list(self.filtered("REFUNDED").context["invoices"]), [invoice])
        self.refund(invoice, receipt, credit, 50, reference="RETURN-2")
        self.assertEqual(list(self.filtered().context["invoices"]), [])
        self.assertEqual(list(self.filtered("REFUNDED").context["invoices"]), [invoice])

    def test_cancellation_credit_without_overpayment_is_not_a_refund_due(self):
        parcel, charge, _, _ = self.prepare(collected=10)
        self.business.cancellation_service_charge = Decimal("20")
        self.business.save(update_fields=["cancellation_service_charge"])
        self.settle(parcel)

        response = self.filtered()

        self.assertEqual(list(response.context["invoices"]), [])
        self.assertContains(response, "No invoices with refunds due found.")

    def test_payment_filters_respect_cancellation_credits_and_refunds_due(self):
        self.business.cancellation_service_charge = Decimal("20")
        self.business.save(update_fields=["cancellation_service_charge"])
        invoices = []
        for collected in (0, 10, 20, 100):
            parcel, _, invoice, _ = self.prepare(collected=collected)
            self.settle(parcel)
            invoices.append(invoice)

        for status, expected in (
            ("UNPAID", [invoices[0]]),
            ("PARTIAL", [invoices[1]]),
            ("OUTSTANDING", [invoices[1], invoices[0]]),
        ):
            with self.subTest(status=status):
                self.assertEqual(list(self.filtered(status).context["invoices"]), expected)
