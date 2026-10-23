"""Optional Chromium check of saved shared freight and cancelled-charge reissue."""

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.billings.models import Invoice
from apps.logistics import test_financial_coverage as fixtures


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class FinancialCoverageBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = fixtures.FinancialCoverageTests.setUp
    parcel = fixtures.FinancialCoverageTests.parcel
    shipment = fixtures.FinancialCoverageTests.shipment
    charge = fixtures.FinancialCoverageTests.charge
    bill = fixtures.FinancialCoverageTests.bill
    cargo = fixtures.FinancialCoverageTests.cargo
    change = fixtures.FinancialCoverageTests.change

    def test_shared_freight_and_reissue_keep_saved_currency_and_tax(self):
        self.business.tax_rate = Decimal("10")
        self.business.save()
        shipment, a, b = self.shipment(), self.parcel(), self.parcel()
        self.cargo(shipment, a, b)
        freight = self.charge(shipment=shipment, description="Freight", unit_price=150)
        handling = self.charge(parcel=a)
        original = self.bill(freight, handling)
        self.change(original, "SENT")
        self.business.currency, self.business.tax_rate = "EUR", Decimal("20")
        self.business.save()
        evidence = Path("/tmp/mm-coverage-browser")
        evidence.mkdir(exist_ok=True)

        def db(action):
            def worker():
                try:
                    return action()
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(worker).result(timeout=20)

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
            page.on("dialog", lambda dialog: dialog.accept())
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                for kind, target in (("parcel", a), ("shipment", shipment)):
                    response = page.goto(
                        self.live_server_url + reverse(f"logistics_{kind}_detail", args=[target.pk])
                    )
                    self.assertEqual(response.status, 200)
                    panel = page.locator("section.card").filter(
                        has=page.get_by_role("heading", name="Billing", exact=True)
                    )
                    self.assertEqual(panel.get_by_text("Shipment coverage", exact=True).count(), 1)
                    self.assertTrue(
                        panel.get_by_text(
                            "Applicable charges counted once (before tax): USD 175.00", exact=True
                        ).is_visible()
                    )
                    self.assertNotIn("€", panel.inner_text())
                    page.screenshot(
                        path=str(evidence / f"{kind}-shared-{width}.png"), full_page=True
                    )
            page.goto(self.live_server_url + reverse("invoice_detail", args=[original.pk]))
            self.assertTrue(page.get_by_text("$192.50", exact=True).first.is_visible())
            page.get_by_role("button", name="Cancel Invoice", exact=True).click()
            page.wait_for_load_state("networkidle")
            self.assertEqual(db(lambda: Invoice.objects.get(pk=original.pk).status), "CANCELLED")
            url = self.live_server_url + reverse("logistics_shipment_invoice", args=[shipment.pk])
            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(url)
                self.assertTrue(page.get_by_label("Freight — $150.00", exact=True).is_checked())
                page.screenshot(path=str(evidence / f"reissue-form-{width}.png"), full_page=True)
            page.get_by_role("button", name="Create invoice / Add to existing invoice").click()
            page.wait_for_load_state("networkidle")
            reissue = db(
                lambda: freight.invoice_lines.select_related("invoice__business")
                .order_by("-pk")
                .first()
                .invoice
            )
            self.assertNotEqual(reissue.pk, original.pk)
            self.assertEqual(
                (reissue.currency_code, reissue.tax_rate_percentage, reissue.total),
                ("USD", Decimal("10"), Decimal("165")),
            )
            page.get_by_role("button", name="Mark as Sent", exact=True).click()
            page.wait_for_load_state("networkidle")
            self.assertEqual(db(lambda: Invoice.objects.get(pk=reissue.pk).status), "SENT")
            self.assertTrue(page.get_by_text("$165.00", exact=True).first.is_visible())
            self.assertEqual(page.get_by_role("link", name="Edit Invoice", exact=True).count(), 0)
            page.screenshot(path=str(evidence / "reissue-sent.png"), full_page=True)
            self.assertEqual(errors, [])
            browser.close()
