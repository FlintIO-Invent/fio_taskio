"""Parcel wizard interaction checks against a disposable Django test database."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.logistics import test_registration, test_route_entry
from apps.logistics.models import Parcel


def database_read(action):
    """Keep synchronous ORM reads outside Playwright's event loop."""

    def execute():
        try:
            return action()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(execute).result(timeout=20)


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class ParcelWizardBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = test_route_entry.RouteEntryTests.setUp
    switch = test_route_entry.RouteEntryTests.switch
    data = test_route_entry.RouteEntryTests.data
    parcel_form = test_route_entry.RouteEntryTests.parcel_form
    save_parcel = test_route_entry.RouteEntryTests.save_parcel

    def test_entry_review_errors_edit_and_registration_at_mobile_desktop_widths(self):
        existing = self.save_parcel()
        evidence = Path("/tmp/parcel-wizard-browser")
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

            def choose(name, text):
                control = page.locator(f'.choices:has(select[name="{name}"])')
                control.locator(".choices__inner").click()
                control.locator("input.choices__input--cloned").fill(text)
                control.locator("[data-choice-selectable]").filter(has_text=text).last.click()

            def panel(name):
                expect(page.locator(f"#{name}")).to_be_visible()
                self.assertEqual(page.locator("[data-parcel-wizard-panel]:visible").count(), 1)
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"),
                    page.viewport_size["width"] + 1,
                )

            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                start = self.live_server_url + reverse("logistics_parcel_register")
                page.goto(start)
                panel("parcel-basics")
                page.screenshot(path=str(evidence / f"entry-{width}.png"), full_page=True)
                expect(page.get_by_role("button", name="Register & continue")).to_be_hidden()
                # Step links cannot jump past invalid required fields.
                page.locator('[data-parcel-wizard-step="parcel-review"]').click()
                panel("parcel-basics")
                expect(page.locator("[data-parcel-browser-errors]")).to_be_visible()
                choose("client", self.customer.email)
                description = f"Wizard parcel {width} <script>alert(1)</script>"
                page.locator("#id_package_description").fill(description)
                expect(page.locator('[name="quantity"]')).to_have_count(0)
                page.locator("[data-parcel-wizard-next]").click()
                panel("parcel-route")
                page.locator("#id_mode_of_transport").select_option("SEA")
                choose("destination_location", "Roseau")
                expect(page.locator("#id_destination_country_code")).to_have_value("DM")
                page.locator("[data-parcel-wizard-next]").click()
                panel("parcel-details")
                page.locator("[data-additional-details] > summary").click()
                page.locator("#id_length_cm").fill("-1")
                page.locator("[data-parcel-wizard-next]").click()
                panel("parcel-details")
                expect(page.locator("[data-parcel-browser-errors]")).to_contain_text("Length")
                page.locator("#id_length_cm").fill("10")
                page.locator("#id_weight_kg").fill("2.5")
                page.locator("[data-parcel-wizard-next]").click()
                panel("parcel-review")
                expect(page.locator("[data-parcel-wizard-review]")).to_contain_text(description)
                expect(page.locator("[data-parcel-wizard-review]")).to_contain_text("Roseau")
                self.assertEqual(page.locator("[data-parcel-wizard-review] script").count(), 0)
                page.get_by_role("button", name="Edit route", exact=True).click()
                panel("parcel-route")
                expect(page.locator("#id_destination_location")).to_have_value(str(self.dm.pk))
                page.locator("#id_mode_of_transport").select_option("AIR")
                page.locator("[data-parcel-wizard-next]").click()
                panel("parcel-details")
                self.assertTrue(page.locator("#id_vessel_name").is_disabled())
                page.locator("[data-parcel-wizard-next]").click()
                panel("parcel-review")
                page.screenshot(path=str(evidence / f"review-{width}.png"), full_page=True)
                page.get_by_role("button", name="Register & continue", exact=True).click()
                page.wait_for_url("**/registration/")
                panel("registration-billing")
                # Browser Back and optional steps change navigation, not saved state.
                page.locator('[data-parcel-wizard-step="registration-payment"]').click()
                panel("registration-payment")
                page.go_back()
                panel("registration-billing")
                page.locator('[data-parcel-wizard-step="registration-payment"]').click()
                page.get_by_role("link", name="Continue to Shipment; payment later").click()
                panel("registration-shipment")
                page.get_by_role("button", name="Assign later · View summary").click()
                page.wait_for_url("**/registration/?summary=1#registration-summary")
                panel("registration-summary")
                page.screenshot(path=str(evidence / f"summary-{width}.png"), full_page=True)
                parcel = database_read(
                    lambda description=description: Parcel.objects.get(
                        package_description=description
                    )
                )
                self.assertEqual(parcel.quantity, 1)
                self.assertIsNone(parcel.shipment_id)
                # Metadata edits use the same review gate.
                page.goto(self.live_server_url + reverse("logistics_parcel_edit", args=[parcel.pk]))
                panel("parcel-basics")
                page.locator("#id_package_description").fill(f"Edited wizard parcel {width}")
                page.locator('[data-parcel-wizard-step="parcel-review"]').click()
                panel("parcel-review")
                page.get_by_role("button", name="Save Parcel", exact=True).click()
                page.wait_for_url("**/logistics/parcels/*/")
                database_read(parcel.refresh_from_db)
                self.assertEqual(parcel.package_description, f"Edited wizard parcel {width}")
                # A server error in an optional hidden tab must reopen that tab.
                page.goto(start + f"?client={self.customer.pk}")
                page.locator("#id_package_description").fill("Server error parcel")
                page.locator("[data-parcel-wizard-next]").click()
                choose("destination_location", "Roseau")
                page.locator("#id_mode_of_transport").select_option("SEA")
                page.locator('[data-parcel-wizard-step="parcel-review"]').click()

                page.locator("#id_sender_country_code").evaluate(
                    "select => select.add(new Option('Invalid country', 'ZZ', true, true))"
                )
                with page.expect_response(
                    lambda response: response.request.method == "POST"
                    and "/parcels/register/" in response.url
                ) as submitted:
                    page.get_by_role("button", name="Register & continue", exact=True).click()
                self.assertEqual(submitted.value.status, 200)
                page.wait_for_selector("[data-logistics-form-errors]")
                panel("parcel-details")
                expect(page.locator("#parcel-sender")).to_be_visible()
                expect(page.locator("#id_package_description")).to_have_value("Server error parcel")
                # Explicit deep links keep their destination after reload.
                page.goto(
                    self.live_server_url
                    + reverse("logistics_parcel_registration", args=[existing.pk])
                    + "#registration-shipment"
                )
                panel("registration-shipment")
                page.reload()
                panel("registration-shipment")
            self.assertEqual(errors, [])
            context.close()
            # Without JavaScript, the complete server form is still usable.
            fallback = browser.new_context(java_script_enabled=False)
            fallback.add_cookies(
                [
                    {
                        "name": "sessionid",
                        "value": self.client.cookies["sessionid"].value,
                        "url": self.live_server_url,
                    }
                ]
            )
            page = fallback.new_page()
            page.route("https://**/*", lambda route: route.abort())
            page.goto(self.live_server_url + reverse("logistics_parcel_register"))
            expect(page.locator("#parcel-route")).to_be_visible()
            page.locator("[data-additional-details] > summary").click()
            expect(page.locator("#id_sender_name")).to_be_visible()
            expect(page.get_by_role("button", name="Register & continue")).to_be_visible()
            browser.close()


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class ParcelWizardPaymentBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True

    setUp = test_registration.ParcelRegistrationTests.setUp
    parcel = test_registration.ParcelRegistrationTests.parcel
    charge = test_registration.ParcelRegistrationTests.charge
    bill = test_registration.ParcelRegistrationTests.bill

    def test_staff_can_record_full_online_payment_without_references(self):
        from apps.billings.payment_services import invoice_settlement
        from apps.businesses.models import UserOnboardingState
        from apps.logistics.location_test_support import approve_test_site

        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.membership.role = "staff"
        self.membership.save(update_fields=["role"])
        approve_test_site(business=self.business, membership=self.membership, parcel=parcel)
        UserOnboardingState.objects.get_or_create(
            business=self.business, user=self.user, defaults={"completed_welcome": True}
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            context = browser.new_context(viewport={"width": 390, "height": 900})
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
            page.goto(self.live_server_url + reverse("logistics_parcel_charge", args=[parcel.pk]))
            quantity = page.locator('[name="quantity"]')
            expect(quantity).to_have_attribute("step", "1")
            quantity.fill("1")
            quantity.evaluate("input => input.stepUp()")
            expect(quantity).to_have_value("2")
            page.goto(
                self.live_server_url + reverse("logistics_parcel_registration", args=[parcel.pk])
            )
            page.get_by_role("button", name="Issue Invoice Parcel Invoice", exact=True).click()
            page.locator('[data-parcel-wizard-step="registration-payment"]').click()
            page.get_by_role("link", name="Record payment Parcel Invoice", exact=True).click()
            page.locator("#id_method").select_option("ONLINE")
            expect(page.locator("#id_reference")).to_have_value("")
            expect(page.locator("#id_verification_reference")).to_have_count(0)
            page.get_by_role("button", name="Save customer receipt").click()
            page.wait_for_url(lambda url: not urlsplit(url).query)
            balance = database_read(
                lambda: invoice_settlement(business=self.business, actor=self.user, invoice=invoice)
            )
            self.assertTrue(balance.settled)
            self.assertEqual(balance.outstanding, 0)
            browser.close()

    def test_inline_client_and_payment_error_stay_in_their_steps(self):
        from apps.billings.models import InvoicePayment
        from apps.businesses.models import UserOnboardingState

        UserOnboardingState.objects.get_or_create(
            business=self.business, user=self.user, defaults={"completed_welcome": True}
        )
        parcel = self.parcel()
        invoice = self.bill(self.charge(parcel=parcel, unit_price=100))
        guide = self.live_server_url + reverse("logistics_parcel_registration", args=[parcel.pk])
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            context = browser.new_context(viewport={"width": 390, "height": 900})
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
            page.goto(self.live_server_url + reverse("logistics_parcel_register"))
            page.locator("#id_package_description").fill("Keep parcel while adding client")
            page.get_by_role("button", name="Add Client", exact=True).click()
            modal = page.locator("#parcelClientModal")
            for field, value in {
                "first_name": "Wizard",
                "last_name": "Customer",
                "company_name": "Wizard Company",
                "email": "wizard-inline@example.test",
                "phone": "1234567",
                "street_address": "10 Main Street",
            }.items():
                modal.locator(f'[name="new_client-{field}"]').fill(value)
            modal.get_by_role("button", name="Add and Select Client").click()
            expect(modal).to_be_hidden()
            expect(page.locator("#id_package_description")).to_have_value(
                "Keep parcel while adding client"
            )
            expect(page.locator("[data-client-selection-status]")).to_contain_text("Client added")
            self.assertTrue(page.locator("#id_client").input_value())
            page.goto(guide)
            expect(page.locator("#registration-payment")).to_be_visible()
            page.get_by_role(
                "button", name=f"Issue Invoice {invoice.invoice_number}", exact=True
            ).click()
            page.wait_for_url(
                lambda url: urlsplit(url).path == urlsplit(guide).path and not urlsplit(url).query
            )
            page.locator('[data-parcel-wizard-step="registration-payment"]').click()
            page.get_by_role(
                "link", name=f"Record payment {invoice.invoice_number}", exact=True
            ).click()
            expect(page.locator("#id_amount")).to_be_visible()
            page.locator("#id_amount").fill("1000")
            page.locator("#id_reference").fill("WIZARD-CASH-1")
            page.get_by_role("button", name="Save customer receipt").click()
            expect(page.locator("#registration-payment")).to_be_visible()
            expect(page.locator("#id_amount")).to_have_value("1000")
            expect(page.locator("#id_reference")).to_have_value("WIZARD-CASH-1")
            self.assertEqual(database_read(InvoicePayment.objects.count), 0)
            page.locator("#id_amount").fill("100")
            page.get_by_role("button", name="Save customer receipt").click()
            page.wait_for_url(
                lambda url: urlsplit(url).path == urlsplit(guide).path and not urlsplit(url).query
            )
            self.assertEqual(database_read(InvoicePayment.objects.count), 1)
            context.close()
            browser.close()
