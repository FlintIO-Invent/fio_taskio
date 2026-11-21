"""Invoice PDF layout regressions using synthetic objects and no database access."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from pypdf import PdfReader

from apps.businesses.models import Business
from apps.crm.models import Client

from .models import Invoice, InvoiceLine
from .payment_services import InvoiceSettlement
from .pdf import render_invoice_pdf, render_invoice_pdf_html
from .presentation import present_invoice


class InvoicePDFLayoutTests(SimpleTestCase):
    def setUp(self):
        self.business = Business(
            pk=101,
            name="Synthetic Services Ltd",
            vertical=Business.Vertical.SERVICE,
            currency="USD",
            tax_rate=Decimal("15.00"),
            address_line_1="123 Example Street",
            country="Sint Maarten",
            email="billing@example.test",
            phone="+1 555 0100",
        )
        self.customer = Client(
            pk=201,
            business=self.business,
            first_name="Synthetic",
            last_name="Customer",
            email="customer@example.test",
        )
        self.invoice = Invoice(
            pk=301,
            business=self.business,
            client=self.customer,
            invoice_number="SYNTHETIC-001",
            status=Invoice.Status.SENT,
            created_at=datetime(2026, 11, 16, 12, tzinfo=UTC),
            subtotal=Decimal("100.00"),
            tax=Decimal("15.00"),
            total=Decimal("115.00"),
            notes="Synthetic invoice note.\nSecond note line.",
        )
        self.lines = [
            InvoiceLine(
                invoice=self.invoice,
                description="Synthetic consultation",
                quantity=Decimal("1"),
                unit_price=Decimal("100.00"),
                line_total=Decimal("100.00"),
            )
        ]
        self.balance = InvoiceSettlement(
            invoice_id=self.invoice.pk,
            currency="USD",
            total=self.invoice.total,
            received=Decimal("40.00"),
            reductions=Decimal("0.00"),
            net_paid=Decimal("40.00"),
            outstanding=Decimal("75.00"),
            state="PARTIAL",
            settled=False,
            legacy_paid_unverified=False,
            issues=(),
            adjusted_total=self.invoice.total,
        )
        # Substitute only database-backed inputs; use the real presentation,
        # Django template and ReportLab renderer. SimpleTestCase forbids queries.
        self.enterContext(
            mock.patch(
                "apps.billings.presentation._invoice_settlement",
                side_effect=lambda invoice: self.balance,
            )
        )
        self.enterContext(mock.patch("apps.billings.pdf.load_invoice_logo", return_value=None))
        self.enterContext(
            mock.patch.object(
                Invoice,
                "lines",
                new_callable=mock.PropertyMock,
                return_value=SimpleNamespace(all=lambda: self.lines),
            )
        )
        # Access policy itself requires database memberships. It is unchanged
        # by this layout test; verify that Logistics still invokes both guards.
        self.require_access = self.enterContext(
            mock.patch("apps.logistics.financial_access.require_invoice_access")
        )
        self.project_references = self.enterContext(
            mock.patch("apps.logistics.financial_access.project_invoice_references")
        )

    def rendered(self, **kwargs):
        data = render_invoice_pdf(self.invoice, current_business=self.business, **kwargs)
        reader = PdfReader(BytesIO(data))
        text = "\n".join(page.extract_text() for page in reader.pages)
        html = render_invoice_pdf_html(self.invoice, current_business=self.business, **kwargs)
        return data, reader, text, html

    def test_services_summary_uses_saved_total_and_removes_settlement_rows(self):
        self.invoice.total = Decimal("117.31")
        self.balance = replace(self.balance, currency="XCD")
        _, reader, text, html = self.rendered()
        for content in (text, html):
            for label in (
                "Original invoice total",
                "Net payments received",
                "Balance due",
                "Refund due",
            ):
                self.assertNotIn(label, content)
            for label in ("Subtotal", "Tax (15.00%)", "Total Amount"):
                self.assertIn(label, content)
            self.assertIn("XCD 117.31", content)
            self.assertNotIn("USD 117.31", content)
        self.assertInHTML("<strong>Total Amount</strong>", html)
        total_fonts = []

        def collect_total_font(text, cm, tm, font, size):
            if "Total Amount" in text:
                total_fonts.append((font["/BaseFont"], size))

        for page in reader.pages:
            page.extract_text(visitor_text=collect_total_font)
        self.assertEqual(len(total_fonts), 1)
        self.assertIn("Manrope", total_fonts[0][0])
        self.assertEqual(total_fonts[0][1], 12)

    def test_issuer_customer_invoice_identity_status_and_notes_are_preserved(self):
        for content in self.rendered()[2:]:
            for value in (
                self.business.name,
                self.business.address_line_1,
                self.business.email,
                self.business.phone,
                "Synthetic Customer",
                self.customer.email,
                self.invoice.invoice_number,
                "Nov 16, 2026",
                "Notes",
                "Second note line.",
            ):
                self.assertIn(value, content)
            self.assertNotIn("Payment status:", content)
            self.assertNotIn("Partially paid", content)

    def test_tax_is_omitted_when_zero(self):
        self.invoice.tax = Decimal("0.00")
        self.invoice.total = self.invoice.subtotal
        for content in self.rendered()[2:]:
            self.assertNotIn("Tax (", content)
            self.assertIn("Total Amount", content)

    def test_notes_follow_existing_include_notes_flag_and_empty_value(self):
        for content in self.rendered(include_notes=False)[2:]:
            self.assertNotIn("Notes", content)
            self.assertNotIn("Synthetic invoice note.", content)
        self.invoice.notes = ""
        for content in self.rendered()[2:]:
            self.assertNotIn("Notes", content)

    def test_services_hide_payment_status_and_preserve_accounting_review(self):
        for outstanding, expected in (("115.00", "Unpaid"), ("0.00", "Paid")):
            with self.subTest(expected=expected):
                self.balance = replace(self.balance, outstanding=Decimal(outstanding))
                self.assertEqual(present_invoice(self.invoice).payment_label, expected)
                for content in self.rendered()[2:]:
                    self.assertNotIn("Payment status:", content)
                    self.assertNotIn(expected, content)
        self.balance = replace(self.balance, issues=("Synthetic accounting issue.",))
        for content in self.rendered()[2:]:
            self.assertIn("Accounting review required", content)
            self.assertIn("Synthetic accounting issue.", content)

    def test_draft_cancelled_and_legacy_statuses_are_preserved(self):
        for status, label in (
            (Invoice.Status.DRAFT, "Draft"),
            (Invoice.Status.CANCELLED, "Cancelled"),
            (Invoice.Status.PAID, "Issued"),
        ):
            with self.subTest(status=status):
                self.invoice.status = status
                for content in self.rendered()[2:]:
                    if status == Invoice.Status.CANCELLED:
                        self.assertIn(label, content)
                    self.assertNotIn("Draft", content)
                    self.assertNotIn("Invoice status:", content)
                    self.assertIn("Total Amount", content)
                self.assertEqual(self.invoice.status, status)

    def test_multipage_invoice_keeps_total_and_notes(self):
        self.lines *= 70
        _, reader, text, _ = self.rendered()
        self.assertGreater(len(reader.pages), 1)
        self.assertEqual(text.count("Total Amount"), 1)
        self.assertIn("USD 115.00", text)
        self.assertIn("Second note line.", text)

    def test_logistics_keeps_settlement_rows_credits_refunds_and_access_guards(self):
        self.business.vertical = Business.Vertical.LOGISTICS
        self.balance = replace(
            self.balance,
            credits=Decimal("20.00"),
            adjusted_total=Decimal("95.00"),
            refund_due=Decimal("10.00"),
        )
        for content in self.rendered()[2:]:
            for label in (
                "Original invoice total",
                "Net payments received",
                "Balance due",
                "Refund due",
                "Cancellation credits",
                "Adjusted invoice amount",
            ):
                self.assertIn(label, content)
            self.assertNotIn("Total Amount", content)
            self.assertIn("USD 10.00", content)
            self.assertIn("Payment status:", content)
            self.assertIn("Partially paid", content)
        self.assertEqual(self.require_access.call_count, 2)
        self.assertEqual(self.project_references.call_count, 2)

    def test_cross_workspace_pdf_rendering_still_rejects_access(self):
        for render in (render_invoice_pdf, render_invoice_pdf_html):
            with self.assertRaisesMessage(ValueError, "current workspace"):
                render(self.invoice, current_business=Business(pk=999))
