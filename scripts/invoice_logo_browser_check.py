"""Optional real-browser invoice branding checks; use a disposable PostgreSQL database."""

import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pypdfium2
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import Client as DjangoClient
from django.test import override_settings
from django.urls import reverse
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

from apps.billings.models import Invoice, InvoiceLine
from apps.billings.pdf import render_invoice_pdf, render_invoice_pdf_html
from apps.billings.services import create_invoice_for_client, recalculate_invoice_totals
from apps.businesses import test_configuration_update
from apps.businesses.models import BusinessInvoiceLogo, BusinessUser
from apps.businesses.test_invoice_logos import logo_upload
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import Client


def sample_logo():
    image = Image.new("RGBA", (900, 240), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 240, 240), radius=40, fill="#2563eb")
    font = ImageFont.load_default(size=64)
    draw.text((35, 75), "MM", font=font, fill="white")
    draw.text((275, 75), "COMPANY", font=font, fill="#2563eb")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def capture_pdf(pdf, path):
    path.write_bytes(pdf)
    document = pypdfium2.PdfDocument(pdf)
    for index in range(min(2, len(document))):
        page = document[index]
        bitmap = page.render(scale=1.5)
        bitmap.to_pil().save(str(path.with_suffix(f".page-{index + 1}.png")))
        bitmap.close()
        page.close()
    document.close()


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class InvoiceLogoBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    site = test_configuration_update.InvitationLocationTests.site
    switch = test_configuration_update.InvitationLocationTests.switch

    def setUp(self):
        test_configuration_update.InvitationLocationTests.setUp(self)
        BusinessUser.objects.create(business=self.services, user=self.owner, role="owner")
        self.cookies, self.invoices = {}, {}
        for business in (self.business, self.services):
            client = DjangoClient()
            client.force_login(self.owner)
            session = client.session
            session[CURRENT_BUSINESS_SESSION_KEY] = business.pk
            session.save()
            self.cookies[business.pk] = client.cookies["sessionid"].value
            customer = Client.objects.create(
                business=business, first_name="Logo", last_name="Customer"
            )
            invoice = create_invoice_for_client(actor=self.owner, client=customer)
            InvoiceLine.objects.create(invoice=invoice, description="Consultation", unit_price=100)
            recalculate_invoice_totals(invoice, actor=self.owner)
            self.invoices[business.pk] = invoice

    def db(self, action):
        def run():
            try:
                return action()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=30)

    def test_upload_preview_replace_remove_pdf_and_responsive_settings(self):
        evidence = Path("/tmp/invoice-logo-browser")
        evidence.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            for business in (self.business, self.services):
                # New login sessions avoid retaining a server-side active-workspace change.
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                context.add_cookies(
                    [
                        {
                            "name": "sessionid",
                            "value": self.cookies[business.pk],
                            "url": self.live_server_url,
                        }
                    ]
                )
                page = context.new_page()
                page.route("https://**/*", lambda route: route.abort())
                errors = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                page.goto(self.live_server_url + reverse("business_settings") + "#invoice-defaults")
                page.wait_for_load_state("networkidle")
                modal = page.locator("#onboardingWelcomeModal.show")
                if modal.count():
                    modal.get_by_role("button", name="Close", exact=True).click()
                form = page.locator("#business-settings-form")
                upload = form.get_by_label("Company logo", exact=True)
                upload.set_input_files(
                    {"name": "company.png", "mimeType": "image/png", "buffer": sample_logo()}
                )
                form.get_by_role("button", name="Save business settings", exact=True).click()
                page.wait_for_load_state("networkidle")
                preview = page.get_by_role("img", name="Current company invoice logo", exact=True)
                expect(preview).to_be_visible()
                original = preview.get_attribute("src")
                panel = page.locator("#invoice-defaults")
                for width in (1440, 390):
                    page.set_viewport_size({"width": width, "height": 1000})
                    for theme in ("light", "dark"):
                        page.evaluate(
                            "theme => document.documentElement.setAttribute('data-bs-theme', theme)",
                            theme,
                        )
                        upload.focus()
                        expect(upload).to_be_focused()
                        self.assertLessEqual(
                            page.evaluate("document.documentElement.scrollWidth"), width + 1
                        )
                        panel.screenshot(
                            path=str(evidence / f"{business.vertical}-settings-{theme}-{width}.png")
                        )
                invoice = self.invoices[business.pk]
                pdf = self.db(lambda invoice=invoice: render_invoice_pdf(invoice, actor=self.owner))
                self.assertEqual(len(PdfReader(BytesIO(pdf)).pages[0].images), 1)
                capture_pdf(pdf, evidence / f"{business.vertical}-invoice.pdf")

                def long_invoice_pdf(invoice=invoice):
                    invoice = Invoice.objects.select_related("business", "client").get(
                        pk=invoice.pk
                    )
                    invoice.business.name = (
                        "Caribbean Equipment, Property Maintenance and Marine Services Incorporated"
                    )
                    invoice.business.address_line_1 = "Harbor Commercial Centre, Building C, Equipment and Marine Services Department"
                    invoice.business.address_line_2 = (
                        "Customer Accounts, Upper Floor, Main Reception and Service Entrance"
                    )
                    invoice.business.email = "company-accounts-and-administration@example.test"
                    for index in range(60):
                        InvoiceLine.objects.create(
                            invoice=invoice,
                            description=f"Additional service item {index}",
                            unit_price=0,
                        )
                    return render_invoice_pdf(invoice, actor=self.owner)

                long_pdf = self.db(long_invoice_pdf)
                self.assertGreater(len(PdfReader(BytesIO(long_pdf)).pages), 1)
                capture_pdf(long_pdf, evidence / f"{business.vertical}-long-invoice.pdf")
                html = self.db(
                    lambda invoice=invoice: render_invoice_pdf_html(invoice, actor=self.owner)
                )
                html_page = context.new_page()
                html_page.set_content(html)
                html_page.screenshot(
                    path=str(evidence / f"{business.vertical}-invoice-html.png"), full_page=True
                )
                html_page.close()
                upload.set_input_files(
                    {"name": "bad.png", "mimeType": "image/png", "buffer": b"invalid image"}
                )
                form.get_by_role("button", name="Save business settings", exact=True).click()
                expect(page.locator("#id_invoice_logo_error")).to_contain_text(
                    "Upload a valid PNG or JPG image."
                )
                expect(preview).to_have_attribute("src", original)
                page.locator("#invoice-defaults").screenshot(
                    path=str(evidence / f"{business.vertical}-invalid-mobile.png")
                )
                replacement = logo_upload(size=(100, 500)).read()
                upload.set_input_files(
                    {"name": "portrait.png", "mimeType": "image/png", "buffer": replacement}
                )
                form.get_by_role("button", name="Save business settings", exact=True).click()
                expect(preview).to_be_visible()
                self.assertNotEqual(preview.get_attribute("src"), original)
                form.get_by_label("Remove saved logo", exact=True).check()
                form.get_by_role("button", name="Save business settings", exact=True).click()
                expect(preview).to_have_count(0)
                self.assertFalse(
                    self.db(
                        lambda business=business: BusinessInvoiceLogo.objects.filter(
                            business=business
                        ).exists()
                    )
                )
                self.assertEqual(errors, [])
                context.close()
            browser.close()
