"""Run only with taskio.services_test_settings and disposable PostgreSQL."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.appointments.models import Appointment
from apps.billings.services import create_invoice_for_client
from apps.businesses.models import ClarivoPlan
from apps.businesses.test_service_allowances import ServicesFixture
from apps.crm.models import Client, Lead


def database_call(operation):
    try:
        return operation()
    finally:
        connections.close_all()


class UnifiedAppointmentsBrowserChecks(ServicesFixture, StaticLiveServerTestCase):
    def test_internal_creation_and_inline_client_start_and_finish_in_appointments(self):
        self.login()
        evidence = Path("/tmp/taskio-unified-appointments-browser")
        evidence.mkdir(exist_ok=True)
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as playwright:
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
            for width in (1440, 390):
                page.set_viewport_size({"width": width, "height": 900})
                title = f"Internal visit {width}"
                email = f"internal-{width}@example.test"
                page.goto(self.live_server_url + reverse("appointment_list"))
                page.get_by_role("link", name="New Appointment", exact=True).click()
                page.locator("#id_title").fill(title)
                page.locator("#id_notes").fill("Preserve this draft")
                page.locator("#id_start_time").fill(self.start.strftime("%Y-%m-%dT%H:%M"))
                page.locator("#id_end_time").fill(
                    self.start.replace(hour=11).strftime("%Y-%m-%dT%H:%M")
                )
                page.get_by_role("button", name="Add a new client", exact=True).click()
                modal = page.locator("#draftClientModal")
                expect(modal).to_be_visible()
                for field, value in {
                    "first_name": "Internal",
                    "last_name": f"Customer {width}",
                    "company_name": f"Household {width}",
                    "email": email,
                    "phone": "+17215550100",
                    "street_address": "12 Example Street",
                }.items():
                    modal.locator(f'[name="new_client-{field}"]').fill(value)
                modal.locator('[type="submit"]').click()
                expect(modal).not_to_be_visible()
                expect(page.locator("#id_notes")).to_have_value("Preserve this draft")
                expect(page.locator("#id_title")).to_have_value(title)
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(path=str(evidence / f"internal-draft-{width}.png"), full_page=True)
                page.get_by_role("button", name="Create appointment", exact=True).click()
                expect(page.get_by_role("heading", name="Actions", exact=True)).to_be_visible()
                page.get_by_role("link", name="Appointments", exact=True).last.click()
                expect(
                    page.locator('[data-entry-kind="appointment"]').filter(has_text=title)
                ).to_have_count(1)
                self.assertEqual(
                    database.submit(
                        database_call,
                        lambda title=title, email=email: Appointment.objects.filter(
                            title=title, client__email=email
                        ).count(),
                    ).result(),
                    1,
                )

                page.get_by_role("link", name="Create Request", exact=True).click()
                expect(page.locator("#id_lead_type")).to_have_value("REQUEST")
                for field, value in {
                    "first_name": f"Follow-up {width}",
                    "last_name": "Customer",
                    "company_name": f"Household {width}",
                    "email": email,
                    "phone": "+17215550100",
                }.items():
                    page.locator(f"#id_{field}").fill(value)
                page.get_by_role("button", name="Create service request", exact=True).click()
                expect(page).to_have_url(self.live_server_url + reverse("appointment_list"))
                row = page.locator('[data-entry-kind="request"]').filter(
                    has_text=f"Follow-up {width}"
                )
                expect(row).to_have_count(1)
                expect(row).to_contain_text("Needs follow-up")
                expect(row).to_contain_text("Not scheduled")
                expect(row).to_contain_text("Internal")
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.screenshot(
                    path=str(evidence / f"internal-results-{width}.png"), full_page=True
                )
            self.assertFalse(errors, errors)
            context.close()
            browser.close()

    def test_workspace_filters_details_scheduling_and_request_only_access(self):
        self.login()
        callbacks = []
        for width in (1440, 390):
            client = self.new_client(client_status="LEAD")
            callbacks.append(
                Lead.objects.create(
                    business=self.business,
                    lead_type="REQUEST",
                    first_name=f"Callback {width}",
                    last_name="Customer",
                    email=client.email,
                    phone=client.phone,
                    company_name=client.company_name,
                    street_address=client.street_address,
                    requested_service=self.service,
                    request_source="public_booking",
                )
            )
        Lead.objects.create(
            business=self.business,
            lead_type="REQUEST",
            first_name="Internal request",
            email=self.customer.email,
            request_source="staff",
            requested_service=self.service,
        )
        source = Lead.objects.create(
            business=self.business,
            lead_type="REQUEST",
            email=self.customer.email,
            request_source="public_booking",
        )
        booked = self.appointment(
            title="Booked visit one",
            staff_member=self.owner,
            service=self.service,
            source_lead=source,
        )
        self.appointment(title="Booked visit two", source_lead=source)
        invoice = create_invoice_for_client(
            actor=self.owner, client=self.customer, appointment=booked
        )
        evidence = Path("/tmp/taskio-unified-appointments-browser")
        evidence.mkdir(exist_ok=True)
        with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as playwright:
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
            for width in (1440, 390):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(self.live_server_url + reverse("appointment_list"))
                rows = page.locator("[data-entry-kind]")
                expect(rows).to_have_count(5)
                expect(page.locator('[data-entry-kind="request"]')).to_have_count(3)
                page.get_by_label("State", exact=True).select_option("needs_follow_up")
                page.get_by_label("Source", exact=True).select_option("online")
                page.get_by_label("Client classification", exact=True).select_option("LEAD")
                page.get_by_role("button", name="Filter", exact=True).click()
                expect(rows).to_have_count(2)
                expect(rows.first).to_contain_text("Not scheduled")
                page.screenshot(path=str(evidence / f"follow-up-{width}.png"), full_page=True)
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                )
                page.get_by_role("link", name="Reset", exact=True).click()
                page.get_by_label("Staff", exact=True).select_option(str(self.owner.pk))
                page.get_by_role("button", name="Filter", exact=True).click()
                expect(rows).to_have_count(1)
                page.get_by_role("link", name="Booked visit one", exact=True).click()
                page.get_by_role("link", name="View Invoice", exact=True).click()
                expect(page).to_have_url(
                    self.live_server_url + reverse("invoice_detail", args=[invoice.pk])
                )

            callback = callbacks[-1]
            page.goto(self.live_server_url + reverse("appointment_list"))
            page.get_by_role("link", name="Callback 390 Customer", exact=True).click()
            page.get_by_role("link", name="Confirm / Schedule Appointment", exact=True).click()
            page.locator("#id_start_time").fill(self.start.strftime("%Y-%m-%dT%H:%M"))
            page.locator("#id_end_time").fill(
                self.start.replace(hour=11).strftime("%Y-%m-%dT%H:%M")
            )
            page.get_by_role("button", name="Create appointment", exact=True).click()
            expect(page.get_by_role("heading", name="Actions", exact=True)).to_be_visible()
            page.goto(self.live_server_url + reverse("appointment_list"))
            expect(
                page.locator(f'[data-entry-kind="request"][data-entry-id="{callback.pk}"]')
            ).to_have_count(0)
            self.assertEqual(
                database.submit(
                    database_call, lambda: Appointment.objects.filter(source_lead=callback).count()
                ).result(),
                1,
            )
            self.assertEqual(
                database.submit(
                    database_call, lambda: Client.objects.get(email=callback.email).client_status
                ).result(),
                "LEAD",
            )

            database.submit(
                database_call,
                lambda: ClarivoPlan.objects.filter(pk=self.plan.pk).update(
                    allow_appointments=False
                ),
            ).result()
            page.goto(self.live_server_url + reverse("appointment_list"))
            expect(page.locator('[data-entry-kind="appointment"]')).to_have_count(0)
            expect(page.get_by_role("link", name="Create Request", exact=True).last).to_be_visible()
            expect(page.get_by_role("link", name="New Appointment", exact=True)).to_have_count(0)
            page.screenshot(path=str(evidence / "request-only-390.png"), full_page=True)
            self.assertFalse(errors, errors)
            context.close()
            browser.close()
