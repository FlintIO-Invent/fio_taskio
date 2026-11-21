"""Real data_import review and native-form checks on owned resources only."""

import argparse
import json
import os
import time

from playwright.sync_api import sync_playwright
from services_clients_browser_check import axe, health, login
from ui_preview.core import load_session, verify_database, verify_source

SCOPE = ".mm-services-data-import"
METRICS = """() => {const root=document.querySelector('.mm-services-data-import')||document.querySelector('.content');const controls=[...root.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,summary')].filter(e=>e.checkVisibility({checkVisibilityCSS:true})).map(e=>{const hit=e.type==='checkbox'?(e.closest('label')||e):e;const r=hit.getBoundingClientRect();return {name:e.getAttribute('aria-label')||e.name||e.textContent.trim().slice(0,80),width:r.width,height:r.height};});return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,h1:root.querySelectorAll('h1').length,font:getComputedStyle(root).fontFamily,smallTargets:controls.filter(e=>e.width<43.9||e.height<43.9),scope:root.matches('.mm-services-data-import')};}"""


def capture(session_path, side, roles_only=False):
    root, state = load_session(session_path)
    if state["route"] != "/crm/staff/data-import/":
        raise RuntimeError("DataImport route required.")
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    origin, identity = health(state, side)
    out = root / side / "evidence" / ("data_import-" + str(time.time_ns()))
    out.mkdir(parents=True)
    fixtures = identity["fixtures"]["data_import_review"]
    sample = fixtures["contexts"]["populated"]
    jobs = sample["jobs"]
    paths = [
        ("hub", "/crm/staff/data-import/"),
        ("lead-upload", "/crm/staff/data-import/leads/"),
        ("service-upload", "/crm/settings/services/import/"),
        ("lead-preview", f"/crm/staff/data-import/leads/{jobs['leads-ready']}/preview/"),
        ("service-preview", f"/crm/settings/services/import/{jobs['services-ready']}/preview/"),
        ("history", "/crm/staff/data-import/history/"),
        ("lead-result", f"/crm/staff/data-import/leads/{jobs['leads-done']}/result/"),
        ("service-result", f"/crm/settings/services/import/{jobs['services-done']}/result/"),
    ]
    cases = []
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
        context = browser.new_context(reduced_motion="reduce", service_workers="block")
        context.route(
            "**/*", lambda r: r.continue_() if r.request.url.startswith(origin + "/") else r.abort()
        )
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        login(page, origin, state, "imports.owner@preview.test", allow_restricted=True)
        for width, height in [] if roles_only else [(1440, 1000), (768, 1024), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ["light", "dark"]:
                page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                for name, path in paths:
                    response = page.goto(origin + path, wait_until="networkidle")
                    page.evaluate("document.fonts.ready")
                    metrics = page.evaluate(METRICS)
                    result = {
                        "screen": name,
                        "width": width,
                        "theme": theme,
                        "status": response.status,
                        "metrics": metrics,
                        "axe": axe(page, SCOPE) if metrics["scope"] else axe(page, ".content"),
                    }
                    if width == 1440 and theme == "light" and name == "hub":
                        result["full_page_axe"] = axe(page)
                    if (width, theme, name) in [
                        (1440, "light", "hub"),
                        (390, "dark", "hub"),
                        (1440, "light", "service-upload"),
                        (390, "dark", "service-upload"),
                    ]:
                        page.screenshot(
                            path=str(out / (name + "-" + str(width) + "-" + theme + ".png")),
                            full_page=True,
                            animations="disabled",
                        )
                    cases.append(result)
                    (out / "cases-progress.json").write_text(json.dumps(cases, indent=2) + "\n")
        scenarios = []
        if not roles_only:
            extra = [
                ("lead-blocked", f"/crm/staff/data-import/leads/{jobs['leads-blocked']}/preview/"),
                (
                    "service-blocked",
                    f"/crm/settings/services/import/{jobs['services-blocked']}/preview/",
                ),
                ("lead-expired", f"/crm/staff/data-import/leads/{jobs['leads-expired']}/preview/"),
                (
                    "service-expired",
                    f"/crm/settings/services/import/{jobs['services-expired']}/preview/",
                ),
                ("history-detail", f"/crm/staff/data-import/history/{jobs['services-done']}/"),
                ("clients-preserved", "/crm/staff/data-import/clients/"),
            ]
            page.set_viewport_size({"width": 390, "height": 844})
            for name, path in extra:
                response = page.goto(origin + path, wait_until="networkidle")
                scope = (
                    SCOPE
                    if page.locator(SCOPE).count()
                    else ".mm-services-clients"
                    if page.locator(".mm-services-clients").count()
                    else ".content"
                )
                scenarios.append(
                    {
                        "scenario": name,
                        "status": response.status,
                        "url": page.url,
                        "overflow": page.evaluate(
                            "document.documentElement.scrollWidth>innerWidth"
                        ),
                        "axe": axe(page, scope),
                        "new_asset": page.locator('link[href*="services-data-import.css"]').count(),
                    }
                )
            page.set_viewport_size({"width": 320, "height": 844})
            for name, path in paths[:2]:
                page.goto(origin + path, wait_until="networkidle")
                scenarios.append(
                    {
                        "scenario": name + "-320",
                        "status": 200,
                        "url": page.url,
                        "overflow": page.evaluate(
                            "document.documentElement.scrollWidth>innerWidth"
                        ),
                    }
                )
            for scenario in ["empty", "long", "readonly"]:
                login(
                    page,
                    origin,
                    state,
                    "imports." + scenario + ".owner@preview.test",
                    allow_restricted=True,
                )
                response = page.goto(
                    origin + "/crm/staff/data-import/history/", wait_until="networkidle"
                )
                scenarios.append(
                    {
                        "scenario": scenario + "-history",
                        "status": response.status,
                        "url": page.url,
                        "overflow": page.evaluate(
                            "document.documentElement.scrollWidth>innerWidth"
                        ),
                    }
                )
        roles = []
        for scenario in ["populated", "logistics"]:
            for role in ["owner", "admin", "staff", "accountant", "viewer"]:
                email = (
                    "imports."
                    + ("" if scenario == "populated" else "logistics.")
                    + role
                    + "@preview.test"
                )
                login(page, origin, state, email, allow_restricted=True)
                response = page.goto(origin + "/crm/staff/data-import/", wait_until="networkidle")
                roles.append(
                    {
                        "scenario": scenario,
                        "role": role,
                        "status": response.status,
                        "url": page.url,
                        "new_scope": page.locator(SCOPE).count(),
                        "capabilities": {
                            name: page.locator(SCOPE + ' a[href="' + path + '"]').count()
                            for name, path in [
                                ("clients", "/crm/staff/data-import/clients/"),
                                ("leads", "/crm/staff/data-import/leads/"),
                                ("services", "/crm/settings/services/import/"),
                                ("history", "/crm/staff/data-import/history/"),
                            ]
                        },
                        "new_asset": page.locator('link[href*="services-data-import.css"]').count(),
                    }
                )
        browser.close()
    report = {
        "side": side,
        "source_sha256": identity["source_sha256"],
        "cases": cases,
        "scenarios": scenarios,
        "roles": roles,
        "page_errors": errors,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    failures = []
    for case in cases:
        if case["status"] != 200:
            failures.append("HTTP " + case["screen"])
        if side == "after":
            if case["metrics"]["documentWidth"] > case["width"]:
                failures.append("Overflow " + str(case["width"]) + " " + case["screen"])
            if case["metrics"]["h1"] != 1:
                failures.append("Heading " + case["screen"])
            if case["metrics"]["smallTargets"]:
                failures.append("Targets " + case["screen"] + " " + str(case["width"]))
            if case["axe"]["violations"]:
                failures.append("Accessibility " + case["screen"] + " " + case["theme"])
    for r in roles:
        if r["scenario"] == "logistics" and (r["new_scope"] or r["new_asset"]):
            failures.append("Logistics changed")
        if r["scenario"] == "populated" and r["role"] == "viewer" and r["new_scope"]:
            failures.append("Role leaked")
    if side == "after":
        for r in roles:
            if r["scenario"] == "populated" and r["role"] != "viewer":
                expected = {
                    "clients": 1,
                    "leads": int(r["role"] in ["owner", "admin", "staff"]),
                    "services": int(r["role"] in ["owner", "admin"]),
                    "history": int(r["role"] in ["owner", "admin"]),
                }
                if r["capabilities"] != expected:
                    failures.append("Import role flags " + r["role"])
    if side == "after" and any(s["overflow"] for s in scenarios):
        failures.append("Scenario overflow")
    if side == "after":
        for case in scenarios:
            if case.get("axe", {}).get("violations") and case["scenario"] != "clients-preserved":
                failures.append("State accessibility " + case["scenario"])
            if case["scenario"] == "clients-preserved" and case.get("new_asset"):
                failures.append("Client assets changed")
    if errors:
        failures.append("JavaScript errors")
    print(
        json.dumps(
            {"evidence": str(out), "cases": len(cases), "failures": sorted(set(failures))}, indent=2
        )
    )
    if failures:
        raise SystemExit(1)


if __name__ != "__main__":
    from django.contrib.staticfiles.testing import StaticLiveServerTestCase
    from django.urls import reverse

    from apps.appointments.models import Appointment
    from apps.billings.models import Invoice
    from apps.businesses.models import UserOnboardingState
    from apps.businesses.test_service_allowances import ServicesFixture
    from apps.crm.models import BusinessService, Client, Lead
    from apps.crm.test_services_dashboard_ui import assert_disposable

    class DataImportFormBrowserChecks(ServicesFixture, StaticLiveServerTestCase):
        port = 8768

        def setUp(self):
            assert_disposable()
            super().setUp()
            self.service.external_code = "NATIVE-SAVED"
            self.service.save(update_fields=["external_code"])
            UserOnboardingState.objects.create(
                business=self.business,
                user=self.owner,
                completed_welcome=True,
                selected_journey="setup_business",
            )

        def test_native_upload_preview_block_confirm_history_and_theme_file_draft(self):
            initial = (
                Client.objects.count(),
                Appointment.objects.count(),
                Invoice.objects.count(),
                Lead.objects.count(),
            )
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
                context = browser.new_context(service_workers="block")
                context.route(
                    "**/*",
                    lambda r: (
                        r.continue_()
                        if r.request.url.startswith(self.live_server_url + "/")
                        else r.abort()
                    ),
                )
                page = context.new_page()
                page.goto(self.live_server_url + "/accounts/login/")
                page.locator("[name=email]").fill(self.owner.email)
                page.locator("[name=password]").fill("test-only-password")
                page.get_by_role("button", name="Sign In", exact=True).click()
                page.wait_for_load_state("networkidle")
                page.goto(self.live_server_url + reverse("lead_import_upload"))
                page.locator("[name=csv_file]").set_input_files(
                    {
                        "name": "browser-leads.csv",
                        "mimeType": "text/csv",
                        "buffer": b"first_name,email,lead_type\nBrowser import,browser@import.test,REQUEST\n",
                    }
                )
                page.get_by_role("button", name="Validate and preview", exact=True).click()
                page.wait_for_load_state("networkidle")
                page.get_by_role("button", name="Confirm Lead Import", exact=True).click()
                page.wait_for_load_state("networkidle")
                self.assertIn(
                    "Import complete", page.locator(".mm-services-data-import").inner_text()
                )
                page.reload()
                page.goto(self.live_server_url + reverse("lead_import_upload"))
                page.locator("[name=csv_file]").set_input_files(
                    {
                        "name": "blocked.csv",
                        "mimeType": "text/csv",
                        "buffer": b"first_name,email\nBad,not-an-email\n",
                    }
                )
                page.get_by_role("button", name="Validate and preview", exact=True).click()
                page.wait_for_load_state("networkidle")
                self.assertEqual(
                    page.get_by_role("button", name="Confirm Lead Import", exact=True).count(), 0
                )
                page.goto(self.live_server_url + reverse("business_service_import"))
                page.locator("details summary").first.click()
                self.assertTrue(page.locator("#sample-csv-text").is_visible())
                page.locator("[name=csv_file]").set_input_files(
                    {
                        "name": "browser-services.csv",
                        "mimeType": "text/csv",
                        "buffer": b"external_code,unit_price,category\nNATIVE-SAVED,79.50,Native import category\n",
                    }
                )
                page.locator('label[for="themeControlToggle"]:visible').first.click()
                self.assertEqual(
                    page.locator("[name=csv_file]").evaluate("(e)=>e.files[0].name"),
                    "browser-services.csv",
                )
                page.get_by_role("button", name="Validate and preview", exact=True).click()
                page.wait_for_load_state("networkidle")
                self.assertIn("79.50", page.locator(".mm-services-data-import").inner_text())
                page.get_by_role("button", name="Confirm Service Import", exact=True).click()
                page.wait_for_load_state("networkidle")
                self.assertIn(
                    "Import complete", page.locator(".mm-services-data-import").inner_text()
                )
                page.get_by_role("link", name="View Import History", exact=True).click()
                page.wait_for_load_state("networkidle")
                self.assertNotIn(
                    "browser@import.test", page.locator(".mm-services-data-import").inner_text()
                )
                browser.close()
            service = BusinessService.objects.get(pk=self.service.pk)
            self.assertEqual(str(service.unit_price), "79.50")
            self.assertEqual(service.category.name, "Native import category")
            self.assertEqual(Lead.objects.count(), initial[3] + 1)
            self.assertEqual(
                (Client.objects.count(), Appointment.objects.count(), Invoice.objects.count()),
                initial[:3],
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--side", choices=["before", "after"], required=True)
    parser.add_argument("--roles-only", action="store_true")
    args = parser.parse_args()
    capture(args.session, args.side, args.roles_only)
