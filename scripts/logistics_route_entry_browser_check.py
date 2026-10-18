"""Disposable database browser check for daily route forms."""

import os
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.logistics import test_route_entry
from apps.logistics.models import LogisticsLocation
from apps.logistics.parcel_services import edit_parcel
from apps.logistics.shipment_services import update_shipment


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class RouteEntryBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    setUp = test_route_entry.RouteEntryTests.setUp
    switch = test_route_entry.RouteEntryTests.switch
    data = test_route_entry.RouteEntryTests.data
    parcel_form = test_route_entry.RouteEntryTests.parcel_form
    shipment_form = test_route_entry.RouteEntryTests.shipment_form
    save_parcel = test_route_entry.RouteEntryTests.save_parcel
    save_shipment = test_route_entry.RouteEntryTests.save_shipment

    def test_destinations_are_available_before_country_selection_and_follow_restored_country(self):
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
            held = []
            for url in ("logistics_parcel_register", "logistics_shipment_create"):
                page.goto(self.live_server_url + reverse(url))
                self.assertEqual(page.locator("#id_destination_country_code").input_value(), "")
                self.assertEqual(
                    set(
                        page.locator("#id_destination_location option").evaluate_all(
                            "options => options.map(option => option.value)"
                        )
                    ),
                    {"", str(self.sxm.pk), str(self.dm.pk)},
                )
                facility = page.locator('.choices:has(select[name="destination_location"])')
                facility.locator(".choices__inner").click()
                facility.locator("input.choices__input--cloned").fill("Roseau")
                facility.locator("[data-choice-selectable]").filter(has_text="Roseau").last.click()
                self.assertEqual(page.locator("#id_destination_country_code").input_value(), "DM")
                self.assertEqual(
                    page.locator("#id_destination_location").input_value(), str(self.dm.pk)
                )

                held.clear()
                page.route("https://unpkg.com/@turf/**", lambda route: held.append(route))
                page.goto(self.live_server_url + reverse(url), wait_until="commit")
                page.locator("#id_destination_country_code").wait_for(state="visible")
                # Browser form restoration need not dispatch a change event.
                page.locator("#id_destination_country_code").evaluate(
                    "select => { select.value = 'SX'; }"
                )
                for request in held:
                    request.abort()
                page.unroute("https://unpkg.com/@turf/**")
                page.wait_for_load_state("domcontentloaded")
                self.assertEqual(page.locator("#id_destination_country_code").input_value(), "SX")
                self.assertEqual(
                    set(
                        page.locator("#id_destination_location option").evaluate_all(
                            "options => options.map(option => option.value)"
                        )
                    ),
                    {"", str(self.sxm.pk)},
                )
                page.locator("#id_destination_country_code").evaluate(
                    "select => { select.value = 'DM'; }"
                )
                page.evaluate(
                    "window.dispatchEvent(new PageTransitionEvent('pageshow'))"
                )
                expect(
                    page.locator(
                        '.choices:has(select[name="destination_country_code"]) .choices__list--single'
                    )
                ).to_contain_text("Dominica")
                self.assertEqual(
                    set(
                        page.locator("#id_destination_location option").evaluate_all(
                            "options => options.map(option => option.value)"
                        )
                    ),
                    {"", str(self.dm.pk)},
                )
            browser.close()

    def test_destination_choices_work_while_external_scripts_are_loading(self):
        extra = [
            LogisticsLocation.objects.create(
                business=self.business,
                name=f"Roseau receiving office {index}",
                code=f"DM-OFFICE-{index}",
                country_code="DM",
                location_type="BRANCH",
            )
            for index in range(10)
        ]
        destinations = {"", str(self.dm.pk), *(str(item.pk) for item in extra)}
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
            held = []
            page.route("https://**/*", lambda route: route.abort())
            # This unrelated blocking vendor script precedes the Choices library.
            page.route("https://unpkg.com/@turf/**", lambda route: held.append(route))
            for url in ("logistics_parcel_register", "logistics_shipment_create"):
                page.goto(self.live_server_url + reverse(url), wait_until="commit")
                page.locator("#id_destination_country_code").wait_for(state="visible")
                self.assertEqual(page.evaluate("document.readyState"), "loading")
                page.locator("#id_destination_country_code").select_option("DM")
                self.assertEqual(
                    set(
                        page.locator("#id_destination_location option").evaluate_all(
                            "options => options.map(option => option.value)"
                        )
                    ),
                    destinations,
                )
                page.locator("#id_destination_location").select_option(str(extra[-1].pk))
                page.locator("#id_destination_country_code").select_option("SX")
                self.assertEqual(
                    set(
                        page.locator("#id_destination_location option").evaluate_all(
                            "options => options.map(option => option.value)"
                        )
                    ),
                    {"", str(self.sxm.pk)},
                )
                for request in held:
                    request.abort()
                held.clear()
                page.wait_for_load_state("domcontentloaded")
                self.assertEqual(page.locator("#id_destination_country_code").input_value(), "SX")
                self.assertEqual(
                    set(
                        page.locator("#id_destination_location option").evaluate_all(
                            "options => options.map(option => option.value)"
                        )
                    ),
                    {"", str(self.sxm.pk)},
                )
                country = page.locator('.choices:has(select[name="destination_country_code"])')
                country.locator(".choices__inner").click()
                country.locator("input.choices__input--cloned").fill("Dominica")
                country.locator("[data-choice-selectable]").filter(has_text="Dominica").last.click()
                facility = page.locator('.choices:has(select[name="destination_location"])')
                facility.locator(".choices__inner").click()
                facility.locator("input.choices__input--cloned").fill("Roseau")
                expect(
                    facility.locator("[data-choice-selectable]").filter(has_text="Roseau")
                ).to_have_count(11)
            browser.close()

    def test_create_edit_desktop_mobile_and_dynamic_choices(self):
        parcel, shipment = self.save_parcel(), self.save_shipment()
        edit_parcel(
            business=self.business,
            actor=self.staff,
            parcel=parcel,
            destination_reference_code="DMRSU",
        )
        update_shipment(
            business=self.business,
            actor=self.staff,
            shipment=shipment,
            expected_revision=shipment.revision,
            destination_reference_code="DMRSU",
        )
        routes = [
            ("parcel-create", reverse("logistics_parcel_register")),
            ("parcel-edit", reverse("logistics_parcel_edit", args=[parcel.pk])),
            ("shipment-create", reverse("logistics_shipment_create")),
            ("shipment-edit", reverse("logistics_shipment_edit", args=[shipment.pk])),
        ]
        evidence = Path("/tmp/logistics-route-entry-browser")
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

            for width in (390, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                for name, route in routes:
                    page.goto(self.live_server_url + route)
                    page.wait_for_selector('[data-route-country="destination"]', state="attached")
                    self.assertFalse(
                        page.locator("[data-additional-details]").evaluate("(e) => e.open")
                    )
                    self.assertEqual(
                        page.locator('input[name="origin"]').get_attribute("type"), "hidden"
                    )
                    choose("destination_country_code", "Dominica")
                    self.assertEqual(
                        page.locator("#id_destination_country_code").input_value(), "DM"
                    )
                    facility_options = page.locator(
                        "#id_destination_location option"
                    ).all_text_contents()
                    self.assertTrue(
                        any("Roseau" in text for text in facility_options), facility_options
                    )
                    self.assertFalse(
                        any("Foreign" in text or "SXM" in text for text in facility_options)
                    )
                    choose("destination_location", "Roseau")
                    mode = page.locator('[name="transport_mode"], [name="mode_of_transport"]')
                    mode.select_option("SEA")
                    page.locator("[data-additional-details] > summary").click()
                    references = page.locator(
                        "#id_destination_reference_code option"
                    ).all_text_contents()
                    self.assertTrue(any("DMRSU" in text for text in references), references)
                    mode.select_option("AIR")
                    references = page.locator(
                        "#id_destination_reference_code option"
                    ).all_text_contents()
                    self.assertEqual(
                        any("DMRSU" in text for text in references), "edit" in name, references
                    )
                    self.assertTrue(any("DMDOM" in text for text in references), references)
                    self.assertFalse(page.locator('[name="vessel_name"]').is_visible())
                    self.assertTrue(page.locator('[name="vessel_name"]').is_disabled())
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width + 1
                    )
                    page.locator("[data-additional-details] > summary").click()
                    page.evaluate("window.scrollTo(0, 0)")
                    page.screenshot(path=str(evidence / f"{name}-{width}.png"), full_page=True)
                    if width == 1440 and "edit" in name:
                        page.get_by_role(
                            "button",
                            name="Save Parcel" if name.startswith("parcel") else "Save Shipment",
                            exact=True,
                        ).click()
                        page.wait_for_url(
                            "**/logistics/parcels/*/"
                            if name.startswith("parcel")
                            else "**/logistics/shipments/*/"
                        )
            self.assertEqual(errors, [])
            browser.close()
