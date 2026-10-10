"""Optional Playwright checks of location registration and searchable selectors."""

import os
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.logistics.location_services import save_location
from scripts import logistics_mobile_check


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class LogisticsLocationBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = logistics_mobile_check.LogisticsMobileChecks.setUp

    def test_search_select_register_and_responsive_forms(self):
        save_location(
            business=self.business,
            actor=self.user,
            name="Historical closed facility",
            code="CLOSED-HUB",
            location_type="HUB",
            country_code="DM",
            is_active=False,
        )
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
            evidence = Path("/tmp/logistics-location-ux")
            evidence.mkdir(exist_ok=True)

            def select(name, search, text):
                choices = page.locator(f'.choices:has(select[name="{name}"])')
                choices.locator(".choices__inner").click()
                choices.locator("input.choices__input--cloned").fill(search)
                choices.locator("[data-choice-selectable]").filter(has_text=text).first.click()

            page.goto(self.live_server_url + reverse("logistics_location_settings"))
            page.locator("#id_name").fill("Roseau company warehouse")
            page.locator("#id_code").fill("DM-WH")
            page.locator("#id_location_type").select_option("WAREHOUSE")
            select("country_code", "Dominica", "Dominica")
            page.locator("#id_address_line_1").fill("123 Company Street")
            page.get_by_role("button", name="Save location").click()
            page.wait_for_url("**/logistics/locations/")
            self.assertTrue(
                page.get_by_role("cell", name="DM-WH · Roseau company warehouse").is_visible()
            )
            for url in ("logistics_parcel_register", "logistics_shipment_create"):
                page.goto(self.live_server_url + reverse(url))
                select("destination_country_code", "Dominica", "Dominica")
                select("destination_location", "Roseau", "DM-WH")
                select("destination_reference_code", "Roseau", "DMRSU")
                self.assertEqual(page.locator("#id_destination_country_code").input_value(), "DM")
                choices = list(page.locator("#id_origin_location option").all_text_contents())
                self.assertFalse(any("CLOSED-HUB" in text for text in choices))
            for url in (
                "logistics_location_settings",
                "logistics_parcel_register",
                "logistics_shipment_create",
                "logistics_application_create",
                "business_settings",
            ):
                for width in (320, 390, 1440):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.goto(self.live_server_url + reverse(url))
                    page.wait_for_timeout(150)
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"),
                        width + 1,
                        (url, width),
                    )
                    self.assertGreater(page.locator(".choices").count(), 0, url)
                    page.screenshot(path=str(evidence / f"{url}-{width}.png"), full_page=True)
            self.assertEqual(errors, [])
            browser.close()
