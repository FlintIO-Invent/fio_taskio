"""Run only with taskio.services_test_settings against a disposable local database."""

import os
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.businesses.test_service_allowances import ServicesFixture


class ServicesBrowserChecks(ServicesFixture, StaticLiveServerTestCase):
    serialized_rollback = True

    def test_home_and_subscription_on_mobile_and_desktop(self):
        evidence = Path("/tmp/services-rollout-browser")
        evidence.mkdir(exist_ok=True)
        self.login()
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
                for currency, prices in (
                    ("eur", ("€39", "€79", "€149")),
                    ("usd", ("$39", "$79", "$159")),
                ):
                    page.goto(
                        self.live_server_url + reverse("home") + f"?currency={currency}#pricing"
                    )
                    pricing = page.locator("#pricing")
                    self.assertEqual(
                        pricing.get_by_text("Online booking page — Included", exact=True).count(), 3
                    )
                    self.assertNotIn("online bookings / month", pricing.inner_text().lower())
                    self.assertIn("Each appointment counts once", pricing.inner_text())
                    for interval in ("monthly", "yearly"):
                        pricing.locator("#pricing-billing-toggle").set_checked(interval == "yearly")
                        for position, slug in enumerate(("starter", "pro", "business")):
                            link = pricing.locator("[data-pricing-plan-link]").nth(position)
                            self.assertIn(f"plan={slug}", link.get_attribute("href"))
                            self.assertIn(f"interval={interval}", link.get_attribute("href"))
                            self.assertIn(f"currency={currency}", link.get_attribute("href"))
                            expected = (
                                prices[position]
                                if interval == "monthly"
                                else {
                                    "€39": "€390",
                                    "€79": "€790",
                                    "€149": "€1,490",
                                    "$39": "$390",
                                    "$79": "$790",
                                    "$159": "$1,590",
                                }[prices[position]]
                            )
                            self.assertTrue(pricing.get_by_text(expected, exact=True).is_visible())
                        page.screenshot(
                            path=str(evidence / f"home-{currency}-{interval}-{width}.png"),
                            full_page=True,
                        )
                        pricing.screenshot(
                            path=str(evidence / f"pricing-{currency}-{interval}-{width}.png")
                        )
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width + 1
                    )
                page.goto(self.live_server_url + reverse("business_subscription"))
                self.assertIn("Each appointment counts once", page.locator("body").inner_text())
                self.assertNotIn("Online Bookings / Month", page.locator("body").inner_text())
                self.assertNotIn("online bookings this month", page.locator("body").inner_text())
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"subscription-{width}.png"), full_page=True)
            self.assertEqual(errors, [])
            browser.close()
