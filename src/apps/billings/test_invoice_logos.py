"""Invoice download, email and HTML branding use the current tenant's logo."""

from io import BytesIO

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from pypdf import PdfReader

from apps.businesses.invoice_logos import normalize_invoice_logo
from apps.businesses.models import BusinessInvoiceLogo
from apps.businesses.test_invoice_logos import logo_upload
from apps.logistics import test_cancellation_settlement as logistics_fixtures

from . import test_payments as fixtures
from .models import InvoiceLine
from .pdf import (
    LEFT_MARGIN,
    PAGE_HEIGHT,
    TOP_MARGIN,
    _header_lines,
    render_invoice_pdf,
    render_invoice_pdf_html,
)


class InvoiceLogoPDFTests(TestCase):
    setUp = fixtures.CustomerPaymentTests.setUp
    make_invoice = fixtures.CustomerPaymentTests.make_invoice

    def save_logo(self, business=None, **kwargs):
        data = normalize_invoice_logo(logo_upload(**kwargs))
        BusinessInvoiceLogo.objects.update_or_create(
            business=business or self.business, defaults={"png_data": data}
        )
        return data

    def pdf(self):
        return PdfReader(BytesIO(render_invoice_pdf(self.invoice)))

    def test_no_logo_and_corrupt_logo_keep_invoice_available_with_text_header(self):
        for data in (None, b"corrupt"):
            if data is not None:
                BusinessInvoiceLogo.objects.create(business=self.business, png_data=data)
                with self.assertLogs("apps.businesses.invoice_logos", level="WARNING"):
                    pdf = self.pdf()
            else:
                pdf = self.pdf()
            self.assertEqual(len(pdf.pages[0].images), 0)
            self.assertIn(self.business.name, pdf.pages[0].extract_text())
            self.assertIn("USD 100.00", pdf.pages[0].extract_text())

    def test_download_email_and_html_embed_logo_without_changing_invoice(self):
        self.save_logo()
        before = (self.invoice.total, self.invoice.status, self.invoice.subtotal, self.invoice.tax)
        response = self.client.get(reverse("invoice_pdf_download", args=[self.invoice.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(PdfReader(BytesIO(response.content)).pages[0].images), 1)
        html = render_invoice_pdf_html(self.invoice)
        self.assertIn('src="data:image/png;base64,', html)
        self.assertIn(self.business.name + " logo", html)
        self.customer.email = "logo-invoice@example.test"
        self.customer.save(update_fields=["email"])
        self.assertEqual(
            self.client.post(reverse("invoice_email_send", args=[self.invoice.pk])).status_code, 302
        )
        name, data, content_type = mail.outbox[-1].attachments[0]
        self.assertTrue(name.endswith(".pdf"))
        self.assertEqual(content_type, "application/pdf")
        self.assertEqual(len(PdfReader(BytesIO(data)).pages[0].images), 1)
        self.invoice.refresh_from_db()
        self.assertEqual(
            (self.invoice.total, self.invoice.status, self.invoice.subtotal, self.invoice.tax),
            before,
        )
        self.assertFalse(self.invoice.payments.exists())

    def test_old_invoice_regeneration_uses_replaced_logo_then_text_after_removal(self):
        self.save_logo(color=(220, 10, 10, 255))
        old_pdf = render_invoice_pdf(self.invoice)
        self.save_logo(color=(10, 10, 220, 255))
        old_image = PdfReader(BytesIO(old_pdf)).pages[0].images[0].image
        new_image = self.pdf().pages[0].images[0].image
        self.assertEqual(old_image.getpixel((0, 0)), (220, 10, 10, 255))
        self.assertEqual(new_image.getpixel((0, 0)), (10, 10, 220, 255))
        BusinessInvoiceLogo.objects.filter(business=self.business).delete()
        self.assertEqual(len(self.pdf().pages[0].images), 0)

    def test_other_business_logo_is_not_used_or_exposed(self):
        self.save_logo(business=self.other, color=(255, 0, 0, 255))
        self.assertEqual(len(self.pdf().pages[0].images), 0)
        self.assertNotIn("data:image/png", render_invoice_pdf_html(self.invoice))
        other_invoice = self.make_invoice(business=self.other, client=self.other_customer)
        response = self.client.get(reverse("invoice_pdf_download", args=[other_invoice.pk]))
        self.assertEqual(response.status_code, 404)
        with self.assertRaises(ValueError):
            render_invoice_pdf(self.invoice, current_business=self.other)

    def test_portrait_wide_and_transparent_logos_fit_and_multipage_invoices_keep_totals(self):
        for size in ((1000, 100), (100, 1000), (250, 250)):
            self.save_logo(size=size)
            pdf = self.pdf()
            image = pdf.pages[0].images[0].image
            with Image.open(
                BytesIO(BusinessInvoiceLogo.objects.get(business=self.business).png_data)
            ) as stored:
                self.assertEqual(image.size, stored.size)
            # Inspect actual drawing transforms rather than just the image object's pixel size.
            placements = []

            def draw(operator, operands, _cm, _tm, placements=placements):
                if operator == b"cm":
                    placements.append(tuple(float(value) for value in operands))

            pdf.pages[0].extract_text(visitor_operand_before=draw)
            logo_transform = next(row for row in placements if row[4] == LEFT_MARGIN and row[0] > 1)
            self.assertLessEqual(logo_transform[0], 144)
            self.assertLessEqual(logo_transform[3], 54)
            self.assertLessEqual(logo_transform[5] + logo_transform[3], PAGE_HEIGHT - TOP_MARGIN)
        self.business.name = "CaribbeanPropertyEquipmentMaintenance" * 3
        self.business.address_line_1 = "A long company address beside the harbor " * 4
        self.business.email = "very-long-company-contact-address@example.test"
        self.business.save()
        for index in range(60):
            InvoiceLine.objects.create(
                invoice=self.invoice, description=f"Additional service line {index}", unit_price=0
            )
        pdf = self.pdf()
        self.assertGreater(len(pdf.pages), 1)
        self.assertEqual(len(pdf.pages[0].images), 1)
        self.assertTrue(all(not list(page.images) for page in pdf.pages[1:]))
        text = "\n".join(page.extract_text() for page in pdf.pages)
        self.assertIn("USD 100.00", text)
        self.assertIn("Additional service line 59", text)
        from reportlab.pdfbase.pdfmetrics import stringWidth

        for line in _header_lines(self.business.name, "Helvetica-Bold", 18):
            self.assertLessEqual(stringWidth(line, "Helvetica-Bold", 18), 240)


class LogisticsInvoiceLogoPDFTests(TestCase):
    setUp = logistics_fixtures.CancellationSettlementTests.setUp
    parcel = logistics_fixtures.CancellationSettlementTests.parcel
    shipment = logistics_fixtures.CancellationSettlementTests.shipment
    charge = logistics_fixtures.CancellationSettlementTests.charge
    bill = logistics_fixtures.CancellationSettlementTests.bill
    issue = logistics_fixtures.CancellationSettlementTests.issue
    receipt = logistics_fixtures.CancellationSettlementTests.receipt
    cargo = logistics_fixtures.CancellationSettlementTests.cargo

    def test_logistics_pdf_and_html_reuse_branding_and_existing_financial_scope(self):
        charge = self.charge(parcel=self.parcel(), unit_price=100)
        invoice = self.bill(charge)
        data = normalize_invoice_logo(logo_upload())
        BusinessInvoiceLogo.objects.create(business=self.business, png_data=data)
        pdf = render_invoice_pdf(invoice, actor=self.user)
        self.assertEqual(len(PdfReader(BytesIO(pdf)).pages[0].images), 1)
        self.assertIn(
            'src="data:image/png;base64,', render_invoice_pdf_html(invoice, actor=self.user)
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "DRAFT")
        self.assertFalse(invoice.payments.exists())
