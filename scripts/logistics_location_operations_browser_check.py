"""Optional browser QA of reviewed rollout, work context and audited scan actions."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.logistics import test_location_operations, test_parcels
from apps.logistics.models import LogisticsProfile, ParcelEvent


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class VerifiedOperationsBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = test_location_operations.LocationOperationsTests.setUp
    setUp_base = test_parcels.ParcelTests.setUp
    switch = test_parcels.ParcelTests.switch
    select = test_location_operations.LocationOperationsTests.select
    parcel = test_location_operations.LocationOperationsTests.parcel

    def test_site_selector_rollout_and_explicit_scanner_action_on_mobile_and_desktop(self):
        owner_cookie = self.client.cookies["sessionid"].value
        worker_client = Client()
        worker_client.force_login(self.staff)
        session = worker_client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        worker_cookie = worker_client.cookies["sessionid"].value

        def db(action):
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(action).result(timeout=20)

        # Exercise explicit enablement through the page, independently of fixture setup.
        db(
            lambda: LogisticsProfile.objects.filter(business=self.business).update(
                location_operations_enabled_at=None
            )
        )
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
            evidence = Path("/tmp/logistics-location-operations-ux")
            evidence.mkdir(exist_ok=True)
            page.goto(self.live_server_url + reverse("logistics_location_access"))
            page.locator('[name="confirm_operations"]').check()
            page.get_by_role("button", name="Enable verified operations").click()
            page.wait_for_url("**/locations/access/")
            self.assertTrue(
                db(
                    lambda: LogisticsProfile.objects.filter(
                        business=self.business, location_operations_enabled_at__isnull=False
                    ).exists()
                )
            )
            for width in (320, 390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(self.live_server_url + reverse("logistics_location_access"))
                self.assertTrue(page.locator("#logistics-work-location").is_visible())
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"rollout-{width}.png"), full_page=True)
            context.clear_cookies()
            context.add_cookies(
                [{"name": "sessionid", "value": worker_cookie, "url": self.live_server_url}]
            )
            for width in (320, 390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(self.live_server_url + reverse("logistics_parcel_scan"))
                page.locator("#logistics-work-location").select_option(str(self.a.pk))
                page.get_by_role("button", name="Use location").click()
                page.wait_for_url("**/parcels/scan/")
                page.locator("[data-scan-input]").fill(self.item.tracking_code)
                page.locator("[data-scan-input]").press("Enter")
                page.locator("[data-scan-parcel]").wait_for()
                self.assertEqual(
                    db(lambda: ParcelEvent.objects.filter(parcel=self.item).count()), 1
                )
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"scan-{width}.png"), full_page=True)
            page.locator('button[name="status"][value="RECEIVED"]').click()
            page.locator("[data-scan-action-success]").wait_for()
            self.assertEqual(
                db(
                    lambda: ParcelEvent.objects.filter(
                        parcel=self.item,
                        status="RECEIVED",
                        actor=self.staff,
                        operational_location=self.a,
                    ).count()
                ),
                1,
            )
            page.goto(
                self.live_server_url + reverse("logistics_parcel_detail", args=[self.item.pk])
            )
            self.assertIn("Authorized work site", page.locator("#parcel-history").inner_text())
            self.assertEqual(errors, [])
            browser.close()
