"""Browser checks using taskio.services_test_settings and disposable PostgreSQL."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.appointments.models import Appointment
from apps.businesses.test_service_allowances import ServicesFixture
from apps.crm.models import Client, Lead


class DraftClientBrowserChecks(ServicesFixture, StaticLiveServerTestCase):
    def test_client_creation_keeps_drafts_on_desktop_and_mobile(self):
        self.login()
        evidence = Path("/tmp/taskio-draft-client-browser")
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
                page.set_viewport_size({"width": width, "height": 667 if width == 390 else 900})
                for route in ("appointment_create", "staff_lead_create"):
                    is_lead = route == "staff_lead_create"
                    name = f"Draft {route} {width}"
                    email = f"{route}-{width}@example.test"
                    page.goto(self.live_server_url + reverse(route))
                    page.locator("#id_notes").fill(name)
                    if is_lead:
                        page.locator("#id_first_name").fill("Prefilled")
                    else:
                        page.locator("#id_title").fill(name)
                        page.locator("#id_start_time").fill(self.start.strftime("%Y-%m-%dT%H:%M"))
                        page.locator("#id_end_time").fill(
                            self.start.replace(hour=11).strftime("%Y-%m-%dT%H:%M")
                        )
                    page.locator('[data-bs-target="#draftClientModal"]').click()
                    modal = page.locator("#draftClientModal")
                    expect(modal).to_be_visible()
                    if is_lead:
                        expect(modal.locator('[name="new_client-first_name"]')).to_have_value(
                            "Prefilled"
                        )
                    modal.get_by_role("button", name="Cancel", exact=True).click()
                    expect(modal).not_to_be_visible()
                    expect(page.locator(".modal-backdrop")).to_have_count(0)
                    expect(page.locator("#id_notes")).to_have_value(name)
                    page.locator('[data-bs-target="#draftClientModal"]').click()
                    values = {
                        "first_name": "   ",
                        "last_name": "Customer",
                        "company_name": name,
                        "email": email,
                        "phone": "+17215550100",
                        "street_address": "12 Example Street",
                    }
                    for field, value in values.items():
                        modal.locator(f'[name="new_client-{field}"]').fill(value)
                    with page.expect_response(
                        lambda response: "quick-create" in response.url
                    ) as invalid:
                        modal.locator('[type="submit"]').click()
                    self.assertEqual(invalid.value.status, 400)
                    expect(modal.locator("[data-draft-client-errors]")).to_be_visible()
                    expect(modal.locator("[data-draft-client-errors]")).to_contain_text(
                        "First name:"
                    )
                    self.assertFalse(
                        database.submit(
                            lambda email=email: Client.objects.filter(email=email).exists()
                        ).result()
                    )
                    modal.locator('[name="new_client-first_name"]').fill("New")
                    page.screenshot(path=str(evidence / f"dialog-{route}-{width}.png"))
                    with page.expect_response(
                        lambda response: "quick-create" in response.url
                    ) as saved:
                        modal.locator('[type="submit"]').click()
                    self.assertEqual(saved.value.status, 201)
                    expect(modal).not_to_be_visible()
                    expect(page.locator(".modal-backdrop")).to_have_count(0)
                    client = database.submit(
                        lambda email=email: Client.objects.get(email=email, business=self.business)
                    ).result()
                    expect(page.locator("#id_notes")).to_have_value(name)
                    if is_lead:
                        expect(page.locator("#id_first_name")).to_have_value("New")
                        expect(page.locator("#id_email")).to_have_value(email)
                        page.locator("#id_lead_type").select_option("REQUEST")
                    else:
                        expect(page.locator("#id_client")).to_have_value(str(client.pk))
                        expect(page.locator("#id_title")).to_have_value(name)
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width + 1
                    )
                    page.screenshot(
                        path=str(evidence / f"saved-{route}-{width}.png"), full_page=True
                    )
                    with page.expect_navigation():
                        page.locator(
                            'form:not([data-draft-client-form]) button[type="submit"]'
                        ).click()
                    if is_lead:
                        self.assertTrue(
                            database.submit(
                                lambda email=email, name=name: Lead.objects.filter(
                                    business=self.business, email=email, notes=name
                                ).exists()
                            ).result()
                        )
                    else:
                        self.assertTrue(
                            database.submit(
                                lambda client=client, name=name: Appointment.objects.filter(
                                    business=self.business, client=client, notes=name
                                ).exists()
                            ).result()
                        )
            self.assertEqual(errors, [])
            browser.close()
