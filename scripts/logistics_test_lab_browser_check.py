"""Nine actual fixture logins in Chromium at desktop/mobile widths, isolated test DB.

No saved passwords, browser traces or HAR. This is emulation, not device evidence.
Run with PYTHONPATH=src:. and PWA_CHROMIUM, using the acceptance suite runner.
"""

import os
from concurrent.futures import ThreadPoolExecutor

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.businesses.models import UserOnboardingState
from apps.logistics import test_test_lab_dataset as dataset_tests
from apps.logistics.location_access import locations_for
from apps.logistics.models import Parcel, Shipment
from apps.logistics.parcel_services import parcels_for_business


@override_settings(
    DEBUG=True,
    ALLOWED_HOSTS=["localhost", "testserver"],
    MOTIONMATE_ENVIRONMENT="local",
    LOGISTICS_LOCAL_BILLING_BYPASS=True,
    LOGISTICS_TEST_LAB_ENABLED=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class TestLabBrowserChecks(StaticLiveServerTestCase):
    # Exercise Block 06A's encrypted normal provisioner and Block 06B's actual dataset.
    serialized_rollback = True
    setUp = dataset_tests.LogisticsTestLabDatasetTests.setUp
    command = dataset_tests.LogisticsTestLabDatasetTests.command
    execute = dataset_tests.LogisticsTestLabDatasetTests.execute
    decrypt = dataset_tests.LogisticsTestLabDatasetTests.decrypt
    provision = dataset_tests.LogisticsTestLabDatasetTests.provision
    data_command = dataset_tests.LogisticsTestLabDatasetTests.data_command
    seed_data = dataset_tests.LogisticsTestLabDatasetTests.seed_data

    def test_all_nine_logins_navigation_scanner_exports_forms_and_logout(self):
        self.provision()
        self.seed_data()
        self.addCleanup(self.payload.clear)
        plans = []
        for credential in self.payload["accounts"]:
            actor = self.users[credential["email"].split("@")[0]]
            UserOnboardingState.objects.create(
                business=self.business, user=actor, completed_welcome=True
            )
            visible = parcels_for_business(business=self.business, actor=actor)
            allowed = visible.first()
            denied = Parcel.objects.exclude(pk__in=visible.values("pk")).first()
            shipment = Shipment.objects.filter(parcels__in=visible).distinct().first()
            plans.append(
                (
                    credential,
                    allowed,
                    denied,
                    shipment,
                    set(locations_for(self.business, actor).values_list("pk", flat=True)),
                )
            )
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            try:
                for width in (390, 1440):
                    for credential, allowed, denied, shipment, sites in plans:
                        with self.subTest(width=width, email=credential["email"]):
                            context = browser.new_context(
                                viewport={"width": width, "height": 900}, has_touch=width == 390
                            )
                            context.route("https://**/*", lambda route: route.abort())
                            page = context.new_page()
                            errors = []
                            page.on(
                                "pageerror", lambda error, errors=errors: errors.append(str(error))
                            )
                            page.goto(self.live_server_url + reverse("business_login"))
                            page.locator('[name="email"]').fill(credential["email"])
                            page.locator('[name="password"]').fill(credential["password"])
                            page.get_by_role("button", name="Sign In", exact=True).click()
                            page.wait_for_url("**" + reverse("agent_dashboard"))
                            for route in (
                                "logistics_parcel_list",
                                "logistics_shipment_list",
                                "logistics_parcel_scan",
                            ):
                                response = page.goto(self.live_server_url + reverse(route))
                                self.assertEqual(response.status, 200)
                                self.assertIn("no-store", response.headers["cache-control"])
                                self.assertEqual(
                                    page.evaluate("document.documentElement.scrollWidth"),
                                    width,
                                    route,
                                )
                            # Work-location options must contain only this account's permitted sites.
                            choices = page.locator('[name="location"] option[value]').evaluate_all(
                                "options => options.map(o => Number(o.value)).filter(Boolean)"
                            )
                            self.assertTrue(set(choices).issubset(sites))
                            if allowed:
                                field = page.get_by_label("Parcel tracking code", exact=True)
                                field.fill(allowed.tracking_code)
                                field.press("Enter")
                                page.locator(f'[data-scan-parcel="{allowed.pk}"]').wait_for()
                                for route in (
                                    "logistics_parcel_detail",
                                    "logistics_shipping_label",
                                ):
                                    self.assertEqual(
                                        page.goto(
                                            self.live_server_url + reverse(route, args=[allowed.pk])
                                        ).status,
                                        200,
                                    )
                                pdf = context.request.get(
                                    self.live_server_url
                                    + reverse("logistics_shipping_label_pdf", args=[allowed.pk])
                                )
                                self.assertEqual(pdf.status, 200)
                                self.assertTrue(pdf.body().startswith(b"%PDF-"))
                            if denied:
                                self.assertEqual(
                                    page.goto(
                                        self.live_server_url
                                        + reverse("logistics_parcel_detail", args=[denied.pk])
                                    ).status,
                                    404,
                                )
                            if shipment:
                                self.assertEqual(
                                    page.goto(
                                        self.live_server_url
                                        + reverse("logistics_shipment_detail", args=[shipment.pk])
                                    ).status,
                                    200,
                                )
                            if credential["email"].split("@")[0] in {"owner", "admin", "manager"}:
                                for route in ("logistics_shipment_create", "invoice_list"):
                                    self.assertEqual(
                                        page.goto(self.live_server_url + reverse(route)).status, 200
                                    )
                            page.goto(self.live_server_url + reverse("logout"))
                            page.goto(self.live_server_url + reverse("logistics_parcel_list"))
                            self.assertIn(reverse("business_login"), page.url)
                            self.assertEqual(errors, [])
                            context.close()
            finally:
                browser.close()
                database.submit(connections.close_all).result()
