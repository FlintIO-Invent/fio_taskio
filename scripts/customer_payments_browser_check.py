"""Optional Chromium check of shared payment entry, settlement and refund UI."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.billings import test_payments as fixtures
from apps.billings.models import Invoice


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class CustomerPaymentBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = fixtures.CustomerPaymentTests.setUp
    make_invoice = fixtures.CustomerPaymentTests.make_invoice

    def check_invoice_layout(self, page, evidence, name):
        page.wait_for_load_state("networkidle")
        welcome = page.locator("#onboardingWelcomeModal.show")
        if welcome.count():
            welcome.get_by_role("button", name="Close", exact=True).click()
        panel = page.get_by_role("region", name="Customer payments")
        actions = page.get_by_role("heading", name="Actions", exact=True).locator("../..")
        payment = page.get_by_role("link", name="Record customer payment", exact=True)
        expect(payment).to_have_count(1)
        expect(
            actions.get_by_role("link", name="Record customer payment", exact=True)
        ).to_be_visible()
        expect(panel.get_by_role("link", name="Record customer payment")).to_have_count(0)
        details = page.get_by_role("heading", name="Invoice Details", exact=True).locator("../..")
        for width in (390, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            for theme in ("light", "dark"):
                page.evaluate(
                    "theme => document.documentElement.setAttribute('data-bs-theme', theme)",
                    theme,
                )
                payment.focus()
                expect(payment).to_be_focused()
                page.keyboard.press("Tab")
                download = actions.get_by_role("link", name="Download PDF", exact=True)
                expect(download).to_be_focused()
                page.keyboard.press("Shift+Tab")
                expect(payment).to_be_focused()
                geometry = payment.evaluate("""button => {
                    const payment = button.getBoundingClientRect();
                    const download = button.nextElementSibling.getBoundingClientRect();
                    return {top: payment.top, nextTop: download.top,
                        width: payment.width, nextWidth: download.width};
                }""")
                self.assertLess(geometry["top"], geometry["nextTop"])
                self.assertAlmostEqual(geometry["width"], geometry["nextWidth"], delta=1)
                self.assertGreaterEqual(
                    details.evaluate(
                        "card => card.nextElementSibling.getBoundingClientRect().top "
                        "- card.getBoundingClientRect().bottom"
                    ),
                    0,
                )
                page.evaluate("window.scrollTo({top: 0, left: 0, behavior: 'instant'})")
                page.screenshot(path=str(evidence / f"{name}-{theme}-{width}.png"), full_page=True)
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"),
                    width + 1,
                    page.evaluate(
                        """() => [...document.querySelectorAll('.content *')]
                        .filter(el => el.getBoundingClientRect().right > innerWidth + 1)
                        .slice(0, 12).map(el => [el.tagName, el.className, el.textContent.slice(0, 60)])"""
                    ),
                )

    def test_partial_full_receipts_and_refund_on_mobile_and_desktop(self):
        evidence = Path("/tmp/mm-payment-browser")
        evidence.mkdir(exist_ok=True)
        with sync_playwright() as playwright:
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
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(self.live_server_url + reverse("invoice_detail", args=[self.invoice.pk]))
                if width == 390:
                    self.check_invoice_layout(page, evidence, "invoice-unpaid")
                    page.set_viewport_size({"width": width, "height": 900})
                page.get_by_role("link", name="Record customer payment", exact=True).click()
                expect(page).to_have_url(
                    self.live_server_url + reverse("invoice_payment_record", args=[self.invoice.pk])
                )
                self.assertEqual(page.get_by_label("Currency", exact=True).input_value(), "USD")
                page.screenshot(path=str(evidence / f"receipt-form-{width}.png"), full_page=True)
            for amount, method, reference in (
                ("40", "CASH", "CASH-BROWSER"),
                ("60", "BANK_TRANSFER", "BANK-BROWSER"),
            ):
                page.get_by_label("Amount", exact=True).fill(amount)
                page.get_by_label("Method", exact=True).select_option(method)
                page.get_by_label("Reference", exact=True).fill(reference)
                page.get_by_role("button", name="Record customer payment", exact=True).click()
                page.wait_for_load_state("networkidle")
                panel = page.get_by_role("region", name="Customer payments")
                if amount == "40":
                    self.assertTrue(panel.get_by_text("USD 60.00", exact=True).is_visible())
                    self.check_invoice_layout(page, evidence, "invoice-partial")
                    page.get_by_role("link", name="Record customer payment", exact=True).click()
                else:
                    self.assertTrue(panel.get_by_text("Paid", exact=True).is_visible())
                    self.assertEqual(
                        page.get_by_role("link", name="Record customer payment").count(), 0
                    )
            with ThreadPoolExecutor(max_workers=1) as pool:

                def invoice_status():
                    try:
                        return Invoice.objects.get(pk=self.invoice.pk).status
                    finally:
                        connections.close_all()

                self.assertEqual(pool.submit(invoice_status).result(), "SENT")
            panel.get_by_role("row").filter(has_text="BANK-BROWSER").get_by_role(
                "link", name="Adjust receipt"
            ).click()
            page.get_by_label("Action", exact=True).select_option("REFUND")
            page.get_by_label("Amount", exact=True).fill("10")
            page.get_by_label("Reference", exact=True).fill("REFUND-BROWSER")
            page.get_by_label("Reason reference", exact=True).fill("CASE-BROWSER")
            page.get_by_role("button", name="Adjust customer receipt", exact=True).click()
            page.wait_for_load_state("networkidle")
            panel = page.get_by_role("region", name="Customer payments")
            self.assertTrue(panel.get_by_text("USD 10.00", exact=True).is_visible())
            self.assertTrue(panel.get_by_text("Partially paid", exact=True).is_visible())
            self.assertEqual(panel.get_by_role("row").count(), 4)
            self.check_invoice_layout(page, evidence, "invoice-refund")
            self.assertEqual(errors, [])
            browser.close()
