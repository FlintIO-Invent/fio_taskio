"""Optional real Chromium checks for guided registration and responsive handoffs."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.billings.models import Invoice, InvoicePayment
from apps.businesses.models import UserOnboardingState
from apps.logistics import test_registration as fixtures
from apps.logistics.models import LogisticsCharge, Parcel


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class RegistrationBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = fixtures.ParcelRegistrationTests.setUp
    parcel = fixtures.ParcelRegistrationTests.parcel
    charge = fixtures.ParcelRegistrationTests.charge
    shipment = fixtures.ParcelRegistrationTests.shipment

    def test_existing_inline_clients_billing_payment_resume_and_shipment_at_two_widths(self):
        UserOnboardingState.objects.get_or_create(
            business=self.business, user=self.user, defaults={"completed_welcome": True}
        )
        shared_parcel = self.parcel(origin="A", destination="B")
        shared_charge = self.charge(parcel=shared_parcel)
        shipment = self.shipment(origin="A", destination="B")
        evidence = Path("/tmp/mm-registration-browser")
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
            errors = []
            for width in (390, 1440):
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    is_mobile=width == 390,
                    has_touch=width == 390,
                )
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
                page.on("pageerror", lambda error: errors.append(str(error)))

                def wait_guide(page=page):
                    page.wait_for_url(
                        lambda url: urlsplit(url).path.endswith("/registration/")
                        and not urlsplit(url).query
                    )

                page.goto(
                    self.live_server_url
                    + reverse("logistics_parcel_register")
                    + f"?client={self.customer.pk}"
                )
                page.locator("#id_package_description").fill(f"Guided browser Parcel {width}")
                page.locator("#id_origin").fill("A")
                page.locator("#id_destination").fill("B")
                page.locator("#id_weight_kg").fill("2.5")
                if width == 1440:
                    page.get_by_role("button", name="Add Client", exact=True).click()
                    modal = page.locator("#parcelClientModal")
                    for field, value in {
                        "first_name": "Inline",
                        "last_name": "Browser",
                        "company_name": "Browser Company",
                        "email": "browser-inline@example.test",
                        "phone": "1234567",
                        "street_address": "10 Main Street",
                    }.items():
                        modal.locator(f'[name="new_client-{field}"]').fill(value)
                    page.screenshot(path=str(evidence / "inline-client-1440.png"))
                    modal.get_by_role("button", name="Add and Select Client").click()
                    modal.wait_for(state="hidden")
                    self.assertEqual(
                        page.locator("#id_package_description").input_value(),
                        f"Guided browser Parcel {width}",
                    )
                page.get_by_role("button", name="Register & continue").click()
                wait_guide()
                parcel = db(
                    lambda width=width: Parcel.objects.get(
                        package_description=f"Guided browser Parcel {width}"
                    )
                )
                guide_url = self.live_server_url + reverse(
                    "logistics_parcel_registration", args=[parcel.pk]
                )
                page.get_by_role("link", name="Parcel detail", exact=True).click()
                page.get_by_role("link", name="Continue Registration", exact=True).click()
                page.get_by_role("link", name="Add charge", exact=True).first.click()
                page.locator("input[name=charge_type][value=custom]").check()
                page.locator("#id_description").fill("Freight")
                page.locator("#id_unit_price").fill("100")
                page.get_by_role("button", name="Add charge", exact=True).click()
                wait_guide()
                page.get_by_role(
                    "link", name="Create invoice / Add to existing invoice", exact=True
                ).first.click()
                if width == 390:
                    page.locator(f'input[name=charges][value="{shared_charge.pk}"]').check()
                page.get_by_role(
                    "button", name="Create invoice / Add to existing invoice", exact=True
                ).click()
                wait_guide()
                invoice = db(lambda parcel=parcel: Invoice.objects.get(lines__parcel=parcel))
                self.assertEqual(
                    db(lambda invoice=invoice: invoice.lines.count()), 2 if width == 390 else 1
                )
                page.get_by_role(
                    "button", name=f"Issue Invoice {invoice.invoice_number}", exact=True
                ).click()
                wait_guide()
                page.get_by_role(
                    "link", name=f"Record payment {invoice.invoice_number}", exact=True
                ).click()
                page.locator("#id_amount").fill("20")
                page.locator("#id_reference").fill(f"BROWSER-CASH-{width}")
                page.get_by_role("button", name="Save customer receipt").click()
                wait_guide()
                panel = page.get_by_role("region", name="Parcel workflow summary")
                self.assertTrue(panel.get_by_text("Partially paid", exact=True).is_visible())
                page.get_by_role(
                    "link", name=f"Record payment {invoice.invoice_number}", exact=True
                ).click()
                page.locator("#id_method").select_option("BANK_TRANSFER")
                page.locator("#id_reference").fill(f"BROWSER-BANK-{width}")
                page.get_by_role("button", name="Save customer receipt").click()
                wait_guide()
                if width == 390:
                    page.get_by_role("button", name="Assign later · View summary").click()
                    page.wait_for_url(lambda url: urlsplit(url).query == "summary=1")
                    self.assertTrue(
                        page.get_by_role(
                            "heading", name="Registration summary", exact=True
                        ).is_visible()
                    )
                    page.goto(guide_url)
                    page.get_by_role(
                        "button", name=f"Assign to {shipment.reference}", exact=True
                    ).click()
                else:
                    page.get_by_role("link", name="Create Shipment with this Parcel").click()
                    self.assertEqual(page.locator("#id_parcel").input_value(), str(parcel.pk))
                    page.get_by_role("button", name="Save Shipment").click()
                wait_guide()
                db(lambda parcel=parcel: parcel.refresh_from_db())
                self.assertIsNotNone(parcel.shipment_id)
                counts = db(
                    lambda: (
                        Parcel.objects.count(),
                        LogisticsCharge.objects.count(),
                        Invoice.objects.count(),
                        InvoicePayment.objects.count(),
                    )
                )
                page.reload()
                self.assertEqual(
                    db(
                        lambda: (
                            Parcel.objects.count(),
                            LogisticsCharge.objects.count(),
                            Invoice.objects.count(),
                            InvoicePayment.objects.count(),
                        )
                    ),
                    counts,
                )
                self.assertTrue(
                    page.get_by_role("region", name="Parcel workflow summary")
                    .get_by_text("Paid", exact=True)
                    .is_visible()
                )
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 2
                )
                page.screenshot(path=str(evidence / f"completion-{width}.png"), full_page=True)
                context.close()
            self.assertEqual(errors, [])
            browser.close()
