"""Optional Chromium verification of automatic cancellation refunds."""

import os
from decimal import Decimal
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.billings.models import InvoicePayment
from apps.logistics import test_cancellation_settlement as fixtures
from apps.logistics.parcel_services import change_parcel_status


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class CancellationRefundBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = fixtures.CancellationSettlementTests.setUp
    parcel = fixtures.CancellationSettlementTests.parcel
    charge = fixtures.CancellationSettlementTests.charge
    bill = fixtures.CancellationSettlementTests.bill
    issue = fixtures.CancellationSettlementTests.issue
    receipt = fixtures.CancellationSettlementTests.receipt
    prepare = fixtures.CancellationSettlementTests.prepare

    def test_automatic_refund_and_optional_service_charge_on_mobile_and_desktop(self):
        self.business.tax_rate = Decimal("10")
        self.business.save(update_fields=["tax_rate"])
        cases = [(width, *self.prepare(collected=110)) for width in (390, 1440)]
        self.business.tax_rate = Decimal("0")
        self.business.country = "US"
        self.business.save(update_fields=["tax_rate", "country"])
        unpaid = self.parcel()
        charge = self.charge(parcel=unpaid, unit_price=105)
        invoice = self.bill(charge)
        self.issue(invoice)
        change_parcel_status(
            business=self.business, actor=self.user, parcel=unpaid, status="CANCELLED"
        )
        cases.append((390, unpaid, charge, invoice, None))
        evidence = Path("/tmp/mm-cancellation-browser")
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
            for width, parcel, _charge, _invoice, _receipt in cases:
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(self.live_server_url + reverse("business_settings"))
                fee = page.get_by_label("Cancellation service charge per parcel", exact=False)
                fee.fill("15" if width == 1440 else "0")
                page.screenshot(path=str(evidence / f"business-fee-{width}.png"), full_page=True)
                page.get_by_role("button", name="Save business settings", exact=True).click()
                page.get_by_text("Business settings updated.", exact=True).wait_for()
                url = self.live_server_url + reverse(
                    "logistics_parcel_cancellation_settlement", args=[parcel.pk]
                )
                page.goto(url)
                self.assertEqual(page.locator('input[name^="retained_"]').count(), 0)
                expected = "105.00" if _receipt is None else "100.00" if width == 390 else "85.00"
                page.get_by_label("Cancellation reason / reference", exact=False).fill("BROWSER")
                page.get_by_role("button", name="Preview settlement", exact=True).click()
                preview = page.get_by_role("region", name="Cancellation settlement preview")
                preview.wait_for()
                if _receipt is None:
                    self.assertTrue(
                        preview.get_by_text("Refund due: 0.00", exact=False).is_visible()
                    )
                    for screen_width in (390, 1440):
                        page.set_viewport_size({"width": screen_width, "height": 900})
                        self.assertTrue(
                            preview.get_by_text(
                                "No customer payment recorded", exact=False
                            ).is_visible()
                        )
                        self.assertTrue(
                            page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
                        )
                        page.screenshot(
                            path=str(evidence / f"missing-payment-{screen_width}.png"),
                            full_page=True,
                        )
                    preview.get_by_role("link", name="Record customer payment", exact=True).click()
                    self.assertEqual(
                        page.get_by_label("Amount", exact=True).input_value(), "105.00"
                    )
                    page.get_by_label("Reference", exact=True).fill("ORIGINAL-PAYMENT-105")
                    page.get_by_role("button", name="Record customer payment", exact=True).click()
                    page.get_by_role("region", name="Customer payments").wait_for()
                    page.goto(url)
                    page.get_by_label("Cancellation reason / reference", exact=False).fill(
                        "BROWSER"
                    )
                    page.get_by_role("button", name="Preview settlement", exact=True).click()
                    preview.wait_for()
                    self.assertEqual(
                        preview.get_by_text("No customer payment recorded", exact=False).count(), 0
                    )
                self.assertTrue(
                    preview.get_by_text(
                        "Tax retained: 0.00" if _receipt is None else "Tax retained: 10.00",
                        exact=False,
                    ).is_visible()
                )
                self.assertTrue(
                    preview.get_by_text(f"Refund due: {expected}", exact=False).is_visible()
                )
                self.assertTrue(
                    page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
                )
                page.screenshot(path=str(evidence / f"preview-{width}.png"), full_page=True)
                page.get_by_role(
                    "button", name="Confirm cancellation settlement", exact=True
                ).click()
                page.get_by_text("Settlement confirmed by", exact=False).wait_for()
                page.get_by_role("link", name="Record completed refund", exact=True).click()
                self.assertEqual(page.get_by_label("Amount", exact=True).input_value(), expected)
                page.get_by_label("Reference", exact=True).fill(
                    f"RETURN-BROWSER-{width}-{expected}"
                )
                page.get_by_label("Reason reference", exact=True).fill("BROWSER")
                page.screenshot(path=str(evidence / f"refund-form-{width}.png"), full_page=True)
                page.get_by_role("button", name="Adjust customer receipt", exact=True).click()
                page.get_by_role("region", name="Customer payments").wait_for()
                page.goto(url)
                page.get_by_text("Settlement confirmed by", exact=False).wait_for()
                self.assertEqual(
                    page.get_by_role("link", name="Record completed refund").count(), 0
                )
            self.assertEqual(errors, [])
            browser.close()
        self.assertEqual(
            list(
                InvoicePayment.objects.filter(kind="REFUND")
                .order_by("amount")
                .values_list("amount", flat=True)
            ),
            [Decimal("85.00"), Decimal("100.00"), Decimal("105.00")],
        )
