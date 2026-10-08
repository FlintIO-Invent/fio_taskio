"""Rendered Logistics audit/acceptance on an isolated DB; optional Playwright tool.

MM_MOBILE_AUDIT=before records the baseline without layout assertions.
Run with PYTHONPATH=src:. python src/manage.py test scripts.logistics_mobile_check
Use PWA_CHROMIUM for the browser binary; evidence goes to /tmp/logistics-mobile-ux.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice, InvoiceLine
from apps.businesses.models import (
    Business,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    UserOnboardingState,
)
from apps.crm.models import Client
from apps.logistics.models import Parcel, Shipment
from apps.logistics.parcel_services import change_parcel_status, register_parcel
from apps.logistics.shipment_services import assign_parcel, create_shipment


@override_settings(
    DEBUG=True, ALLOWED_HOSTS=["localhost", "testserver"], LOGISTICS_LOCAL_BILLING_BYPASS=False
)
class LogisticsMobileChecks(StaticLiveServerTestCase):
    serialized_rollback = True

    def setUp(self):
        self.user = TaskIOUser.objects.create_user(
            email="mobile-operator@example.com", password="MobileTest!91"
        )
        self.business = Business.objects.create(
            name="Mobile Logistics", slug="mobile-logistics", vertical="LOGISTICS"
        )
        ClarivoPlan.objects.filter(slug="logistics").update(is_active=True)
        BusinessUser.objects.create(business=self.business, user=self.user, role="owner")
        BusinessSubscription.objects.create(
            business=self.business,
            plan=ClarivoPlan.objects.get(slug="logistics"),
            status="active",
            billing_interval="yearly",
        )
        UserOnboardingState.objects.create(
            business=self.business, user=self.user, completed_welcome=True
        )
        self.customer = Client.objects.create(
            business=self.business,
            first_name="Alexandra",
            last_name="Vandermeer-Santos",
            company_name="Caribbean Distribution and Transportation Services",
            email="alexandra.vandermeer@example.com",
            phone="+59991234567",
            street_address="123 Caribbean Distribution Centre, Willemstad",
        )
        self.shipment = create_shipment(
            business=self.business,
            actor=self.user,
            origin="Miami Distribution Centre",
            destination="Willemstad Distribution Centre",
            transport_mode="SEA",
            vessel_name="Caribbean Freight Vessel",
            voyage_reference="VOY-2026-1008",
            departure_at=timezone.now(),
            estimated_arrival_at=timezone.now() + timedelta(days=3),
        )
        self.parcel = register_parcel(
            business=self.business,
            client=self.customer,
            actor=self.user,
            origin=self.shipment.origin,
            destination=self.shipment.destination,
            package_description="Replacement parts and warehouse supplies",
            quantity=2,
            sender_name="Miami Distribution Team",
            recipient_name="Willemstad Receiving Team",
            internal_notes="Handle with care",
            weight_kg="4.5",
        )
        change_parcel_status(
            business=self.business, parcel=self.parcel, actor=self.user, status="RECEIVED"
        )
        assign_parcel(
            business=self.business, shipment=self.shipment, parcel=self.parcel, actor=self.user
        )
        for index in range(60):
            register_parcel(
                business=self.business,
                client=self.customer,
                actor=self.user,
                origin="Miami",
                destination="Willemstad",
                package_description=f"Eligible parcel {index:02d}",
            )
        self.invoice = Invoice.objects.create(
            business=self.business,
            client=self.customer,
            invoice_number="MOBILE-2026-1008",
            subtotal="125.00",
            total="125.00",
        )
        InvoiceLine.objects.create(
            invoice=self.invoice,
            description="Freight handling and distribution",
            quantity=1,
            unit_price="125.00",
        )
        self.client.force_login(self.user)
        self.routes = {
            "dashboard": reverse("agent_dashboard"),
            "clients": reverse("staff_client_list"),
            "client-detail": reverse("staff_client_detail", args=[self.customer.pk]),
            "parcels": reverse("logistics_parcel_list"),
            "register": reverse("logistics_parcel_register"),
            "parcel-detail": reverse("logistics_parcel_detail", args=[self.parcel.pk]),
            "parcel-update": reverse("logistics_parcel_update", args=[self.parcel.pk]),
            "shipments": reverse("logistics_shipment_list"),
            "shipment-create": reverse("logistics_shipment_create"),
            "shipment-edit": reverse("logistics_shipment_edit", args=[self.shipment.pk]),
            "shipment-detail": reverse("logistics_shipment_detail", args=[self.shipment.pk]),
            "manifest": reverse("logistics_shipment_manifest", args=[self.shipment.pk]),
            "invoices": reverse("invoice_list"),
            "invoice-detail": reverse("invoice_detail", args=[self.invoice.pk]),
        }

    def test_rendered_layouts(self):
        from playwright.sync_api import sync_playwright

        mode = os.environ.get("MM_MOBILE_AUDIT", "after")
        output = Path("/tmp/logistics-mobile-ux") / mode
        output.mkdir(parents=True, exist_ok=True)
        evidence = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            context = browser.new_context(viewport={"width": 390, "height": 844})
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
            page.on("pageerror", lambda error: errors.append(error.stack or str(error)))
            for width in (320, 390, 430, 600, 800, 1440):
                page.set_viewport_size({"width": width, "height": 844 if width < 1000 else 900})
                for name, route in self.routes.items():
                    with self.subTest(width=width, route=name):
                        response = page.goto(self.live_server_url + route)
                        self.assertEqual(response.status, 200, name)
                        data = page.evaluate(
                            """() => {
                          const visible = element => !element.hidden && element.getAttribute('aria-hidden') !== 'true' && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length) && getComputedStyle(element).visibility !== 'hidden';
                          const content = document.querySelector('.content');
                          const controls = [...content.querySelectorAll('.btn, input:not([type=hidden]), select, .choices__inner, .nav-link')].filter(visible);
                          return {
                            width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
                            tables: [...content.querySelectorAll('.table-responsive')].filter(visible).map(element => ({width:element.clientWidth, scrollWidth:element.scrollWidth})),
                            shortControls: controls.map(element => ({name: element.textContent.trim().slice(0,60) || element.name, height: (element.matches('[type=checkbox], [type=radio]') ? element.closest('label') || element : element).getBoundingClientRect().height})).filter(element => element.height < 43.9),
                            actions: [...content.querySelectorAll('.btn')].filter(visible).map(element => ({name:element.textContent.trim(), y:element.getBoundingClientRect().y})),
                          };
                        }"""
                        )
                        evidence.append({"route": name, "viewport": width, **data})
                        if width in (320, 390, 1440):
                            page.screenshot(
                                path=str(output / f"{width}-{name}.png"), full_page=True
                            )
                        if mode != "before":
                            self.assertLessEqual(data["scrollWidth"], width + 1, data)
                            if width < 992:
                                self.assertEqual(data["shortControls"], [], data)
                                for table in data["tables"]:
                                    self.assertLessEqual(
                                        table["scrollWidth"], table["width"] + 1, data
                                    )
                            if (
                                name
                                in ("register", "parcel-update", "shipment-create", "shipment-edit")
                                and width < 992
                            ):
                                save = page.locator('.mobile-form-actions button[type="submit"]')
                                self.assertLess(save.bounding_box()["y"], 844)
                            if name == "dashboard" and width < 992:
                                sections = page.locator(
                                    ".mobile-dashboard-kpis, .mobile-dashboard-quick, .mobile-dashboard-attention, .mobile-dashboard-shipments, .mobile-dashboard-activity"
                                )
                                positions = sections.evaluate_all(
                                    "(items) => items.map(item => ({name:item.className, y:item.getBoundingClientRect().y})).sort((a,b) => a.y-b.y)"
                                )
                                for position, expected in zip(
                                    positions,
                                    ("kpis", "quick", "attention", "shipments", "activity"),
                                    strict=True,
                                ):
                                    self.assertIn("mobile-dashboard-" + expected, position["name"])
            context.close()
            browser.close()
        (output / "layout-results.json").write_text(
            json.dumps({"layouts": evidence, "page_errors": errors}, indent=2)
        )
        self.assertEqual(errors, [], errors)

    def test_mobile_operations(self):
        from playwright.sync_api import sync_playwright

        if os.environ.get("MM_MOBILE_AUDIT") == "before":
            self.skipTest("Baseline audit is read-only")
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
            )
            context = browser.new_context(
                viewport={"width": 320, "height": 844}, is_mobile=True, has_touch=True
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
            page.set_default_timeout(10000)
            page.route("https://**/*", lambda route: route.abort())
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def db(action, *args, **kwargs):
                return database.submit(action, *args, **kwargs).result()

            def visit(route):
                page.goto(self.live_server_url + route)

            def choose_parcel(parcel):
                choices = page.locator(".choices").filter(has=page.locator("#id_parcel"))
                choices.locator(".choices__inner").click()
                choices.locator("input.choices__input").fill(parcel.tracking_code[:16])
                choices.locator(f'.choices__item--choice[data-value="{parcel.pk}"]').click()

            visit(self.routes["register"])
            page.locator(".mobile-form-actions button").click()
            self.assertTrue(page.locator("[data-parcel-browser-errors]").is_visible())
            page.locator("#id_package_description").fill("Phone registration with retained details")
            page.locator("#id_origin").fill("Miami")
            page.locator("#id_destination").fill("Willemstad")
            page.locator("#id_quantity").fill("2")
            page.set_viewport_size({"width": 320, "height": 420})
            page.locator("#id_origin").focus()
            page.locator("#id_origin").scroll_into_view_if_needed()
            self.assertLessEqual(
                page.locator("#id_origin").bounding_box()["y"]
                + page.locator("#id_origin").bounding_box()["height"],
                420,
            )
            self.assertLess(page.locator(".mobile-form-actions button").bounding_box()["y"], 420)
            page.set_viewport_size({"width": 320, "height": 844})
            page.get_by_role("button", name="Add Client", exact=True).click()
            modal = page.locator("#parcelClientModal")
            modal.locator('[name="new_client-first_name"]').fill("Mobile")
            modal.locator('[name="new_client-last_name"]').fill("Customer")
            modal.locator('[name="new_client-company_name"]').fill("Mobile Warehouse")
            modal.locator('[name="new_client-email"]').fill("mobile-customer@example.com")
            modal.locator('[name="new_client-phone"]').fill("+59991234568")
            modal.locator('[name="new_client-street_address"]').fill("123 Warehouse Road")
            page.get_by_role("button", name="Add and Select Client", exact=True).click()
            try:
                modal.wait_for(state="hidden")
            except Exception:
                Path("/tmp/logistics-mobile-modal-debug.json").write_text(
                    json.dumps(
                        page.evaluate(
                            """() => ({errors: [...document.querySelectorAll('[data-client-fields] :invalid')].map(e => ({name:e.name,value:e.value,message:e.validationMessage})), text: document.querySelector('[data-parcel-client-form]').innerText, choices:typeof window.Choices, select:document.querySelector('#id_client').outerHTML})"""
                        ),
                        indent=2,
                    )
                )
                page.screenshot(path="/tmp/logistics-mobile-modal-debug.png", full_page=True)
                raise
            self.assertEqual(
                page.locator("#id_package_description").input_value(),
                "Phone registration with retained details",
            )
            customer = db(Client.objects.get, email="mobile-customer@example.com")
            self.assertEqual(page.locator("#id_client").input_value(), str(customer.pk))
            # Reject an invalid retry token through a normal CSRF-protected form POST.
            token = page.locator(
                '[data-logistics-parcel-form] [name="idempotency_key"]'
            ).input_value()
            page.locator('[data-logistics-parcel-form] [name="idempotency_key"]').evaluate(
                '(input) => input.value="invalid"'
            )
            page.locator(".mobile-form-actions button").click()
            page.wait_for_load_state()
            page.locator("[data-logistics-form-errors]").wait_for(state="visible")
            self.assertEqual(page.locator("#id_origin").input_value(), "Miami")
            self.assertEqual(
                page.evaluate('document.activeElement.hasAttribute("data-logistics-form-errors")'),
                True,
            )
            page.locator('[data-logistics-parcel-form] [name="idempotency_key"]').evaluate(
                "(input, token) => input.value=token", token
            )
            page.locator(".mobile-form-actions button").click()
            page.wait_for_url("**/logistics/parcels/*/")
            parcel = db(Parcel.objects.get, client=customer)
            visit(reverse("logistics_parcel_update", args=[parcel.pk]))
            page.locator("#id_status").select_option("RECEIVED")
            page.locator("#id_location").fill("Warehouse")
            page.locator(".mobile-form-actions button").click()
            page.wait_for_url("**" + reverse("logistics_parcel_detail", args=[parcel.pk]))
            db(parcel.refresh_from_db)
            self.assertEqual(parcel.current_status, "RECEIVED")

            visit(self.routes["shipment-create"])
            page.locator("#id_transport_mode").select_option("ROAD")
            self.assertTrue(page.locator('[data-shipment-reference-mode="ROAD"]').is_visible())
            self.assertFalse(page.locator('[data-shipment-reference-mode="SEA"]').is_visible())
            page.locator("#id_vehicle_reference").fill("TRUCK-21")
            page.locator("#id_origin").fill("Miami")
            page.locator("#id_destination").fill("Willemstad")
            choose_parcel(parcel)
            page.locator(".mobile-form-actions button").click()
            page.wait_for_url("**/logistics/shipments/*/")
            shipment = db(Shipment.objects.get, transport_mode="ROAD")
            db(parcel.refresh_from_db)
            self.assertEqual(parcel.shipment_id, shipment.pk)
            # Dismissing cancellation must not submit a write.
            page.once("dialog", lambda dialog: dialog.dismiss())
            page.get_by_role("button", name="Cancel shipment", exact=True).click()
            db(shipment.refresh_from_db)
            self.assertEqual(shipment.status, "DRAFT")
            for status in ("READY", "IN_TRANSIT", "ARRIVED"):
                with page.expect_navigation():
                    page.get_by_role(
                        "button", name="Mark " + Shipment.Status(status).label, exact=True
                    ).click()
                db(shipment.refresh_from_db)
                self.assertEqual(shipment.status, status)
            for status in ("READY", "DELIVERED"):
                visit(reverse("logistics_parcel_update", args=[parcel.pk]))
                page.locator("#id_status").select_option(status)
                page.locator(".mobile-form-actions button").click()
                page.wait_for_url("**" + reverse("logistics_parcel_detail", args=[parcel.pk]))
                db(parcel.refresh_from_db)
                self.assertEqual(parcel.current_status, status)
            visit(reverse("logistics_shipment_detail", args=[shipment.pk]))
            with page.expect_navigation():
                page.get_by_role("button", name="Mark Completed", exact=True).click()
            db(shipment.refresh_from_db)
            self.assertEqual(shipment.status, "COMPLETED")

            visit(self.routes["shipment-detail"])
            page.once("dialog", lambda dialog: dialog.accept())
            with page.expect_navigation():
                page.get_by_role("button", name="Cancel shipment", exact=True).click()
            db(self.shipment.refresh_from_db)
            db(self.parcel.refresh_from_db)
            self.assertEqual(self.shipment.status, "CANCELLED")
            self.assertIsNone(self.parcel.shipment_id)
            # The route is highlighted, while the mobile sidebar starts closed.
            visit(self.routes["parcels"])
            self.assertFalse(page.locator("#navbarVerticalCollapse").is_visible())
            page.get_by_role("button", name="Toggle Navigation").click()
            self.assertTrue(page.locator('.navbar-vertical a[aria-current="page"]').is_visible())
            self.assertEqual(
                page.locator('.navbar-vertical a[aria-current="page"]').get_attribute("href"),
                self.routes["parcels"],
            )
            self.assertEqual(
                page.locator('.navbar-vertical a[href="/logistics/track/"]').count(), 0
            )
            page.get_by_role("button", name="Toggle Navigation").click()
            page.screenshot(
                path="/tmp/logistics-mobile-ux/after/320-workflow-complete.png", full_page=True
            )
            self.assertEqual(errors, [])
            context.close()
            browser.close()
