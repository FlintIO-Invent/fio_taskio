"""Optional live-browser verification of access administration and work-site selection."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.logistics import test_location_access, test_parcels
from apps.logistics.models import LogisticsLocationAssignment


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class LocationAccessBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = test_location_access.LocationAccessTests.setUp
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    parcel = test_location_access.LocationAccessTests.parcel
    shipment = test_location_access.LocationAccessTests.shipment
    grant = test_location_access.LocationAccessTests.grant

    def test_owner_assignment_and_staff_selection_at_mobile_and_desktop_sizes(self):
        self.c.name = "Caribbean regional distribution and transportation facility " * 2
        self.c.save()
        owner_cookie = self.client.cookies["sessionid"].value
        from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

        worker_client = Client()
        worker_client.force_login(self.staff)
        session = worker_client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        worker_cookie = worker_client.cookies["sessionid"].value

        def db(action):
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(action).result(timeout=20)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            context = browser.new_context(viewport={"width": 390, "height": 844})
            context.add_cookies(
                [{"name": "sessionid", "value": owner_cookie, "url": self.live_server_url}]
            )
            page = context.new_page()
            page.route("https://**/*", lambda route: route.abort())
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            evidence = Path("/tmp/logistics-location-access-ux")
            evidence.mkdir(exist_ok=True)

            def select(name, text):
                choices = page.locator(f'.choices:has(select[name="{name}"])').first
                choices.locator(".choices__inner").click()
                choices.locator("input.choices__input--cloned").fill(text)
                choices.locator("[data-choice-selectable]").filter(has_text=text).first.click()

            page.goto(self.live_server_url + reverse("logistics_location_access"))
            select("assignment-membership", "worker@example.com")
            select("assignment-location", "SITE-C")
            page.locator("#id_assignment-can_operate").check()
            page.get_by_role("button", name="Save assignment").click()
            page.wait_for_url("**/locations/access/")
            self.assertTrue(
                db(
                    lambda: LogisticsLocationAssignment.objects.filter(
                        membership=self.member, location=self.c, can_operate=True
                    ).exists()
                )
            )
            for width in (320, 390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(self.live_server_url + reverse("logistics_location_access"))
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"access-{width}.png"), full_page=True)
            context.clear_cookies()
            context.add_cookies(
                [{"name": "sessionid", "value": worker_cookie, "url": self.live_server_url}]
            )
            for width in (320, 390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(self.live_server_url + reverse("logistics_parcel_scan"))
                page.locator("#logistics-work-location").select_option(str(self.c.pk))
                page.get_by_role("button", name="Use location").click()
                page.wait_for_url("**/parcels/scan/")
                self.assertEqual(
                    db(
                        lambda: LogisticsLocationAssignment.objects.get(
                            membership=self.member, is_current=True
                        ).location_id
                    ),
                    self.c.pk,
                )
                self.assertTrue(page.locator("#logistics-work-location").is_visible())
                self.assertLess(
                    page.locator(".logistics-work-location").bounding_box()["height"], 300
                )
                self.assertLess(
                    page.evaluate(
                        "document.querySelector('.logistics-work-location + .content').getBoundingClientRect().top - document.querySelector('.logistics-work-location').getBoundingClientRect().bottom"
                    ),
                    80,
                )
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"worker-scan-{width}.png"), full_page=True)
            self.assertEqual(errors, [])
            browser.close()
