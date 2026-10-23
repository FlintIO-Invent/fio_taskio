"""Optional Chromium evidence for Parcel journeys and restricted staff clearance."""

import os
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.accounts.models import TaskIOUser
from apps.businesses.models import BusinessUser, UserOnboardingState
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.logistics import test_workflow_summary as fixtures
from apps.logistics.location_test_support import approve_test_site


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class ParcelWorkflowBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = fixtures.ParcelWorkflowSummaryTests.setUp
    parcel = fixtures.ParcelWorkflowSummaryTests.parcel
    charge = fixtures.ParcelWorkflowSummaryTests.charge
    bill = fixtures.ParcelWorkflowSummaryTests.bill
    issue = fixtures.ParcelWorkflowSummaryTests.issue
    receipt = fixtures.ParcelWorkflowSummaryTests.receipt
    move = fixtures.ParcelWorkflowSummaryTests.move

    def test_detail_list_dashboard_scan_and_staff_privacy_at_mobile_desktop_widths(self):
        parcel = self.parcel()
        self.move(parcel, "RECEIVED")
        invoice = self.bill(self.charge(parcel=parcel))
        self.issue(invoice)
        self.receipt(invoice)
        UserOnboardingState.objects.get_or_create(
            business=self.business, user=self.user, defaults={"completed_welcome": True}
        )
        staff = TaskIOUser.objects.create_user(email="workflow-browser-staff@example.test")
        membership = BusinessUser.objects.create(business=self.business, user=staff, role="staff")
        approve_test_site(business=self.business, membership=membership, parcel=parcel)
        UserOnboardingState.objects.create(
            business=self.business, user=staff, completed_welcome=True
        )
        staff_client = Client()
        staff_client.force_login(staff)
        session = staff_client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        evidence = Path("/tmp/mm-workflow-browser")
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
                    self.live_server_url + reverse("logistics_parcel_detail", args=[parcel.pk])
                )
                panel = page.get_by_role("region", name="Parcel workflow summary")
                self.assertTrue(panel.get_by_text("Paid", exact=True).is_visible())
                panel.locator("summary").filter(has_text="Recorded journey history").click()
                self.assertTrue(panel.get_by_text("Charge recorded", exact=False).is_visible())
                self.assertEqual(
                    page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), True
                )
                page.screenshot(path=str(evidence / f"journey-{width}.png"), full_page=True)
                page.goto(self.live_server_url + reverse("logistics_parcel_list"))
                self.assertTrue(
                    page.get_by_text("Paid", exact=True).filter(visible=True).first.is_visible()
                )
                page.goto(self.live_server_url + reverse("agent_dashboard"))
                self.assertTrue(
                    page.get_by_text("Paid", exact=True).filter(visible=True).first.is_visible()
                )
                page.goto(self.live_server_url + reverse("logistics_parcel_scan"))
                page.locator("input[name=tracking_code]").fill(parcel.tracking_code)
                page.locator("input[name=tracking_code]").press("Enter")
                panel = page.get_by_role("region", name="Parcel workflow summary")
                panel.wait_for()
                self.assertTrue(panel.get_by_text("Paid", exact=True).is_visible())
                self.assertTrue(
                    page.get_by_role("button", name="Mark In transit", exact=True).is_visible()
                )
                page.screenshot(path=str(evidence / f"scan-{width}.png"), full_page=True)
            context.add_cookies(
                [
                    {
                        "name": "sessionid",
                        "value": staff_client.cookies["sessionid"].value,
                        "url": self.live_server_url,
                    }
                ]
            )
            page.goto(self.live_server_url + reverse("logistics_parcel_detail", args=[parcel.pk]))
            panel = page.get_by_role("region", name="Parcel workflow summary")
            self.assertTrue(
                panel.get_by_text("Accounting clearance confirmed.", exact=True).is_visible()
            )
            self.assertNotIn(invoice.invoice_number, page.content())
            self.assertNotIn("SECRET-BANK", page.content())
            page.screenshot(path=str(evidence / "staff-clearance.png"), full_page=True)
            self.assertEqual(errors, [])
            browser.close()
