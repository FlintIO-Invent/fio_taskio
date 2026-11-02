"""Real Chromium and PDF evidence, using disposable local test databases only."""

import os
from pathlib import Path

import pypdfium2
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.billings import test_payments as service_fixtures
from apps.billings.pdf import render_invoice_pdf_html
from apps.logistics import test_cancellation_settlement as logistics_fixtures
from apps.logistics.parcel_services import change_parcel_status
from scripts.logistics_parcel_wizard_browser_check import database_read

EVIDENCE = Path("/tmp/invoice-terminology-browser")


def pdf_preview(path):
    document = pypdfium2.PdfDocument(str(path))
    page = document[0]
    bitmap = page.render(scale=1.5)
    bitmap.to_pil().save(str(path.with_suffix(".png")))
    bitmap.close()
    page.close()
    document.close()


class BrowserEvidence:
    def page(self, playwright):
        browser = playwright.chromium.launch(
            headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
        )
        context = browser.new_context()
        context.add_cookies(
            [
                {
                    "name": "sessionid",
                    "value": self.client.cookies["sessionid"].value,
                    "url": self.live_server_url,
                }
            ]
        )
        page = context.new_page()
        page.route("https://**/*", lambda route: route.abort())
        page.on("dialog", lambda dialog: dialog.accept())
        return browser, page

    def capture(self, page, name):
        EVIDENCE.mkdir(exist_ok=True)
        page.wait_for_load_state("networkidle")
        welcome = page.locator("#onboardingWelcomeModal.show")
        if welcome.count():
            welcome.get_by_role("button", name="Close", exact=True).click()
            page.wait_for_load_state("networkidle")
        self.assertLessEqual(
            page.evaluate("document.documentElement.scrollWidth"), page.viewport_size["width"] + 1
        )
        page.screenshot(path=str(EVIDENCE / name), full_page=True)


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class ServicesTerminologyBrowserChecks(BrowserEvidence, StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = service_fixtures.CustomerPaymentTests.setUp
    make_invoice = service_fixtures.CustomerPaymentTests.make_invoice
    receipt = service_fixtures.CustomerPaymentTests.receipt

    def test_services_screens_payment_email_and_pdf(self):
        self.customer.email = "customer-browser@example.test"
        self.customer.save(update_fields=["email"])
        self.user.is_staff = self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])
        self.receipt(40)
        legacy = self.make_invoice(status="PAID")
        self.business.currency = "EUR"
        self.business.save(update_fields=["currency"])
        with sync_playwright() as playwright:
            browser, page = self.page(playwright)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                for name, route in (
                    ("service-partial", reverse("invoice_detail", args=[self.invoice.pk])),
                    ("service-outstanding", reverse("invoice_list") + "?status=OUTSTANDING"),
                    ("service-client", reverse("staff_client_detail", args=[self.customer.pk])),
                    ("service-dashboard", reverse("agent_dashboard")),
                    ("invoice-admin", reverse("admin:billings_invoice_changelist")),
                ):
                    page.goto(self.live_server_url + route)
                    self.capture(page, f"{name}-{width}.png")
                page.goto(self.live_server_url + reverse("invoice_detail", args=[self.invoice.pk]))
                panel = page.get_by_role("region", name="Customer payments")
                expect(panel).to_contain_text("Partially paid")
                expect(panel).to_contain_text("USD 60.00")
                self.assertEqual(page.get_by_role("button", name="Mark as Paid").count(), 0)
                page.goto(self.live_server_url + reverse("invoice_list") + "?status=OUTSTANDING")
                review = page.get_by_role("region", name="Invoices requiring accounting review")
                expect(review).to_contain_text(legacy.invoice_number)
                expect(review).to_contain_text("before requesting payment")
            page.goto(
                self.live_server_url + reverse("invoice_payment_record", args=[self.invoice.pk])
            )
            expect(page.get_by_label("Currency", exact=True)).to_have_value("USD")
            page.get_by_label("Amount", exact=True).fill("60")
            page.get_by_label("Method", exact=True).select_option("CASH")
            page.get_by_label("Reference", exact=True).fill("BROWSER-REMAINDER")
            page.get_by_role("button", name="Record customer payment", exact=True).click()
            page.wait_for_load_state("networkidle")
            expect(page.get_by_role("region", name="Customer payments")).to_contain_text("Paid")
            page.get_by_role("button", name="Email Invoice", exact=True).click()
            page.wait_for_load_state("networkidle")
            expect(page.locator("body")).to_contain_text("Delivery to the recipient is unconfirmed")
            expect(page.locator("body")).to_contain_text("customer-browser@example.test")
            self.capture(page, "service-paid-email-1440.png")
            with page.expect_download() as download:
                page.get_by_role("link", name="Download PDF", exact=True).first.click()
            pdf_path = EVIDENCE / "service-paid.pdf"
            download.value.save_as(str(pdf_path))
            pdf_preview(pdf_path)
            html = database_read(
                lambda: render_invoice_pdf_html(
                    type(self.invoice)
                    .objects.select_related("business", "client")
                    .get(pk=self.invoice.pk)
                )
            )
            (EVIDENCE / "service-paid-html-pdf.html").write_text(html)
            page.set_content(html)
            page.screenshot(path=str(EVIDENCE / "service-paid-html-pdf.png"), full_page=True)
            self.assertEqual(errors, [])
            browser.close()


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class LogisticsTerminologyBrowserChecks(BrowserEvidence, StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = logistics_fixtures.CancellationSettlementTests.setUp
    parcel = logistics_fixtures.CancellationSettlementTests.parcel
    shipment = logistics_fixtures.CancellationSettlementTests.shipment
    charge = logistics_fixtures.CancellationSettlementTests.charge
    bill = logistics_fixtures.CancellationSettlementTests.bill
    issue = logistics_fixtures.CancellationSettlementTests.issue
    receipt = logistics_fixtures.CancellationSettlementTests.receipt
    settle = logistics_fixtures.CancellationSettlementTests.settle

    def test_logistics_shared_debt_refund_and_partial_registration(self):
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
        partial_parcel = self.parcel()
        partial = self.bill(self.charge(parcel=partial_parcel, unit_price=100))
        self.issue(partial)
        self.receipt(partial, 40)
        with sync_playwright() as playwright:
            browser, page = self.page(playwright)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                for name, route in (
                    ("logistics-shared-refund-debt", reverse("invoice_detail", args=[invoice.pk])),
                    ("logistics-outstanding", reverse("invoice_list") + "?status=OUTSTANDING"),
                    ("logistics-dashboard", reverse("agent_dashboard")),
                    ("logistics-parcel-summary", reverse("logistics_parcel_detail", args=[b.pk])),
                    (
                        "logistics-registration",
                        reverse("logistics_parcel_registration", args=[partial_parcel.pk]),
                    ),
                ):
                    page.goto(self.live_server_url + route)
                    self.capture(page, f"{name}-{width}.png")
                payment = page.locator("#registration-payment")
                expect(payment).to_contain_text("Record payment received")
                expect(payment).to_contain_text("Continue without recording a payment")
                expect(payment).to_contain_text("Partially paid")
            page.locator('[name="decision"][value="record"]').check()
            page.locator("#id_amount").fill("20")
            page.locator("#id_method").select_option("CASH")
            page.locator("#registration-payment button[type=submit]").last.click()
            page.wait_for_load_state("networkidle")
            actual = database_read(lambda: list(partial.payments.values_list("amount", flat=True)))
            self.assertEqual(sum(actual), 60)
            page.goto(self.live_server_url + reverse("invoice_detail", args=[invoice.pk]))
            panel = page.get_by_role("region", name="Customer payments")
            expect(panel).to_contain_text("Unpaid")
            expect(panel).to_contain_text("Refund due")
            expect(panel).to_contain_text("USD 100.00")
            with page.expect_download() as download:
                page.get_by_role("link", name="Download PDF", exact=True).first.click()
            pdf_path = EVIDENCE / "logistics-shared-refund-debt.pdf"
            download.value.save_as(str(pdf_path))
            pdf_preview(pdf_path)
            self.assertEqual(errors, [])
            browser.close()
