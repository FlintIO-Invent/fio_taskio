"""Optional Chromium check of shared payment entry, settlement and refund UI."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.billings import test_payments as fixtures
from apps.billings.models import Invoice


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class CustomerPaymentBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = fixtures.CustomerPaymentTests.setUp
    make_invoice = fixtures.CustomerPaymentTests.make_invoice

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
                page.goto(
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
                    page.screenshot(path=str(evidence / "partial-balance.png"), full_page=True)
                    panel.get_by_role("link", name="Record customer payment", exact=True).click()
                else:
                    self.assertTrue(panel.get_by_text("Settled", exact=True).is_visible())
                    self.assertEqual(
                        panel.get_by_role("link", name="Record customer payment").count(), 0
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
            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                page.screenshot(path=str(evidence / f"refund-balance-{width}.png"), full_page=True)
            self.assertEqual(errors, [])
            browser.close()
