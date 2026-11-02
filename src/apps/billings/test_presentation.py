"""Customer-facing vocabulary must follow accounting without rewriting history."""

import json
import uuid
from io import BytesIO
from unittest import mock

from django.contrib.admin.sites import AdminSite
from django.core import mail
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.logistics import test_cancellation_settlement as cancellation_fixtures
from apps.logistics.credit_services import approve_credit, credit_review, fingerprint
from apps.logistics.parcel_services import change_parcel_status
from apps.logistics.workflow_summary import resolve_parcel_workflow

from . import test_payments as fixtures
from .admin import InvoiceAdmin
from .models import Invoice, InvoicePayment
from .pdf import render_invoice_pdf, render_invoice_pdf_html
from .presentation import present_invoice
from .services import change_invoice_status


class InvoicePresentationTests(TestCase):
    setUp = fixtures.CustomerPaymentTests.setUp
    make_invoice = fixtures.CustomerPaymentTests.make_invoice
    receipt = fixtures.CustomerPaymentTests.receipt
    adjustment = fixtures.CustomerPaymentTests.adjustment
    balance = fixtures.CustomerPaymentTests.balance

    def filtered(self, status):
        response = self.client.get(reverse("invoice_list"), {"status": status})
        self.assertEqual(response.status_code, 200)
        return response

    def email(self, invoice):
        self.customer.email = "customer@example.test"
        self.customer.save(update_fields=["email"])
        response = self.client.post(reverse("invoice_email_send", args=[invoice.pk]))
        self.assertEqual(response.status_code, 302)
        return mail.outbox[-1]

    def pdf_text(self, invoice):
        return "\n".join(
            page.extract_text() for page in PdfReader(BytesIO(render_invoice_pdf(invoice))).pages
        )

    def test_paid_filter_is_receipt_backed_and_legacy_records_are_review_only(self):
        self.receipt()
        legacy = self.make_invoice(status="PAID")
        paid = self.filtered("PAID")
        self.assertEqual(list(paid.context["invoices"]), [self.invoice])
        outstanding = self.filtered("OUTSTANDING")
        self.assertEqual(list(outstanding.context["invoices"]), [])
        self.assertEqual(outstanding.context["review_invoices"], [legacy])
        self.assertContains(outstanding, "Verify payment evidence before requesting payment")
        detail = self.client.get(reverse("invoice_detail", args=[legacy.pk]))
        self.assertContains(detail, "Manually marked paid — unverified")
        self.assertNotContains(
            detail, 'href="' + reverse("invoice_payment_record", args=[legacy.pk]) + '"'
        )
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, "PAID")
        self.assertFalse(legacy.payments.exists())
        reconciliation = self.client.get(reverse("invoice_payment_record", args=[legacy.pk]))
        self.assertIsNone(reconciliation.context["form"].initial["amount"])
        self.assertContains(reconciliation, "review before requesting payment")

    def test_partial_and_refunded_manual_paid_invoice_never_displays_paid_payment_status(self):
        self.invoice.status = "PAID"
        self.invoice.save()
        receipt = self.receipt(40)
        self.assertEqual(present_invoice(self.invoice).payment_label, "Partially paid")
        self.assertEqual(list(self.filtered("PARTIAL").context["invoices"]), [self.invoice])
        self.adjustment(receipt, 40)
        self.assertEqual(present_invoice(self.invoice).payment_label, "Unpaid")
        self.assertEqual(list(self.filtered("UNPAID").context["invoices"]), [self.invoice])
        self.assertEqual(list(self.filtered("PAID").context["invoices"]), [])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "PAID")

    def test_partial_balance_and_vocabulary_agree_across_html_client_email_pdf_and_admin(self):
        self.receipt(40)
        detail = self.client.get(reverse("invoice_detail", args=[self.invoice.pk]))
        listing = self.filtered("OUTSTANDING")
        client = self.client.get(reverse("staff_client_detail", args=[self.customer.pk]))
        pdf_html = render_invoice_pdf_html(self.invoice)
        pdf = self.pdf_text(self.invoice)
        email = self.email(self.invoice)
        for response in (detail, listing, client):
            self.assertContains(response, "Issued")
            self.assertContains(response, "Partially paid")
            self.assertContains(response, "60.00")
        for content in (pdf_html, pdf, email.body, email.alternatives[0].content):
            self.assertIn("Issued", content)
            self.assertIn("Partially paid", content)
            self.assertIn("Original invoice total", content)
            self.assertIn("Net payments received", content)
            self.assertIn("Balance due", content)
            self.assertIn("Refund due", content)
            self.assertIn("USD 60.00", content)
        admin = InvoiceAdmin(Invoice, AdminSite())
        self.assertEqual(admin.lifecycle(self.invoice), "Issued")
        self.assertEqual(admin.payment_state(self.invoice), "Partially paid")
        self.assertIn("Balance due: USD 60.00", admin.financial_summary(self.invoice))
        self.assertEqual(admin.lifecycle(None), "Draft")

    def test_full_payment_says_paid_on_both_pdf_paths_and_keeps_sent_enum(self):
        self.receipt()
        financial = present_invoice(self.invoice)
        self.assertEqual((financial.lifecycle_label, financial.payment_label), ("Issued", "Paid"))
        self.assertIn("Payment status: Paid", self.pdf_text(self.invoice))
        self.assertIn("<strong>Paid</strong>", render_invoice_pdf_html(self.invoice))
        detail = self.client.get(reverse("invoice_detail", args=[self.invoice.pk]))
        self.assertContains(detail, ">Paid</span>")
        self.assertNotContains(detail, "Mark as Paid")
        self.assertNotContains(detail, "Settled")
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "SENT")

    def test_sending_resending_and_failed_submission_preserve_financial_state(self):
        for amount in (0, 40, 100):
            invoice = self.make_invoice()
            if amount:
                self.receipt(amount, invoice=invoice)
            before = self.balance(invoice)
            count = InvoicePayment.objects.count()
            for _ in range(2):
                message = self.email(invoice)
                self.assertIn(f"Balance due: USD {100 - amount:.2f}", message.body)
            invoice.refresh_from_db()
            self.assertEqual(invoice.status, "SENT")
            self.assertEqual(invoice.email_send_count, 2)
            self.assertEqual(self.balance(invoice), before)
            self.assertEqual(InvoicePayment.objects.count(), count)
            financial = present_invoice(invoice)
            self.assertIn("customer@example.test", financial.email_note)
            self.assertIn("Delivery to the recipient is unconfirmed", financial.email_note)
            with mock.patch("apps.billings.views.send_invoice_email", return_value=False):
                self.client.post(reverse("invoice_email_send", args=[invoice.pk]))
            invoice.refresh_from_db()
            self.assertEqual(invoice.email_send_count, 2)
            self.assertEqual(self.balance(invoice), before)

    def test_draft_cancelled_zero_value_and_legacy_zero_are_not_payment_evidence(self):
        for status in ("DRAFT", "CANCELLED"):
            invoice = self.make_invoice(status=status)
            financial = present_invoice(invoice)
            self.assertEqual(financial.payment_label, "")
            self.assertEqual(financial.balance_due, 0)
            self.assertIn("Balance due: USD 0.00", self.email(invoice).body)
        zero = self.make_invoice(total=0)
        self.assertTrue(present_invoice(zero).no_payment_required)
        self.assertFalse(present_invoice(zero).verified_paid)
        legacy_zero = self.make_invoice(total=0, status="PAID")
        self.assertTrue(present_invoice(legacy_zero).review_required)
        self.assertFalse(present_invoice(legacy_zero).no_payment_required)
        self.assertFalse(InvoicePayment.objects.exists())

    def test_saved_receipt_currency_survives_workspace_default_changes_everywhere(self):
        self.receipt(40)
        self.business.currency = "EUR"
        self.business.save(update_fields=["currency"])
        self.invoice.refresh_from_db()
        financial = present_invoice(self.invoice)
        self.assertEqual(financial.currency, "USD")
        detail = self.client.get(reverse("invoice_detail", args=[self.invoice.pk]))
        self.assertContains(
            detail, '<p class="invoice-detail-value fw-semibold">USD</p>', html=True
        )
        for content in (
            self.pdf_text(self.invoice),
            render_invoice_pdf_html(self.invoice),
            self.email(self.invoice).body,
        ):
            self.assertIn("USD 60.00", content)
            self.assertNotIn("EUR 60.00", content)
        dashboard = self.client.get(reverse("agent_dashboard"))
        currencies = {row["currency"]: row for row in dashboard.context["finance_currency_totals"]}
        self.assertEqual(currencies["USD"]["outstanding_invoice_total"], 60)
        self.assertEqual(dashboard.context["unpaid_invoice_total"], 0)
        self.assertContains(dashboard, "USD")

    def test_services_dashboard_excludes_drafts_cancelled_and_review_and_uses_remaining_balance(
        self,
    ):
        self.make_invoice(total=30, status="DRAFT")
        self.make_invoice(total=900, status="CANCELLED")
        partial = self.make_invoice()
        self.receipt(40, invoice=partial)
        full = self.make_invoice()
        self.receipt(100, invoice=full)
        legacy = self.make_invoice(status="PAID")
        other = self.make_invoice(business=self.other, client=self.other_customer, total=999)
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.context["unpaid_invoice_total"], 160)
        self.assertEqual(response.context["paid_invoice_total"], 140)
        self.assertEqual(response.context["paid_invoice_count"], 1)
        self.assertEqual(response.context["open_invoice_count"], 2)
        totals = response.context["finance_currency_totals"][0]
        self.assertEqual((totals["review_invoice_total"], totals["review_invoice_count"]), (100, 1))
        self.assertEqual(list(response.context["recent_invoices"]), [partial, self.invoice])
        self.assertNotContains(response, legacy.invoice_number)
        self.assertNotContains(response, other.invoice_number)

    def test_inconsistent_history_is_explicitly_reviewed_without_collectible_amount(self):
        receipt = self.receipt(40)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE billings_invoicepayment SET invoice_total_snapshot = %s WHERE id = %s",
                [99, receipt.pk],
            )
        response = self.filtered("OUTSTANDING")
        self.assertEqual(list(response.context["invoices"]), [])
        self.assertEqual(response.context["review_invoices"], [self.invoice])
        self.assertContains(response, "Accounting review required")
        dashboard = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(dashboard.context["unpaid_invoice_total"], 0)
        self.assertEqual(dashboard.context["finance_currency_totals"][0]["review_invoice_count"], 1)

    def test_old_mark_paid_post_routes_permitted_roles_to_receipt_without_mutating_status(self):
        for role in ("owner", "admin", "staff", "accountant"):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            response = self.client.post(
                reverse("invoice_change_status", args=[self.invoice.pk]), {"status": "PAID"}
            )
            self.assertRedirects(
                response, reverse("invoice_payment_record", args=[self.invoice.pk])
            )
            self.invoice.refresh_from_db()
            self.assertEqual(self.invoice.status, "SENT")
            self.assertFalse(self.invoice.payments.exists())
        self.membership.role = "viewer"
        self.membership.save(update_fields=["role"])
        response = self.client.post(
            reverse("invoice_change_status", args=[self.invoice.pk]), {"status": "PAID"}
        )
        self.assertNotEqual(response.url, reverse("invoice_payment_record", args=[self.invoice.pk]))
        self.assertFalse(self.invoice.payments.exists())

    def test_delete_endpoint_and_admin_retain_every_non_draft_invoice(self):
        admin = InvoiceAdmin(Invoice, AdminSite())
        self.user.is_staff = self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])
        request = RequestFactory().get("/admin/")
        request.user = self.user
        for status in ("SENT", "PAID", "CANCELLED"):
            invoice = self.make_invoice(status=status)
            self.client.post(reverse("invoice_delete", args=[invoice.pk]))
            self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())
            self.assertFalse(admin.has_delete_permission(request, invoice))
            with self.assertRaises(ProtectedError):
                admin.delete_model(request, invoice)
        draft = self.make_invoice(status="DRAFT")
        self.assertTrue(admin.has_delete_permission(request, draft))
        self.client.post(reverse("invoice_delete", args=[draft.pk]))
        self.assertFalse(Invoice.objects.filter(pk=draft.pk).exists())
        self.assertNotIn("status", admin.get_form(request, self.invoice).base_fields)
        self.assertNotIn("delete_selected", admin.get_actions(request))


class LogisticsInvoicePresentationTests(TestCase):
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
    balance = cancellation_fixtures.CancellationSettlementTests.balance

    def test_fully_credited_without_receipts_is_not_paid(self):
        parcel, _, invoice, _ = self.prepare(collected=0)
        self.settle(parcel)
        invoice.refresh_from_db()
        financial = present_invoice(invoice)
        self.assertTrue(self.balance(invoice).settled)
        self.assertTrue(financial.no_payment_required)
        self.assertFalse(financial.verified_paid)
        self.assertIn("Fully credited", financial.note)
        summary = resolve_parcel_workflow(business=self.business, actor=self.user, parcel=parcel)
        self.assertEqual(summary.financial["state_label"], "No payment required")
        # The existing native Decimal/datetime workflow contract stays serializable
        # without leaking Business model objects or private receipt details.
        serialized = json.dumps(summary.to_dict(), cls=DjangoJSONEncoder)
        self.assertNotIn("billing_business", serialized)
        response = self.client.get(reverse("invoice_list"), {"status": "PAID"})
        self.assertEqual(list(response.context["invoices"]), [])
        self.assertFalse(InvoicePayment.objects.exists())

    def test_retained_paid_obligation_and_refund_due_have_separate_indicators(self):
        parcel, _, invoice, receipt = self.prepare(paid=True)
        self.business.cancellation_service_charge = 20
        self.business.save(update_fields=["cancellation_service_charge"])
        credit = self.settle(parcel).credits.get()
        invoice.refresh_from_db()
        financial = present_invoice(invoice)
        self.assertEqual(financial.payment_label, "Paid")
        self.assertEqual((financial.balance_due, financial.balance.refund_due), (0, 80))
        self.assertFalse(self.balance(invoice).settled)
        self.assertIn("Refund due", InvoiceAdmin(Invoice, AdminSite()).payment_state(invoice))
        self.assertEqual(
            list(self.client.get(reverse("invoice_list"), {"status": "PAID"}).context["invoices"]),
            [invoice],
        )
        self.refund(invoice, receipt, credit, 30)
        self.assertEqual(present_invoice(invoice).balance.refund_due, 50)
        self.assertEqual(present_invoice(invoice).payment_label, "Paid")
        for content in (
            render_invoice_pdf_html(invoice, actor=self.user),
            "\n".join(
                page.extract_text()
                for page in PdfReader(BytesIO(render_invoice_pdf(invoice, actor=self.user))).pages
            ),
        ):
            self.assertIn("Cancellation credits", content)
            self.assertIn("Adjusted invoice amount", content)
            self.assertIn("Refund due", content)
            self.assertIn("USD 50.00", content)

    def test_shared_invoice_debt_is_collectible_even_with_refund_liability(self):
        a, b = self.parcel(), self.parcel()
        invoice = self.bill(
            self.charge(parcel=a, unit_price=100), self.charge(parcel=b, unit_price=100)
        )
        self.issue(invoice)
        line = invoice.lines.get(parcel=a)
        receipt = self.receipt(invoice, 100)
        choices = {
            "invoices": {
                str(invoice.pk): {"receipts": {str(receipt.pk): {f"{line.pk}:{a.pk}": "100"}}}
            }
        }
        change_parcel_status(business=self.business, actor=self.user, parcel=a, status="CANCELLED")
        self.settle(a, choices=choices)
        invoice.refresh_from_db()
        financial = present_invoice(invoice)
        self.assertEqual((financial.balance_due, financial.balance.refund_due), (100, 100))
        self.assertEqual(financial.payment_label, "Unpaid")
        response = self.client.get(reverse("invoice_list"), {"status": "OUTSTANDING"})
        self.assertEqual(list(response.context["invoices"]), [invoice])
        dashboard = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(dashboard.context["outstanding_invoice_total"], 100)
        self.assertEqual(dashboard.context["refund_currency_totals"][0]["refund_due_total"], 100)
        before = self.balance(invoice)
        response = self.client.post(reverse("invoice_email_send", args=[invoice.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("Original invoice total: USD 200.00", mail.outbox[-1].body)
        self.assertIn("Balance due: USD 100.00", mail.outbox[-1].body)
        self.assertIn("Refund due: USD 100.00", mail.outbox[-1].body)
        self.assertEqual(self.balance(invoice), before)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "SENT")

    def test_approved_credit_never_displays_paid_or_accepts_payment_decision_without_receipt(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        snapshot = credit_review(business=self.business, actor=self.user, parcel=parcel)
        approve_credit(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            status="IN_TRANSIT",
            expires_at=timezone.now() + timezone.timedelta(days=1),
            reason_reference="CASE-CREDIT",
            obligation_fingerprint=fingerprint(snapshot),
            idempotency_key=uuid.uuid4(),
        )
        summary = resolve_parcel_workflow(business=self.business, actor=self.user, parcel=parcel)
        self.assertTrue(summary.financial["clearance"]["via_credit"])
        self.assertEqual(summary.financial["state_label"], "Unpaid")
        url = reverse("logistics_parcel_registration", args=[parcel.pk])
        response = self.client.post(url, {"action": "payment", "decision": "record"})
        self.assertContains(response, "Create and issue an Invoice")
        self.assertFalse(InvoicePayment.objects.exists())
        response = self.client.post(url, {"action": "payment", "decision": "continue"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session[f"parcel_payment_decision_{self.business.pk}_{parcel.pk}"],
            "continue",
        )
        self.assertEqual(self.balance(invoice).outstanding, 100)

    def test_registration_partial_receipt_records_an_action_not_a_paid_flag(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        url = reverse("logistics_parcel_registration", args=[parcel.pk])
        response = self.client.post(
            url,
            {
                "action": "payment",
                "decision": "record",
                "invoice": invoice.pk,
                "amount": "40",
                "method": "CASH",
                "idempotency_key": uuid.uuid4(),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session[f"parcel_payment_decision_{self.business.pk}_{parcel.pk}"], "record"
        )
        invoice.refresh_from_db()
        self.assertEqual(present_invoice(invoice).payment_label, "Partially paid")
        response = self.client.get(url)
        self.assertContains(response, "Record payment received")
        self.assertContains(response, "Continue without recording a payment")
        self.assertNotContains(response, "Paid · record")
        self.assertEqual(self.balance(invoice).outstanding, 60)

    def test_legacy_paid_is_review_only_on_logistics_dashboard(self):
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.issue(invoice)
        change_invoice_status(
            business=self.business, actor=self.user, invoice=invoice, status="PAID"
        )
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.context["outstanding_invoice_total"], 0)
        self.assertEqual(response.context["paid_invoice_total"], 0)
        self.assertEqual(
            response.context["finance_currency_totals"][0]["review_invoice_total"], 100
        )
        self.assertEqual(
            list(
                self.client.get(reverse("invoice_list"), {"status": "REVIEW"}).context["invoices"]
            ),
            [invoice],
        )
