"""Optional real-browser verification of Logistics Invoice issuance and clearance UI."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.billings.models import Invoice
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.logistics import test_financial_access as fixtures


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class LogisticsFinancialBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = fixtures.LogisticsFinancialAccessTests.setUp
    setUp_base = fixtures.LogisticsFinancialAccessTests.setUp_base
    switch = fixtures.LogisticsFinancialAccessTests.switch
    parcel = fixtures.LogisticsFinancialAccessTests.parcel
    shipment = fixtures.LogisticsFinancialAccessTests.shipment
    grant = fixtures.LogisticsFinancialAccessTests.grant
    login_worker = fixtures.LogisticsFinancialAccessTests.login_worker
    charge = fixtures.LogisticsFinancialAccessTests.charge
    bill = fixtures.LogisticsFinancialAccessTests.bill

    def test_owner_and_staff_issue_charge_invoices_on_mobile_and_desktop(self):
        worker_cookie = self.client.cookies["sessionid"].value
        owner = Client()
        owner.force_login(self.user)
        session = owner.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        owner_cookie = owner.cookies["sessionid"].value
        evidence = Path("/tmp/mm-finance-browser")
        evidence.mkdir(exist_ok=True)

        def db(action):
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(action).result(timeout=20)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            context = browser.new_context()
            page = context.new_page()
            page.route("https://**/*", lambda route: route.abort())
            page.on("dialog", lambda dialog: dialog.accept())
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for role, cookie, invoice in (
                ("owner", owner_cookie, self.ic),
                ("staff", worker_cookie, self.ia),
            ):
                context.clear_cookies()
                context.add_cookies(
                    [{"name": "sessionid", "value": cookie, "url": self.live_server_url}]
                )
                for width in (390, 1440):
                    page.set_viewport_size({"width": width, "height": 900})
                    page.goto(self.live_server_url + reverse("invoice_detail", args=[invoice.pk]))
                    self.assertTrue(
                        page.get_by_role("button", name="Mark as Sent", exact=True).is_visible()
                    )
                    self.assertEqual(
                        page.get_by_role("link", name="Edit Invoice", exact=True).count(), 0
                    )
                    page.screenshot(
                        path=str(evidence / f"{role}-draft-{width}.png"), full_page=True
                    )
                page.get_by_role("button", name="Mark as Sent", exact=True).click()
                page.wait_for_load_state("networkidle")
                self.assertTrue(
                    page.get_by_role("button", name="Mark as Paid", exact=True).is_visible()
                )
                self.assertEqual(
                    db(lambda invoice=invoice: Invoice.objects.get(pk=invoice.pk).status), "SENT"
                )
                page.screenshot(path=str(evidence / f"{role}-sent.png"), full_page=True)
            response = page.goto(
                self.live_server_url + reverse("invoice_detail", args=[self.mixed.pk])
            )
            self.assertEqual(response.status, 404)
            db(lambda: self.grant(self.a, operate=False))
            page.goto(self.live_server_url + reverse("invoice_detail", args=[self.ia.pk]))
            self.assertEqual(page.get_by_role("button", name="Mark as Paid", exact=True).count(), 0)
            self.assertEqual(errors, [])
            browser.close()
