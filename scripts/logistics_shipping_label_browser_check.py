"""Optional registration/prefill UX and actual Chromium 4 x 6 print verification."""

import os
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import zxingcpp
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from apps.logistics import test_location_operations, test_parcels
from apps.logistics.models import Parcel, ParcelEvent


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class ShippingLabelBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    select = test_location_operations.LocationOperationsTests.select
    parcel = test_location_operations.LocationOperationsTests.parcel
    setUp = test_location_operations.LocationOperationsTests.setUp

    def test_prefill_registration_preview_and_print_decoding(self):
        self.customer.street_address = "10 Fictional Customer Street"
        self.customer.save()
        client_updated_at = self.customer.updated_at
        evidence = Path("/tmp/mm-shipping-label-ux")
        evidence.mkdir(exist_ok=True)

        def db(action):
            def execute():
                try:
                    return action()
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(execute).result(timeout=20)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            context = browser.new_context(viewport={"width": 390, "height": 844})
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
            page.goto(
                self.live_server_url
                + reverse("logistics_parcel_register")
                + f"?client={self.customer.pk}"
            )
            page.locator("#parcel-recipient-tab").click()
            page.locator("#id_recipient_name").fill("Operator's chosen recipient")
            page.locator('[data-shipping-prefill="recipient"]').click()
            page.wait_for_function(
                "document.querySelector('#id_recipient_address_line_1').value === '10 Fictional Customer Street'"
            )
            self.assertEqual(
                page.locator("#id_recipient_name").input_value(), "Operator's chosen recipient"
            )
            self.assertEqual(page.locator("#id_recipient_country_code").input_value(), "SX")
            page.locator("#parcel-sender-tab").click()
            page.locator('[data-shipping-prefill="sender"]').click()
            page.wait_for_function(
                "document.querySelector('#id_sender_address_line_1').value === '10 Fictional Customer Street'"
            )
            page.locator("#id_package_description").fill("Fictional shipping-label browser parcel")
            page.locator("#id_origin").fill("Miami")
            page.locator("#id_destination").fill("Sint Maarten")
            page.locator("#id_origin_location").select_option(str(self.a.pk), force=True)
            page.locator("#id_destination_location").select_option(str(self.b.pk), force=True)
            page.get_by_role("button", name="Register Parcel", exact=True).click()
            page.wait_for_url("**/logistics/parcels/*/")
            item = db(
                lambda: Parcel.objects.get(
                    package_description="Fictional shipping-label browser parcel"
                )
            )
            self.assertEqual(item.recipient_name, "Operator's chosen recipient")
            self.assertEqual(
                db(lambda: type(self.customer).objects.get(pk=self.customer.pk).updated_at),
                client_updated_at,
            )
            self.assertTrue(page.get_by_role("link", name="Download PDF", exact=True).is_visible())
            self.assertIn("shipping label below", page.locator("body").inner_text())
            page.get_by_role("link", name="Preview Shipping Label").click()
            page.locator(".shipping-label svg").wait_for()
            page.evaluate("document.fonts.ready")
            events_before = db(lambda: ParcelEvent.objects.count())
            for width in (320, 390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"label-{width}.png"), full_page=True)
            printed = page.pdf(prefer_css_page_size=True, print_background=True)
            reader = PdfReader(BytesIO(printed))
            self.assertEqual(len(reader.pages), 1)
            self.assertEqual(tuple(reader.pages[0].mediabox), (0, 0, 288, 432))
            text = reader.pages[0].extract_text()
            self.assertNotIn("Back to Parcel", text)
            self.assertNotIn("Print Shipping Label", text)
            self.assertIn("Operator's chosen recipient", text)
            with pdfium.PdfDocument(printed) as document:
                pdf_page = document[0]
                bitmap = pdf_page.render(scale=300 / 72)
                try:
                    symbols = zxingcpp.read_barcodes(bitmap.to_pil())
                finally:
                    bitmap.close()
                    pdf_page.close()
            self.assertEqual({str(symbol.format) for symbol in symbols}, {"QR Code", "Code 128"})
            self.assertTrue(all(symbol.text == item.tracking_code for symbol in symbols))
            page.add_init_script("window.print = () => { window.labelPrintRequested = true; };")
            page.goto(
                self.live_server_url
                + reverse("logistics_shipping_label", args=[item.pk])
                + "?print=1"
            )
            page.wait_for_function("window.labelPrintRequested === true")
            self.assertEqual(db(lambda: ParcelEvent.objects.count()), events_before)
            self.assertEqual(errors, [])
            context.close()
            browser.close()
