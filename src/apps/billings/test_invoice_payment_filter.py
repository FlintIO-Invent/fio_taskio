"""Payment filters use validated balances within the active workspace."""

from django.db import connection
from django.test import TestCase
from django.urls import reverse

from . import test_payments as fixtures
from .models import InvoicePayment


class InvoicePaymentFilterTests(TestCase):
    setUp = fixtures.CustomerPaymentTests.setUp
    make_invoice = fixtures.CustomerPaymentTests.make_invoice
    receipt = fixtures.CustomerPaymentTests.receipt
    adjustment = fixtures.CustomerPaymentTests.adjustment

    def filtered(self, status):
        response = self.client.get(reverse("invoice_list"), {"status": status})
        self.assertEqual(response.status_code, 200)
        return response

    def test_unpaid_partial_and_combined_filters_use_balances_not_lifecycle(self):
        unpaid = self.invoice
        partial = self.make_invoice()
        self.receipt(40, invoice=partial)
        settled_sent = self.make_invoice()
        self.receipt(100, invoice=settled_sent)
        for status in ("DRAFT", "CANCELLED", "PAID"):
            self.make_invoice(status=status)
        self.make_invoice(total=0)
        ledger_count = InvoicePayment.objects.count()

        for status, expected in (
            ("UNPAID", [unpaid]),
            ("PARTIAL", [partial]),
            ("OUTSTANDING", [partial, unpaid]),
        ):
            with self.subTest(status=status):
                response = self.filtered(status)
                self.assertEqual(list(response.context["invoices"]), expected)
                self.assertContains(response, f'<option value="{status}" selected>')
        self.assertEqual(InvoicePayment.objects.count(), ledger_count)
        settled_sent.refresh_from_db()
        self.assertEqual(settled_sent.status, "SENT")

    def test_refunds_and_reversals_reopen_the_correct_payment_filter(self):
        receipt = self.receipt()
        self.adjustment(receipt, 30)
        self.assertEqual(list(self.filtered("PARTIAL").context["invoices"]), [self.invoice])
        self.adjustment(receipt, 70, kind="REVERSAL")
        self.assertEqual(list(self.filtered("PARTIAL").context["invoices"]), [])
        self.assertEqual(list(self.filtered("UNPAID").context["invoices"]), [self.invoice])

    def test_other_workspace_and_inconsistent_history_are_excluded(self):
        other = self.make_invoice(business=self.other, client=self.other_customer)
        self.receipt(40, business=self.other, actor=self.other_user, invoice=other)
        receipt = self.receipt(40)
        # Simulate damaged imported history, which must require accounting review.
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE billings_invoicepayment SET invoice_total_snapshot = %s WHERE id = %s",
                [99, receipt.pk],
            )

        for status in ("UNPAID", "PARTIAL", "OUTSTANDING"):
            with self.subTest(status=status):
                response = self.filtered(status)
                self.assertEqual(list(response.context["invoices"]), [])
                self.assertNotContains(response, other.invoice_number)

    def test_empty_states_describe_the_selected_payment_filter(self):
        self.receipt()
        for status, label in (
            ("UNPAID", "unpaid"),
            ("PARTIAL", "partially paid"),
            ("OUTSTANDING", "unpaid or partially paid"),
        ):
            with self.subTest(status=status):
                self.assertContains(self.filtered(status), f"No {label} invoices found.")
