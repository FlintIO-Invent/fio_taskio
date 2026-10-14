"""Real Chromium credit review/resume and camera adapter checks; no camera hardware."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.businesses.models import UserOnboardingState
from apps.logistics import test_credit_scanning as fixtures
from apps.logistics.models import LogisticsCreditApproval, ParcelEvent


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class CreditScannerBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp_base = fixtures.CreditLocationScannerTests.setUp_base
    setUp = fixtures.CreditLocationScannerTests.setUp
    switch = fixtures.CreditLocationScannerTests.switch
    select = fixtures.CreditLocationScannerTests.select
    parcel = fixtures.CreditLocationScannerTests.parcel
    charge = fixtures.CreditLocationScannerTests.charge
    bill = fixtures.CreditLocationScannerTests.bill
    issue = fixtures.CreditLocationScannerTests.issue

    def test_mobile_credit_review_manual_camera_adapter_and_explicit_action(self):
        invoice = self.bill(self.charge(parcel=self.item))
        self.issue(invoice)
        from apps.logistics.parcel_services import change_parcel_status

        change_parcel_status(
            business=self.business, actor=self.user, parcel=self.item, status="RECEIVED"
        )
        UserOnboardingState.objects.get_or_create(
            business=self.business, user=self.user, defaults={"completed_welcome": True}
        )
        evidence = Path("/tmp/mm-credit-scanner-browser")
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
            context = browser.new_context(
                viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
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
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            scan_url = self.live_server_url + reverse("logistics_parcel_scan")
            page.goto(scan_url)
            field = page.get_by_label("Parcel tracking code", exact=True)
            field.fill(self.item.tracking_code)
            field.press("Enter")
            page.locator("[data-scan-parcel]").wait_for()
            self.assertEqual(page.locator('button[value="IN_TRANSIT"]').count(), 0)
            count = db(lambda: ParcelEvent.objects.filter(parcel=self.item).count())
            page.get_by_role("link", name="Continue Registration", exact=True).click()
            page.get_by_role("link", name="Review scoped credit", exact=True).click()
            page.locator("#id_reason_reference").fill("BROWSER-SCOPED-CREDIT")
            page.locator("#id_confirm_obligations").check()
            page.get_by_role("button", name="Approve scoped credit", exact=True).click()
            page.get_by_role("heading", name="Credit audit", exact=True).wait_for()
            self.assertEqual(db(lambda: LogisticsCreditApproval.objects.count()), 1)
            page.screenshot(path=str(evidence / "credit-review-390.png"), full_page=True)
            page.goto(scan_url)
            self.assertTrue(
                page.evaluate(
                    "code => window.MotionmateParcelScan.submitCode(code)", self.item.tracking_code
                )
            )
            page.locator('button[value="IN_TRANSIT"]').wait_for()
            self.assertEqual(
                db(lambda: ParcelEvent.objects.filter(parcel=self.item).count()), count
            )
            self.assertTrue(
                page.get_by_role("region", name="Parcel workflow summary")
                .get_by_text("Approved credit", exact=True)
                .is_visible()
            )
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 392)
            page.screenshot(path=str(evidence / "approved-scan-390.png"), full_page=True)
            page.get_by_role("button", name="Mark In transit", exact=True).click()
            page.locator("[data-scan-action-success]").wait_for()
            self.assertEqual(
                db(
                    lambda: ParcelEvent.objects.filter(
                        parcel=self.item, status="IN_TRANSIT", credit_approval__isnull=False
                    ).count()
                ),
                1,
            )
            self.assertEqual(errors, [])
            browser.close()
