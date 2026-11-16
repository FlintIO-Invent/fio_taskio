"""Real Django before/after evidence; verified disposable PostgreSQL only.

SERVICES_DASHBOARD_UI_STAGE=before captures without asserting new UI features.
All artifacts stay under SERVICES_DASHBOARD_UI_ROOT/evidence, outside the repo.
"""

import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.urls import reverse
from PIL import Image, ImageChops
from playwright.sync_api import expect, sync_playwright

from apps.appointments.models import Appointment
from apps.billings.payment_services import record_invoice_payment
from apps.crm.test_services_dashboard_ui import DashboardFixture

SIZES = [(1440, 900), (768, 1024), (390, 844)]
STATES = [
    "populated",
    "empty",
    "long",
    "locked",
    "restricted",
    "grace",
    "admin",
    "staff",
    "accountant",
    "viewer",
]
REPO = Path(__file__).resolve().parents[1]
AXE = (REPO / "ui-lab/services-dashboard/tools/node_modules/axe-core/axe.min.js").read_text()
NUNITO = (
    REPO / "ui-lab/services-dashboard/shared/assets/nunito-sans-latin-wght-normal.woff2"
).read_bytes()


def axe_node_key(violation, node):
    # Axe may reorder equivalent class selectors as the document changes.
    targets = tuple(
        re.sub(
            r"(?:\.[\w-]+){2,}",
            lambda m: "".join(sorted(re.findall(r"\.[\w-]+", m.group()))),
            target,
        )
        for target in node["target"]
    )
    return violation["id"], targets


def db_call(action):
    def run():
        try:
            return action()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(run).result(timeout=30)


def local_browser_network(page, local_url):
    """No browser requests may leave loopback; preserve the existing shell font."""

    def handle(route):
        url = route.request.url
        if url.startswith(local_url + "/"):
            route.continue_()
        elif url.startswith("https://fonts.googleapis.com/"):
            route.fulfill(
                content_type="text/css",
                body="@font-face{font-family:'Nunito Sans';font-style:normal;font-weight:200 1000;src:url('https://fonts.gstatic.com/step7-nunito.woff2') format('woff2')}",
            )
        elif url == "https://fonts.gstatic.com/step7-nunito.woff2":
            route.fulfill(content_type="font/woff2", body=NUNITO)
        elif url.startswith("https://unicons.iconscout.com/"):
            route.fulfill(content_type="text/css", body="/* Test substitution: unused Unicons. */")
        elif url.startswith("https://unpkg.com/@turf/"):
            route.fulfill(
                content_type="application/javascript", body="/* Test substitution: no maps. */"
            )
        else:
            route.abort()

    page.context.route("**/*", handle)


class ServicesDashboardBrowserChecks(DashboardFixture, StaticLiveServerTestCase):
    serialized_rollback = True
    port = 8768

    def test_time_currency_and_direction(self):
        if os.environ.get("SERVICES_DASHBOARD_UI_STAGE", "after") == "before":
            self.skipTest("New presentation cases are after-only.")
        out = Path(os.environ["SERVICES_DASHBOARD_UI_ROOT"]) / "evidence/after/time-currency"
        out.mkdir(parents=True, exist_ok=True)
        checks = []

        def prepare():
            cookie = self.login_role()
            record_invoice_payment(
                business=self.business,
                actor=self.owner,
                invoice=self.invoices[0],
                amount=Decimal("40"),
                currency="USD",
                method="CASH",
                reference="STEP7-BROWSER",
                idempotency_key=uuid.uuid4(),
            )
            self.business.currency, self.business.country, self.business.default_locale = (
                "EUR",
                "Netherlands",
                "nl-NL",
            )
            self.business.timezone = "Europe/Amsterdam"
            self.business.save()
            for appointment, instant in zip(
                self.appointments[:2],
                [
                    datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
                    datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
                ],
                strict=True,
            ):
                Appointment.objects.filter(pk=appointment.pk).update(
                    start_time=instant, end_time=instant + timedelta(minutes=30)
                )
            return cookie

        cookie = db_call(prepare)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
            try:
                with mock.patch(
                    "django.utils.timezone.now",
                    return_value=datetime(2026, 10, 24, 23, 45, tzinfo=UTC),
                ):
                    for width in (390, 1440):
                        for theme in ("light", "dark"):
                            context = browser.new_context(
                                viewport={"width": width, "height": 900},
                                service_workers="block",
                                reduced_motion="reduce",
                            )
                            context.add_cookies(
                                [
                                    {
                                        "name": settings.SESSION_COOKIE_NAME,
                                        "value": cookie,
                                        "url": self.live_server_url,
                                    }
                                ]
                            )
                            context.add_init_script(
                                f"localStorage.setItem('phoenixTheme','{theme}');"
                            )
                            page = context.new_page()
                            local_browser_network(page, self.live_server_url)
                            self.assertEqual(
                                page.goto(
                                    self.live_server_url + reverse("agent_dashboard"),
                                    wait_until="networkidle",
                                ).status,
                                200,
                            )
                            page.evaluate("document.fonts.ready")
                            self.assertTrue(
                                page.evaluate(
                                    "document.fonts.check('600 16px \"Motionmate Dashboard Manrope\"')"
                                )
                            )
                            for appointment, offset in zip(
                                self.appointments[:2], ["UTC+02:00", "UTC+01:00"], strict=True
                            ):
                                row = page.locator(
                                    f'.mm-sd-appointment[data-record-id="{appointment.pk}"]'
                                )
                                self.assertIn("2:30 AM", row.inner_text())
                                self.assertIn(offset, row.inner_text())
                            row = page.locator(
                                f'.mm-sd-invoice[data-record-id="{self.invoices[0].pk}"]'
                            )
                            self.assertIn("$85,00", row.inner_text())
                            self.assertIn("USD", row.inner_text())
                            self.assertIn("Partially paid", row.inner_text())
                            self.assertIn(
                                "€625,00", page.locator(".mm-sd-finance-summary").inner_text()
                            )
                            self.assertTrue(
                                page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                            )
                            page.screenshot(
                                path=str(out / f"dst-eur-usd-{width}-{theme}.png"),
                                full_page=True,
                                animations="disabled",
                            )
                            checks.append(
                                f"{width}/{theme}: local Manrope loaded; repeated 02:30 has both DST offsets; saved USD receipt remains USD; EUR workspace total stays separate"
                            )
                            context.close()
                context = browser.new_context(
                    viewport={"width": 390, "height": 844}, service_workers="block"
                )
                context.add_cookies(
                    [
                        {
                            "name": settings.SESSION_COOKIE_NAME,
                            "value": cookie,
                            "url": self.live_server_url,
                        }
                    ]
                )
                context.add_init_script(
                    "localStorage.setItem('phoenixIsRTL','true');localStorage.setItem('phoenixTheme','dark');"
                )
                page = context.new_page()
                local_browser_network(page, self.live_server_url)
                page.goto(
                    self.live_server_url + reverse("agent_dashboard"), wait_until="networkidle"
                )
                self.assertEqual(page.locator("html").get_attribute("dir"), "rtl")
                self.assertTrue(page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"))
                page.screenshot(
                    path=str(out / "rtl-390-dark.png"), full_page=True, animations="disabled"
                )
                checks.append(
                    "Existing Phoenix RTL switch retained; dashboard reflows at 390px (Latin synthetic content only)"
                )
                context.close()
                (out / "results.json").write_text(
                    json.dumps(
                        {"pass": True, "checks": checks, "browser": browser.version}, indent=2
                    )
                    + "\n"
                )
            finally:
                browser.close()

    def test_interactions(self):
        if os.environ.get("SERVICES_DASHBOARD_UI_STAGE", "after") == "before":
            self.skipTest("New dashboard interactions are after-only.")
        out = Path(os.environ["SERVICES_DASHBOARD_UI_ROOT"]) / "evidence/after/interactions"
        out.mkdir(parents=True, exist_ok=True)
        checks, errors, failed = [], [], []
        report = {"checks": checks}
        url = self.live_server_url + reverse("agent_dashboard")

        def prepare(name="populated"):
            self.scenario(name)
            return self.login_role()

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
            report["browser"] = browser.version
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                reduced_motion="reduce",
                service_workers="block",
            )
            cookie = db_call(prepare)
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": cookie,
                        "url": self.live_server_url,
                    }
                ]
            )
            context.add_init_script("localStorage.setItem('phoenixTheme','light');")
            page = context.new_page()
            local_browser_network(page, self.live_server_url)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "requestfailed",
                lambda request: failed.append({"url": request.url, "failure": request.failure}),
            )

            def assert_dialog_focus(dialog, key="Tab"):
                # Native Bootstrap permits leaving web content for browser chrome.
                # Returning must re-enter the dialog, never another app control.
                if not page.evaluate("document.hasFocus()"):
                    self.assertTrue(page.evaluate("document.activeElement===document.body"))
                    page.keyboard.press(key)
                self.assertTrue(dialog.evaluate("e=>e.contains(document.activeElement)"))

            try:
                page.goto(url, wait_until="networkidle")
                self.assertEqual(page.locator("main").count(), 1)
                self.assertEqual(page.locator("h1").count(), 1)
                self.assertEqual(page.locator('[data-bs-target="#searchBoxModal"]').count(), 0)
                self.assertEqual(page.locator(".mm-sd-appointment:visible").count(), 3)
                self.assertEqual(page.locator(".mm-sd-request:visible").count(), 3)
                detail = page.locator("[data-mm-sd-more]").first
                detail.locator("summary").focus()
                page.keyboard.press("Enter")
                self.assertEqual(page.locator(".mm-sd-appointment:visible").count(), 5)
                expect(detail.locator("summary")).to_have_text("Show fewer appointments")
                self.assertEqual(
                    detail.locator("summary").evaluate("e=>getComputedStyle(e).outlineStyle"),
                    "solid",
                )
                page.set_viewport_size({"width": 1440, "height": 900})
                self.assertEqual(page.locator(".mm-sd-request:visible").count(), 5)
                page.set_viewport_size({"width": 390, "height": 844})
                self.assertEqual(page.locator(".mm-sd-appointment:visible").count(), 5)
                page.locator(".mm-sd-appointments summary").click()
                self.assertEqual(page.locator(".mm-sd-appointment:visible").count(), 3)
                checks.append(
                    "Mobile disclosures: 3/5 rows, keyboard Enter, remembered choice, desktop 5; visible focus"
                )

                for selector in [".mm-sd-appointment", ".mm-sd-request", ".mm-sd-invoice"]:
                    link = page.locator(selector).first
                    href = link.get_attribute("href")
                    with page.expect_navigation(wait_until="networkidle") as response:
                        link.click()
                    self.assertEqual(response.value.status, 200)
                    self.assertEqual(page.url, self.live_server_url + href)
                    page.goto(url, wait_until="networkidle")
                for label in ["Open Appointments", "View Bookings", "View Invoices"]:
                    link = page.get_by_role("link", name=label, exact=True).first
                    href = link.get_attribute("href")
                    with page.expect_navigation(wait_until="networkidle") as response:
                        link.click()
                    self.assertEqual(response.value.status, 200)
                    self.assertEqual(page.url, self.live_server_url + href)
                    page.goto(url, wait_until="networkidle")
                checks.append(
                    "Actual appointment/request/invoice detail and list destinations respond 200; follow-up query retained"
                )
                booking = page.locator(".mm-sd-share-actions a")
                href = booking.get_attribute("href")
                with page.expect_popup() as event:
                    booking.click()
                popup = event.value
                popup.wait_for_load_state("networkidle")
                self.assertEqual(popup.url, self.live_server_url + href)
                self.assertTrue(popup.locator("form").count())
                popup.close()
                page.bring_to_front()
                checks.append(
                    "Booking Open action reaches the supplied relative public-booking destination in a new tab"
                )

                page.locator('label[for="themeControlToggle"]:visible').click()
                self.assertEqual(page.locator("html").get_attribute("data-bs-theme"), "dark")
                self.assertEqual(page.evaluate("localStorage.getItem('phoenixTheme')"), "dark")
                self.assertFalse(
                    page.evaluate("Object.keys(localStorage).some(k=>k.includes('lab-theme'))")
                )
                checks.append(
                    "Existing Phoenix theme toggle persists dark theme without a parallel preference"
                )
                page.get_by_role("link", name="Motionmate home", exact=True).focus()
                page.keyboard.press("Tab")
                self.assertEqual(page.evaluate("document.activeElement.id"), "themeControlToggle")
                self.assertEqual(
                    page.locator('label[for="themeControlToggle"]:visible').evaluate(
                        "e=>getComputedStyle(e).outlineStyle"
                    ),
                    "solid",
                )
                page.keyboard.press("Space")
                self.assertEqual(page.locator("html").get_attribute("data-bs-theme"), "light")
                checks.append(
                    "Theme checkbox is in the native Tab sequence, has a visible label focus ring and toggles with Space"
                )
                page.get_by_role("button", name="Account menu").click()
                self.assertTrue(page.locator(".dropdown-profile.show").is_visible())
                page.keyboard.press("Escape")
                self.assertFalse(page.locator(".dropdown-profile.show").count())
                self.assertEqual(page.evaluate("document.activeElement.id"), "navbarDropdownUser")
                page.get_by_role("button", name="Toggle Navigation").click()
                page.locator("#navbarVerticalCollapse.show").wait_for(state="visible")
                page.get_by_role("button", name="Toggle Navigation").click()
                page.locator("#navbarVerticalCollapse.show").wait_for(state="hidden")
                checks.append(
                    "Bootstrap account dropdown and Phoenix mobile navigation still open and close"
                )

                page.evaluate(
                    "Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:text=>new Promise(resolve=>{window.copyText=text;window.finishCopy=resolve})}})"
                )
                page.locator("[data-mm-sd-copy]").click()
                self.assertTrue(page.locator("[data-mm-sd-copy]").is_disabled())
                self.assertEqual(
                    page.locator("[data-mm-sd-copy]").get_attribute("aria-busy"), "true"
                )
                self.assertEqual(
                    page.evaluate("window.copyText"),
                    page.locator("#mm-sd-booking-url").input_value(),
                )
                page.evaluate("window.finishCopy()")
                page.get_by_text("Link copied", exact=True).wait_for()
                self.assertTrue(page.locator("[data-mm-sd-copy]").is_enabled())
                for value in ['{writeText:()=>Promise.reject(new Error("denied"))}', "undefined"]:
                    page.evaluate(
                        "Object.defineProperty(navigator,'clipboard',{configurable:true,value:"
                        + value
                        + "})"
                    )
                    page.locator("[data-mm-sd-copy]").click()
                    page.locator("#mm-sd-copy-status[data-failed]").wait_for()
                    self.assertEqual(
                        page.locator("#mm-sd-booking-url").evaluate(
                            "e=>e===document.activeElement&&e.selectionEnd-e.selectionStart===e.value.length"
                        ),
                        True,
                    )
                checks.append(
                    "Clipboard simulated success/busy, rejection and unavailable API select the exact server URL with live feedback"
                )

                for width, height in SIZES:
                    for theme in ("light", "dark"):
                        page.set_viewport_size({"width": width, "height": height})
                        page.evaluate("theme=>localStorage.setItem('phoenixTheme',theme)", theme)
                        db_call(lambda: prepare("welcome"))
                        page.goto(url, wait_until="networkidle")
                        modal = page.locator("#onboardingWelcomeModal")
                        modal.locator("button").first.wait_for(state="visible")
                        self.assertIn("show", modal.get_attribute("class"))
                        self.assertTrue(
                            modal.locator("input[name=csrfmiddlewaretoken]").first.input_value()
                        )
                        modal.get_by_role("button", name="Close", exact=True).focus()
                        for _ in range(8):
                            page.keyboard.press("Tab")
                            assert_dialog_focus(modal)
                        page.screenshot(
                            path=str(out / f"welcome-{width}-{theme}.png"),
                            full_page=True,
                            animations="disabled",
                        )
                        form = modal.locator("form").filter(
                            has=page.locator("input[name=selected_journey][value=setup_business]")
                        )
                        self.assertEqual(
                            form.locator("input[name=open_guide_after_select]").input_value(), "1"
                        )
                        with page.expect_navigation(wait_until="networkidle"):
                            form.locator("button[type=submit]").click()
                        self.assertTrue(page.url.endswith("?setup_guide=1"))
                        panel = page.locator("#onboardingGuidePanel")
                        panel.get_by_role("button", name="Close", exact=True).wait_for(
                            state="visible"
                        )
                        page.keyboard.press("Escape")
                        self.assertIn("show", panel.get_attribute("class"))
                        panel.get_by_role("button", name="Close", exact=True).focus()
                        page.keyboard.press("Shift+Tab")
                        assert_dialog_focus(panel, "Shift+Tab")
                        page.screenshot(
                            path=str(out / f"guide-{width}-{theme}.png"),
                            full_page=True,
                            animations="disabled",
                        )
                        self.assertEqual(
                            page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),
                            True,
                        )
                        with page.expect_navigation(wait_until="networkidle"):
                            panel.get_by_role("button", name="Close", exact=True).click()
                        self.assertNotIn("setup_guide", page.url)
                checks.append(
                    "Six viewport/theme pairs: real CSRF journey selection POST, guide auto-open, static Escape behavior, close POST"
                )

                page.get_by_role("button", name="Open Setup Guide").click()
                panel = page.locator("#onboardingGuidePanel")
                panel.get_by_role("button", name="Next", exact=True).wait_for(state="visible")
                with page.expect_navigation(wait_until="networkidle"):
                    panel.get_by_role("button", name="Next", exact=True).click()
                self.assertTrue(page.url.endswith("?setup_guide=1"))
                panel.get_by_role("button", name="Back", exact=True).wait_for(state="visible")
                with page.expect_navigation(wait_until="networkidle"):
                    panel.get_by_role("button", name="Back", exact=True).click()
                with page.expect_navigation(wait_until="networkidle"):
                    panel.get_by_role("button", name="Open Business Settings", exact=True).click()
                self.assertIn(reverse("business_settings"), page.url)
                checks.append(
                    "Existing guide Next/Back/start-task forms POST and navigate to Business Settings"
                )

                db_call(prepare)
                page.goto(url, wait_until="networkidle")
                for width in (320, 390, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertTrue(
                        page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                    )
                page.set_viewport_size({"width": 320, "height": 844})
                page.screenshot(
                    path=str(out / "reflow-320-dark.png"), full_page=True, animations="disabled"
                )
                page.emulate_media(reduced_motion="no-preference")
                self.assertTrue(page.locator(".mm-services-dashboard").is_visible())
                page.evaluate(AXE)
                report["axeKeyboardPage"] = page.evaluate(
                    "async()=>{const r=await axe.run('.mm-services-dashboard');return {violations:r.violations.map(v=>v.id),incomplete:r.incomplete.map(v=>v.id)}}"
                )
                self.assertFalse(report["axeKeyboardPage"]["violations"])
                checks.append("320px reflow and normal/reduced motion; dashboard region axe")

                nojs = browser.new_context(
                    java_script_enabled=False,
                    viewport={"width": 390, "height": 844},
                    service_workers="block",
                )
                nojs.add_cookies(context.cookies())
                fallback = nojs.new_page()
                local_browser_network(fallback, self.live_server_url)
                self.assertEqual(fallback.goto(url, wait_until="networkidle").status, 200)
                self.assertEqual(fallback.locator(".mm-sd-appointment:visible").count(), 5)
                self.assertEqual(fallback.locator(".mm-sd-request:visible").count(), 5)
                self.assertTrue(fallback.locator("#mm-sd-booking-url").input_value())
                fallback.screenshot(path=str(out / "no-js-390.png"), full_page=True)
                nojs.close()
                checks.append(
                    "Without JavaScript: all 5 server records and manual-copy URL remain available"
                )
                self.assertFalse(errors, errors)
                self.assertFalse(failed, failed)
                report["pass"] = True
            except Exception as error:
                report.update({"pass": False, "error": str(error)})
                page.screenshot(path=str(out / "failure.png"), full_page=True)
                raise
            finally:
                report.update(browserErrors=errors, failedRequests=failed)
                (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
                context.close()
                browser.close()

    def test_before_after_matrix_and_workflows(self):
        stage = os.environ.get("SERVICES_DASHBOARD_UI_STAGE", "after")
        root = Path(os.environ["SERVICES_DASHBOARD_UI_ROOT"])
        out = root / "evidence" / stage
        out.mkdir(parents=True, exist_ok=True)
        cases = []
        baseline = {}
        if stage == "after":
            saved = json.loads((root / "evidence/before/results.json").read_text())
            self.assertEqual(saved["passed"], saved["total"])
            baseline = {(c["state"], c["width"], c["theme"]): c for c in saved["cases"]}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
            cases_to_run = [(state, "agent_dashboard", "owner", False) for state in STATES]
            cases_to_run += [
                (name, route, "owner", False)
                for name, route in [
                    ("unchanged-appointments", "appointment_list"),
                    ("unchanged-clients", "staff_client_list"),
                    ("unchanged-invoices", "invoice_list"),
                    ("unchanged-settings", "business_settings"),
                    ("unchanged-services", "business_service_list"),
                ]
            ]
            cases_to_run += [
                ("logistics-" + role, "agent_dashboard", role, True) for role in ["owner", "staff"]
            ]
            try:
                for state, route, role, logistics in cases_to_run:
                    scenario = state if state in STATES else "populated"
                    if scenario in self.roles:
                        role, scenario = scenario, "populated"

                    def prepare(scenario=scenario, logistics=logistics, role=role, route=route):
                        self.scenario(scenario)
                        business = (
                            self.logistics
                            if logistics
                            else self.empty_business
                            if scenario == "empty"
                            else self.business
                        )
                        cookie = self.login_role(role, business)
                        response = self.client.get(reverse(route))
                        context = response.context
                        projection = {}
                        if route == "agent_dashboard" and not logistics:
                            for key in [
                                "client_count",
                                "open_service_request_count",
                                "new_service_request_count",
                                "public_booking_pending_review_count",
                                "today_appointment_count",
                                "upcoming_appointment_count",
                                "open_invoice_count",
                                "draft_invoice_count",
                                "sent_invoice_count",
                                "invoice_value_this_month",
                                "unpaid_invoice_total",
                                "dashboard_appointments_enabled",
                                "dashboard_invoices_enabled",
                            ]:
                                projection[key] = str(context[key])
                            for key in [
                                "upcoming_appointments",
                                "service_request_followups",
                                "recent_invoices",
                            ]:
                                projection[key] = [obj.pk for obj in context[key]]
                        return cookie, projection

                    cookie, projection = db_call(prepare)
                    for width, height in SIZES:
                        for theme in ("light", "dark"):
                            label = f"{state}-{width}-{theme}"
                            context = browser.new_context(
                                viewport={"width": width, "height": height},
                                device_scale_factor=1,
                                color_scheme=theme,
                                reduced_motion="reduce",
                                service_workers="block",
                            )
                            context.add_cookies(
                                [
                                    {
                                        "name": settings.SESSION_COOKIE_NAME,
                                        "value": cookie,
                                        "url": self.live_server_url,
                                    }
                                ]
                            )
                            context.add_init_script(
                                f"localStorage.setItem('phoenixTheme','{theme}');"
                            )
                            page = context.new_page()
                            errors, failed, requests, substituted = [], [], [], []
                            page.on(
                                "pageerror", lambda error, errors=errors: errors.append(str(error))
                            )
                            page.on(
                                "requestfailed",
                                lambda request, failed=failed: failed.append(
                                    {"url": request.url, "failure": request.failure}
                                ),
                            )
                            page.on(
                                "request",
                                lambda request, requests=requests: requests.append(
                                    {
                                        "url": request.url.replace(self.live_server_url, ""),
                                        "method": request.method,
                                    }
                                ),
                            )

                            def network(handler, _request, substituted=substituted):
                                url = handler.request.url
                                if url.startswith(self.live_server_url + "/"):
                                    handler.continue_()
                                elif url.startswith("https://fonts.googleapis.com/"):
                                    substituted.append("Nunito CSS")
                                    handler.fulfill(
                                        content_type="text/css",
                                        body="@font-face{font-family:'Nunito Sans';font-style:normal;font-weight:200 1000;src:url('https://fonts.gstatic.com/step7-nunito.woff2') format('woff2')}",
                                    )
                                elif url == "https://fonts.gstatic.com/step7-nunito.woff2":
                                    handler.fulfill(content_type="font/woff2", body=NUNITO)
                                elif url.startswith("https://unicons.iconscout.com/"):
                                    substituted.append("Unused Unicons CSS")
                                    handler.fulfill(
                                        content_type="text/css",
                                        body="/* External test substitution: no Unicons used on these screens. */",
                                    )
                                elif url.startswith("https://unpkg.com/@turf/"):
                                    substituted.append("Unused Turf script")
                                    handler.fulfill(
                                        content_type="application/javascript",
                                        body="/* No maps in this evidence matrix. */",
                                    )
                                else:
                                    handler.abort()

                            page.route("**/*", network)
                            result = {
                                "state": state,
                                "width": width,
                                "height": height,
                                "theme": theme,
                                "projection": projection,
                            }
                            try:
                                response = page.goto(
                                    self.live_server_url + reverse(route), wait_until="networkidle"
                                )
                                self.assertEqual(response.status, 200)
                                page.evaluate("document.fonts.ready")
                                metrics = page.evaluate("""()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth,
                                  marker:document.body.classList.contains('mm-services-dashboard-page'),font:getComputedStyle(document.querySelector('.mm-services-dashboard')||document.body).fontFamily,
                                  newAssets:[...document.querySelectorAll('link[href],script[src]')].map(e=>e.href||e.src).filter(u=>u.includes('services-dashboard.')),
                                  mainLinks:[...document.querySelectorAll('.content a[href]')].map(a=>({href:a.getAttribute('href'),text:a.textContent.trim()})),
                                  forms:[...document.querySelectorAll('.content form,.onboarding-welcome-modal form,.onboarding-guide-panel form')].map(f=>({action:f.getAttribute('action'),method:f.method,fields:[...f.querySelectorAll('input[name]')].filter(i=>i.name!=='csrfmiddlewaretoken').map(i=>({name:i.name,value:i.value}))}))})""")
                                result["metrics"] = metrics
                                if stage == "after":
                                    target = route == "agent_dashboard" and not logistics
                                    self.assertEqual(metrics["marker"], target)
                                    self.assertEqual(len(metrics["newAssets"]), 2 if target else 0)
                                    if target:
                                        self.assertIn("Manrope", metrics["font"])
                                page.evaluate(AXE)
                                result["axe"] = page.evaluate(
                                    """async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),incomplete:r.incomplete.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))};}"""
                                )
                                if stage == "after":
                                    prior = baseline[state, width, theme]
                                    self.assertEqual(projection, prior["projection"])
                                    self.assertEqual(metrics["forms"], prior["metrics"]["forms"])
                                    previous_nodes = {
                                        axe_node_key(v, n)
                                        for v in prior["axe"]["violations"]
                                        for n in v["nodes"]
                                    }
                                    current_nodes = {
                                        axe_node_key(v, n)
                                        for v in result["axe"]["violations"]
                                        for n in v["nodes"]
                                    }
                                    self.assertFalse(
                                        current_nodes - previous_nodes,
                                        current_nodes - previous_nodes,
                                    )
                                    if target:
                                        result["contentAxe"] = page.evaluate(
                                            """async()=>{const r=await axe.run('.mm-services-dashboard',{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),incomplete:r.incomplete.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))};}"""
                                        )
                                        self.assertFalse(result["contentAxe"]["violations"])
                                    else:
                                        self.assertEqual(
                                            metrics["mainLinks"], prior["metrics"]["mainLinks"]
                                        )
                                        self.assertFalse(
                                            [r for r in requests if "manrope" in r["url"].lower()]
                                        )
                                    result["baselineComparison"] = (
                                        "projections/forms/accessibility preserved"
                                    )
                                for full in (False, True):
                                    page.screenshot(
                                        path=str(
                                            out / f"{label}-{'full' if full else 'viewport'}.png"
                                        ),
                                        full_page=full,
                                        animations="disabled",
                                    )
                                    if stage == "after" and not target:
                                        name = f"{label}-{'full' if full else 'viewport'}.png"
                                        with (
                                            Image.open(out / name) as current,
                                            Image.open(root / "evidence/before" / name) as previous,
                                        ):
                                            self.assertEqual(current.size, previous.size)
                                            self.assertIsNone(
                                                ImageChops.difference(
                                                    current.convert("RGB"), previous.convert("RGB")
                                                ).getbbox(),
                                                name,
                                            )
                                        result["unchangedPixels"] = True
                                self.assertLessEqual(metrics["documentWidth"], width + 1)
                                self.assertFalse(errors, errors)
                                self.assertFalse(failed, failed)
                                result["pass"] = True
                            except Exception as error:
                                result.update({"pass": False, "error": str(error)})
                            result.update(
                                browserErrors=errors,
                                failedRequests=failed,
                                requests=requests,
                                substitutedExternalAssets=substituted,
                            )
                            cases.append(result)
                            context.close()
                            print(
                                f"{stage} {'PASS' if result['pass'] else 'FAIL'} {label}",
                                flush=True,
                            )
                output = {
                    "stage": stage,
                    "browser": browser.version,
                    "cases": cases,
                    "passed": sum(c["pass"] for c in cases),
                    "total": len(cases),
                }
                (out / "results.json").write_text(json.dumps(output, indent=2) + "\n")
            finally:
                browser.close()
        self.assertTrue(all(c["pass"] for c in cases), [c for c in cases if not c["pass"]])
