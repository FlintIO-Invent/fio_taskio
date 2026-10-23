"""Optional real Chromium check on disposable local PostgreSQL only."""

import os
import uuid
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.billings.models import InvoicePayment
from apps.billings.services import change_invoice_status
from apps.logistics import test_parcel_intake
from apps.logistics.billing_services import add_charge, invoice_charges
from apps.logistics.models import Parcel
from scripts.logistics_parcel_wizard_browser_check import database_read


@override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"])
class RegistrationChangesBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp_base = test_parcel_intake.ParcelIntakeTests.setUp_base
    switch = test_parcel_intake.ParcelIntakeTests.switch
    setUp = test_parcel_intake.ParcelIntakeTests.setUp
    select = test_parcel_intake.ParcelIntakeTests.select
    parcel = test_parcel_intake.ParcelIntakeTests.parcel
    ship = test_parcel_intake.ParcelIntakeTests.ship

    def test_hub_receipt_explicit_decision_validation_and_mobile_desktop(self):
        self.client.force_login(self.staff)
        evidence = Path("/tmp/clarivo-four-browser")
        evidence.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(
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

            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(self.live_server_url + reverse("logistics_parcel_register"))
                choose("client", self.customer.email)
                description = f"Physical hub receipt {width}"
                page.locator("#id_package_description").fill(description)
                page.locator("[data-parcel-wizard-next]").click()
                choose("destination_location", self.b.name)
                page.locator("[data-parcel-wizard-next]").click()
                page.locator("[data-parcel-wizard-next]").click()
                page.get_by_role("button", name="Register & continue", exact=True).click()
                page.wait_for_url("**/registration/")
                parcel = database_read(
                    lambda description=description: Parcel.objects.get(
                        package_description=description
                    )
                )
                self.assertEqual(parcel.current_status, "RECEIVED")
                self.assertEqual(
                    database_read(
                        lambda parcel=parcel: list(parcel.events.values_list("status", flat=True))
                    ),
                    ["REGISTERED", "RECEIVED"],
                )

                def bill(parcel=parcel):
                    charge = add_charge(
                        business=self.business,
                        actor=self.user,
                        parcel=parcel,
                        description="Hub handling",
                        unit_price=25,
                        idempotency_key=uuid.uuid4(),
                    )
                    invoice = invoice_charges(
                        business=self.business, actor=self.user, charge_ids=[charge.pk]
                    )
                    change_invoice_status(
                        business=self.business, actor=self.user, invoice=invoice, status="SENT"
                    )
                    return invoice.pk

                invoice_id = database_read(bill)
                url = self.live_server_url + reverse(
                    "logistics_parcel_registration", args=[parcel.pk]
                )
                page.goto(url)
                expect(page.locator("#registration-payment")).to_be_visible()
                self.assertEqual(page.locator('[name="decision"]:checked').count(), 0)
                page.locator("[data-parcel-wizard-next]").click()
                expect(page.locator("#registration-payment")).to_be_visible()
                expect(page.locator("#registration-payment")).to_contain_text(
                    "Select paid or unpaid"
                )
                page.locator('[name="decision"][value="unpaid"]').check()
                page.locator("[data-parcel-wizard-back]").click()
                page.locator("[data-parcel-wizard-next]").click()
                expect(page.locator('[name="decision"][value="unpaid"]')).to_be_checked()
                page.locator("[data-parcel-wizard-next]").click()
                expect(page.locator("#registration-shipment")).to_be_visible()
                self.assertEqual(
                    database_read(
                        lambda invoice_id=invoice_id: InvoicePayment.objects.filter(
                            invoice_id=invoice_id
                        ).count()
                    ),
                    0,
                )
                expect(
                    page.get_by_role("link", name="Create Shipment with this Parcel")
                ).to_have_count(0)
                page.locator("[data-parcel-wizard-back]").click()
                page.locator('[name="decision"][value="paid"]').check()
                page.locator("#id_amount").fill("")
                page.locator("[data-parcel-wizard-next]").click()
                expect(page.locator("#registration-payment")).to_be_visible()
                expect(page.locator('[name="decision"][value="paid"]')).to_be_checked()
                expect(page.locator("#registration-payment")).to_contain_text(
                    "This field is required"
                )
                page.locator("#id_amount").fill("10")
                page.locator("#id_method").select_option("CASH")
                page.screenshot(path=str(evidence / f"payment-{width}.png"), full_page=True)
                page.locator("[data-parcel-wizard-next]").click()
                expect(page.locator("#registration-shipment")).to_be_visible()
                page.reload()
                self.assertEqual(
                    database_read(
                        lambda invoice_id=invoice_id: InvoicePayment.objects.filter(
                            invoice_id=invoice_id
                        ).count()
                    ),
                    1,
                )
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"shipment-{width}.png"), full_page=True)
            self.assertEqual(errors, [])
            browser.close()

    def test_business_defaults_and_saved_service_prefill_at_mobile_desktop(self):
        from apps.crm.models import BusinessService
        from apps.logistics.models import LogisticsProfile

        self.business.country = "US"
        self.business.save(update_fields=["country"])
        LogisticsProfile.objects.filter(business=self.business).update(transportation_modes=["SEA"])
        service = BusinessService.objects.create(
            business=self.business, name="Hub service", unit_price=25
        )
        evidence = Path("/tmp/clarivo-four-browser")
        evidence.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(
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
                page.goto(self.live_server_url + reverse("business_settings"))
                page.locator("#id_logistics_vessel_names").fill("MV One\nMV Two")
                page.locator("#id_logistics_carrier_names").fill("Carrier One\nCarrier Two")
                page.locator("#id_logistics_default_vessel").fill("MV One")
                page.locator("#id_logistics_default_carrier").fill("Carrier One")
                page.get_by_role("button", name="Save business settings", exact=True).click()
                expect(page.get_by_text("Business settings updated.", exact=True)).to_be_visible()
                self.assertEqual(
                    database_read(
                        lambda: self.business.__class__.objects.get(
                            pk=self.business.pk
                        ).logistics_default_vessel
                    ),
                    "MV One",
                )
                page.locator("#logistics-defaults").scroll_into_view_if_needed()
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"defaults-{width}.png"), full_page=True)
                page.goto(self.live_server_url + reverse("logistics_shipment_create"))
                expect(page.locator("#id_vessel_name")).to_have_value("MV One")
                expect(page.locator("#id_carrier_name")).to_have_value("Carrier One")
                page.locator("[data-additional-details] > summary").click()
                page.locator("#id_vessel_name").select_option("MV Two")
                expect(page.locator("#id_vessel_name")).to_have_value("MV Two")
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"transport-{width}.png"), full_page=True)
                page.goto(self.live_server_url + reverse("logistics_parcel_register"))
                expect(page.locator("#id_vessel_name")).to_have_value("MV One")
                page.goto(
                    self.live_server_url + reverse("logistics_parcel_charge", args=[self.item.pk])
                )
                page.locator("#id_service").select_option(str(service.pk))
                expect(page.locator("#id_unit_price")).to_have_value("25.00")
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"service-{width}.png"), full_page=True)
            self.assertEqual(errors, [])
            browser.close()
