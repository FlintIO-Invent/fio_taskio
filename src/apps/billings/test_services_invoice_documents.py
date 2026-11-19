"""Services customer documents retain saved facts, disclosures and document guards."""

import importlib.util
import os
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
from pypdf import PdfReader

from . import test_pdf_layout as fixtures
from .models import Invoice
from .pdf import render_invoice_pdf


class ServicesInvoiceDocumentTests(SimpleTestCase):
    setUp = fixtures.InvoicePDFLayoutTests.setUp
    rendered = fixtures.InvoicePDFLayoutTests.rendered

    def test_customer_draft_is_clean_but_internal_enum_survives(self):
        self.invoice.status = Invoice.Status.DRAFT
        for content in self.rendered()[2:]:
            self.assertNotIn("Draft", content)
            self.assertNotIn("Invoice status", content)
            self.assertNotIn("Balance due", content)
            self.assertIn("Subtotal", content)
            self.assertIn("Total Amount", content)
        self.assertEqual(self.invoice.status, "DRAFT")

    def test_long_notes_and_descriptions_wrap_and_keep_page_identity(self):
        self.lines *= 55
        self.lines[0].description = "Long uninterrupted description " + "Example" * 50
        self.invoice.notes = "Notes shared on download. " * 350
        _, reader, text, _ = self.rendered()
        self.assertGreater(len(reader.pages), 4)
        self.assertEqual(text.count("Total Amount"), 1)
        for index, page in enumerate(reader.pages, 1):
            self.assertIn(f"Page {index} of {len(reader.pages)}", page.extract_text())
            self.assertIn(self.invoice.invoice_number, page.extract_text())
        self.assertIn("Notes shared on download.", text)
        self.assertNotIn("Notes shared on download.", self.rendered(include_notes=False)[2])

    def test_cancellation_review_and_refund_explanations_remain(self):
        self.invoice.status = Invoice.Status.CANCELLED
        self.balance = replace(self.balance, refund_due=Decimal("10"))
        for content in self.rendered()[2:]:
            self.assertIn("Cancelled", content)
            self.assertIn("Money has not been recorded as returned", content)
        self.balance = replace(self.balance, issues=("Currency evidence needs review.",))
        for content in self.rendered()[2:]:
            self.assertIn("Accounting review required", content)
            self.assertIn("Currency evidence needs review.", content)

    def test_logistics_document_matches_frozen_before(self):
        source = os.environ.get("SERVICES_INVOICES_BEFORE")
        if not source:
            self.skipTest("Frozen BEFORE source supplied by guarded review adapter only.")
        path = Path(source) / "src/apps/billings/pdf.py"
        spec = importlib.util.spec_from_file_location("apps.billings._invoice_pdf_before", path)
        before = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(before)
        self.business.vertical = "LOGISTICS"
        with mock.patch.object(before, "load_invoice_logo", return_value=None):
            expected = before.render_invoice_pdf(self.invoice)
            actual = render_invoice_pdf(self.invoice)
            # Compare full decoded page operations, geometry and resources: metadata timestamps
            # and randomized document IDs are intentionally excluded from the PDF comparison.
            old, new = PdfReader(BytesIO(expected)), PdfReader(BytesIO(actual))
            self.assertEqual(len(old.pages), len(new.pages))
            for original, candidate in zip(old.pages, new.pages, strict=True):
                self.assertEqual(
                    original.get_contents().get_data(), candidate.get_contents().get_data()
                )
                self.assertEqual(original.mediabox, candidate.mediabox)
                self.assertEqual(original.extract_text(), candidate.extract_text())
