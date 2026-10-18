"""Optional browser verification; run with manage.py test against a disposable DB."""

import csv
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.accounts.models import TaskIOUser
from apps.businesses import test_configuration_update
from apps.businesses.models import BusinessInvitation, BusinessUser
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import BusinessService, ImportJob, ServiceCategory
from apps.logistics.models import LogisticsLocationAssignment


@override_settings(
    DEBUG=True,
    ALLOWED_HOSTS=["localhost", "testserver"],
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class ConfigurationBrowserChecks(StaticLiveServerTestCase):
    serialized_rollback = True
    site = test_configuration_update.InvitationLocationTests.site
    switch = test_configuration_update.InvitationLocationTests.switch

    def setUp(self):
        test_configuration_update.InvitationLocationTests.setUp(self)
        BusinessUser.objects.create(business=self.services, user=self.owner, role="owner")
        self.cookies = {}
        self.existing = {}
        for business in (self.business, self.services):
            for role in BusinessUser.Role.values:
                user = (
                    self.owner
                    if role == "owner"
                    else TaskIOUser.objects.create_user(
                        email=f"{business.slug}-{role}@browser.test", first_name=role.title()
                    )
                )
                if role != "owner":
                    BusinessUser.objects.create(business=business, user=user, role=role)
                client = Client()
                client.force_login(user)
                session = client.session
                session[CURRENT_BUSINESS_SESSION_KEY] = business.pk
                session.save()
                self.cookies[business.pk, role] = client.cookies["sessionid"].value
            category = ServiceCategory.objects.create(business=business, name="Existing")
            self.existing[business.pk] = BusinessService.objects.create(
                business=business,
                category=category,
                name="Before",
                external_code="UPDATE",
                unit_price=Decimal("10.00"),
                tax_rate=Decimal("3.00"),
            ).pk
        self.evidence = Path("/tmp/motionmate-config-verification")
        self.evidence.mkdir(exist_ok=True)
        self.layout_problems = []
        self.js_errors = []

    def db(self, action):
        def run():
            try:
                return action()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(run).result(timeout=30)

    def browser(self, playwright):
        return playwright.chromium.launch(
            headless=True, executable_path=os.environ.get("PWA_CHROMIUM")
        )

    def page(self, browser, business, width, role="owner", anonymous=False):
        context = browser.new_context(viewport={"width": width, "height": 900})
        if not anonymous:
            context.add_cookies(
                [
                    {
                        "name": "sessionid",
                        "value": self.cookies[business.pk, role],
                        "url": self.live_server_url,
                    }
                ]
            )
        page = context.new_page()
        page.route("https://**/*", lambda route: route.abort())
        page.on("pageerror", lambda error: self.js_errors.append(str(error)))
        return context, page

    def capture(self, page, name, width):
        page.wait_for_timeout(100)
        actual_width = page.evaluate("document.documentElement.scrollWidth")
        if actual_width > width + 1:
            self.layout_problems.append((name, width, actual_width))
            overflowing = page.evaluate(
                """width => [...document.querySelectorAll('body *')]
                .filter(element => {
                    const rect = element.getBoundingClientRect();
                    return rect.width > 0 && rect.right > width + 1;
                }).map(element => ({tag: element.tagName, classes: element.className,
                    text: element.innerText?.slice(0, 80),
                    right: element.getBoundingClientRect().right,
                    width: element.getBoundingClientRect().width,
                    overflow: getComputedStyle(element).overflowX})).slice(0, 60)""",
                width,
            )
            (self.evidence / f"{name}-{width}-overflow.json").write_text(
                json.dumps(overflowing, indent=2)
            )
        page.screenshot(path=str(self.evidence / f"{name}-{width}.png"), full_page=True)

    def finish(self, name):
        (self.evidence / f"{name}.json").write_text(
            json.dumps(
                {
                    "layout_problems": self.layout_problems,
                    "javascript_errors": self.js_errors,
                },
                indent=2,
            )
        )
        self.assertEqual(self.js_errors, [])
        self.assertEqual(self.layout_problems, [])

    @patch("apps.businesses.views.send_business_invitation_email", return_value=False)
    def test_invitation_selection_signup_acceptance_and_assignment(self, _send):
        with sync_playwright() as playwright:
            browser = self.browser(playwright)
            for business in (self.business, self.services):
                for width in (390, 1440):
                    context, page = self.page(browser, business, width)
                    page.goto(self.live_server_url + reverse("business_team_members"))
                    email = f"signup-{business.pk}-{width}@browser.test"
                    page.locator("#id_email").fill(email)
                    page.locator("#id_role").select_option("staff")
                    if business == self.business:
                        options = page.locator("#id_location option").evaluate_all(
                            "items => items.map(item => item.value)"
                        )
                        self.assertIn(str(self.location.pk), options)
                        self.assertNotIn(str(self.foreign.pk), options)
                        page.locator("#id_location").select_option(str(self.location.pk))
                    else:
                        self.assertEqual(page.locator("#id_location").count(), 0)
                    page.get_by_role("button", name="Send invitation").click()
                    page.wait_for_url("**/team/")
                    invitation = self.db(
                        lambda email=email: BusinessInvitation.objects.get(email=email)
                    )
                    self.assertEqual(
                        invitation.location_id,
                        self.location.pk if business == self.business else None,
                    )
                    self.capture(page, f"{business.slug}-team", width)
                    context.close()
                    context, page = self.page(browser, business, width, anonymous=True)
                    page.goto(
                        self.live_server_url
                        + reverse("accept_business_invitation", args=[invitation.token])
                    )
                    page.locator("#id_first_name").fill("Browser")
                    page.locator("#id_last_name").fill("Employee")
                    for field in ("password1", "password2"):
                        page.locator(f"#id_{field}").fill("Browser-Local-Verification-42!")
                    self.capture(page, f"{business.slug}-accept", width)
                    page.get_by_role("button", name="Create account and join workspace").click()
                    page.wait_for_url("**" + reverse("agent_dashboard"))

                    def persisted(business=business, email=email):
                        member = BusinessUser.objects.get(business=business, user__email=email)
                        self.assertEqual(member.role, "staff")
                        assignments = LogisticsLocationAssignment.objects.filter(membership=member)
                        if business == self.business:
                            assignment = assignments.get()
                            self.assertEqual(assignment.location_id, self.location.pk)
                            self.assertTrue(assignment.is_current)
                            self.assertFalse(assignment.can_operate)
                        else:
                            self.assertFalse(assignments.exists())

                    self.db(persisted)
                    context.close()
            browser.close()
        self.finish("invitations")

    def test_combined_upload_preview_execution_and_invalid_rows(self):
        with sync_playwright() as playwright:
            browser = self.browser(playwright)
            for business in (self.business, self.services):
                for width in (390, 1440):
                    context, page = self.page(browser, business, width)
                    for route_name in (
                        "business_service_list",
                        "business_service_category_list",
                        "data_import",
                    ):
                        response = page.goto(self.live_server_url + reverse(route_name))
                        self.assertEqual(response.status, 200)
                        self.capture(page, f"{business.slug}-{route_name}", width)
                    page.goto(self.live_server_url + reverse("business_service_import"))
                    with page.expect_download() as download:
                        page.get_by_role("link", name="Download Template").first.click()
                    self.assertIn(
                        "category", Path(download.value.path()).read_text().splitlines()[0]
                    )
                    self.capture(page, f"{business.slug}-upload", width)

                    def upload(rows, page=page):
                        content = io.StringIO(newline="")
                        writer = csv.writer(content)
                        writer.writerow(
                            ["name", "unit_price", "category", "external_code", "tax_rate"]
                        )
                        writer.writerows(rows)
                        page.locator("input[type=file]").set_input_files(
                            {
                                "name": "combined.csv",
                                "mimeType": "text/csv",
                                "buffer": content.getvalue().encode(),
                            }
                        )
                        page.get_by_role("button", name="Validate and preview").click()
                        page.wait_for_url("**/preview/")
                        return page.url.rstrip("/").split("/")[-2]

                    category_name = f"New category {width}"
                    job_id = upload(
                        [
                            [f"First {width}", "12.50", category_name, f"FIRST-{width}", ""],
                            [
                                f"Second {width}",
                                "20.00",
                                category_name.upper(),
                                f"SECOND-{width}",
                                "",
                            ],
                            [f"Updated {width}", "35.50", "Existing", "UPDATE", "3.00"],
                        ]
                    )
                    self.assertEqual(
                        page.get_by_role("button", name="Confirm Service Import").count(), 1
                    )
                    self.assertEqual(page.locator("tbody tr").count(), 3)
                    self.assertIn("UPDATE", page.locator("tbody").inner_text())
                    self.capture(page, f"{business.slug}-preview", width)
                    if width == 390:
                        page.locator(".table-responsive").first.evaluate(
                            "element => element.scrollLeft = element.scrollWidth"
                        )
                        self.capture(page, f"{business.slug}-preview-details", width)
                    preview = self.db(
                        lambda job_id=job_id: ImportJob.objects.get(pk=job_id).preview_payload
                    )
                    self.assertEqual(preview["metadata"]["summary"]["categories_to_create"], 1)
                    self.assertEqual(preview["metadata"]["summary"]["update_count"], 1)
                    self.assertFalse(
                        self.db(
                            lambda business=business, category_name=category_name: ServiceCategory.objects.filter(
                                business=business, name=category_name
                            ).exists()
                        )
                    )
                    page.get_by_role("button", name="Confirm Service Import").click()
                    page.wait_for_url("**/result/")
                    self.assertTrue(
                        page.get_by_role("heading", name="Import complete", exact=True).is_visible()
                    )
                    self.capture(page, f"{business.slug}-result", width)

                    def matches_preview(preview=preview, business=business, width=width):
                        for row in preview["normalized_rows"]:
                            fields = row["service_fields"]
                            service = BusinessService.objects.get(
                                business=business, external_code=fields["external_code"]
                            )
                            for field, value in fields.items():
                                actual = getattr(service, field)
                                self.assertEqual(
                                    actual,
                                    (
                                        Decimal(value)
                                        if field in ("unit_price", "tax_rate")
                                        else value
                                    ),
                                    field,
                                )
                            self.assertEqual(service.category.business_id, business.pk)
                            if row["category"]["will_create"]:
                                self.assertEqual(service.category.code, row["category"]["key"])
                        self.assertEqual(
                            business.service_categories.count(), 2 if width == 390 else 3
                        )

                    self.db(matches_preview)
                    before = self.db(
                        lambda business=business: (
                            list(business.business_services.order_by("pk").values()),
                            list(business.service_categories.order_by("pk").values()),
                        )
                    )
                    page.goto(self.live_server_url + reverse("business_service_import"))
                    upload(
                        [
                            ["Valid", "15.00", "Must not exist", "VALID-BLOCKED", ""],
                            ["Invalid", "bad", "Must not exist", "INVALID", ""],
                        ]
                    )
                    self.assertEqual(
                        page.get_by_role("button", name="Confirm Service Import").count(), 0
                    )
                    self.assertIn("ERROR", page.locator("tbody").inner_text())
                    self.assertIn("3", page.locator("tbody tr").nth(1).inner_text())
                    self.capture(page, f"{business.slug}-invalid", width)
                    if width == 390:
                        page.locator(".table-responsive").first.evaluate(
                            "element => element.scrollLeft = element.scrollWidth"
                        )
                        self.capture(page, f"{business.slug}-invalid-details", width)
                    after = self.db(
                        lambda business=business: (
                            list(business.business_services.order_by("pk").values()),
                            list(business.service_categories.order_by("pk").values()),
                        )
                    )
                    self.assertEqual(before, after)
                    context.close()
            browser.close()
        self.finish("imports")

    def test_settings_profile_roles_links_and_responsive_layout(self):
        with sync_playwright() as playwright:
            browser = self.browser(playwright)
            for business in (self.business, self.services):
                for role in BusinessUser.Role.values:
                    for width in (390, 1440):
                        context, page = self.page(browser, business, width, role)
                        response = page.goto(self.live_server_url + reverse("business_settings"))
                        self.assertEqual(response.status, 200)
                        if role in ("owner", "admin"):
                            self.assertEqual(response.status, 200)
                            section = page.locator('section[aria-labelledby="configuration-title"]')
                            payment_link = section.get_by_role(
                                "link", name="Subscription and Motionmate payment settings"
                            )
                            self.assertEqual(payment_link.count(), int(role == "owner"))
                            for href in section.locator("a").evaluate_all(
                                "items => items.map(item => item.getAttribute('href'))"
                            ):
                                if href.startswith("/"):
                                    self.assertEqual(
                                        context.request.get(self.live_server_url + href).status,
                                        200,
                                        (business.slug, role, href),
                                    )
                            self.capture(page, f"{business.slug}-{role}-settings", width)
                        else:
                            self.assertEqual(page.locator('form input[name="currency"]').count(), 0)
                        response = page.goto(self.live_server_url + reverse("saas_profile"))
                        self.assertEqual(response.status, 200)
                        self.assertTrue(
                            page.get_by_role("heading", name="My account", exact=True).is_visible()
                        )
                        self.assertIn(reverse("business_settings") + "#my-account", page.url)
                        self.assertNotIn("Account Profile", page.locator("body").inner_text())
                        self.assertNotIn("Legacy", page.locator("body").inner_text())
                        self.assertEqual(
                            page.locator(f'a[href^="{reverse("saas_profile")}"]').count(), 0
                        )
                        self.assertEqual(
                            page.locator('#my-account form input[name="account-email"]').count(), 1
                        )
                        self.assertEqual(
                            page.locator('input[name="email"]').count(),
                            int(role in ("owner", "admin")),
                        )
                        self.assertEqual(
                            context.request.get(
                                self.live_server_url + reverse("password_change")
                            ).status,
                            200,
                        )
                        if role not in ("owner", "admin"):
                            csrf = page.locator(
                                'input[name="csrfmiddlewaretoken"]'
                            ).first.input_value()
                            denied = context.request.post(
                                self.live_server_url + reverse("business_settings"),
                                form={"csrfmiddlewaretoken": csrf, "name": "Forbidden"},
                            )
                            self.assertEqual(denied.status, 403)
                        self.capture(page, f"{business.slug}-{role}-profile", width)
                        context.close()
            browser.close()
        self.finish("settings-profile")

    def test_personal_profile_save_preserves_business_configuration(self):
        with sync_playwright() as playwright:
            browser = self.browser(playwright)
            for business in (self.business, self.services):
                before = self.db(
                    lambda business=business: type(business).objects.values().get(pk=business.pk)
                )
                for role in BusinessUser.Role.values:
                    context, page = self.page(browser, business, 390, role)
                    page.goto(self.live_server_url + reverse("business_settings"))
                    form = page.locator("#my-account form")
                    form.locator('input[name="account-first_name"]').fill("Verified")
                    form.locator('input[name="account-last_name"]').fill(role.title())
                    form.get_by_role("button", name="Save personal details").click()
                    self.assertIn("Personal details updated.", page.locator("body").inner_text())
                    self.capture(page, f"{business.slug}-{role}-profile-saved", 390)
                    context.close()
                after = self.db(
                    lambda business=business: type(business).objects.values().get(pk=business.pk)
                )
                self.assertEqual(before, after)
            browser.close()
        self.finish("profile-save")
