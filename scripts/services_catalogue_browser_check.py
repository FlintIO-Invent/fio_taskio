"""Real catalogue review and native-form checks on owned resources only."""

import argparse
import json
import os
import time

from playwright.sync_api import sync_playwright
from services_clients_browser_check import axe, health, login
from ui_preview.core import load_session, verify_database, verify_source

SCOPE = ".mm-services-catalogue"
METRICS = """() => {const root=document.querySelector('.mm-services-catalogue')||document.querySelector('.content');const controls=[...root.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,summary')].filter(e=>e.checkVisibility({checkVisibilityCSS:true})).map(e=>{const hit=e.type==='checkbox'?(e.closest('label')||e):e;const r=hit.getBoundingClientRect();return {name:e.getAttribute('aria-label')||e.name||e.textContent.trim().slice(0,80),width:r.width,height:r.height};});return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,h1:root.querySelectorAll('h1').length,font:getComputedStyle(root).fontFamily,smallTargets:controls.filter(e=>e.width<43.9||e.height<43.9),scope:root.matches('.mm-services-catalogue')};}"""


def capture(session_path, side):
    root, state = load_session(session_path)
    if state["route"] != "/crm/settings/services/":
        raise RuntimeError("Catalogue route required.")
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    origin, identity = health(state, side)
    out = root / side / "evidence" / ("catalogue-" + str(time.time_ns()))
    out.mkdir(parents=True)
    fixtures = identity["fixtures"]["catalogue_review"]
    sample = fixtures["contexts"]["populated"]
    paths = [
        ("list", "/crm/settings/services/"),
        ("service-create", "/crm/settings/services/create/"),
        ("category-create", "/crm/settings/service-categories/create/"),
        ("service-edit", f"/crm/settings/services/{sample['service_ids'][0]}/edit/"),
        ("category-edit", f"/crm/settings/service-categories/{sample['category_ids'][0]}/edit/"),
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
        login(page, origin, state, "catalogue.owner@preview.test", allow_restricted=True)
        for width, height in [(1440, 1000), (768, 1024), (390, 844), (320, 844)]:
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
                    if width == 1440 and theme == "light" and name == "list":
                        result["full_page_axe"] = axe(page)
                    if (width, theme, name) in [
                        (1440, "light", "list"),
                        (390, "dark", "list"),
                        (1440, "light", "service-create"),
                        (390, "dark", "service-create"),
                    ]:
                        page.screenshot(
                            path=str(out / (name + "-" + str(width) + "-" + theme + ".png")),
                            full_page=True,
                            animations="disabled",
                        )
                    cases.append(result)
                    (out / "cases-progress.json").write_text(json.dumps(cases, indent=2) + "\n")
        scenarios = []
        for scenario in ["empty", "long", "archived", "no-booking", "readonly"]:
            login(
                page,
                origin,
                state,
                "catalogue." + scenario + ".owner@preview.test",
                allow_restricted=True,
            )
            page.set_viewport_size({"width": 390, "height": 844})
            response = page.goto(origin + "/crm/settings/services/", wait_until="networkidle")
            scenarios.append(
                {
                    "scenario": scenario,
                    "status": response.status,
                    "url": page.url,
                    "overflow": page.evaluate("document.documentElement.scrollWidth>innerWidth"),
                    "mutations": page.locator(SCOPE + " form[method=post]").count(),
                }
            )
        roles = []
        for scenario in ["populated", "logistics"]:
            for role in ["owner", "admin", "staff", "accountant", "viewer"]:
                email = (
                    "catalogue."
                    + ("" if scenario == "populated" else "logistics.")
                    + role
                    + "@preview.test"
                )
                login(page, origin, state, email, allow_restricted=True)
                response = page.goto(origin + "/crm/settings/services/", wait_until="networkidle")
                roles.append(
                    {
                        "scenario": scenario,
                        "role": role,
                        "status": response.status,
                        "url": page.url,
                        "new_scope": page.locator(SCOPE).count(),
                        "new_asset": page.locator('link[href*="services-catalogue.css"]').count(),
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
        if (
            r["scenario"] == "populated"
            and r["role"] in ["staff", "accountant", "viewer"]
            and r["new_scope"]
        ):
            failures.append("Role leaked")
    if side == "after" and any(s["overflow"] for s in scenarios):
        failures.append("Scenario overflow")
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

    from apps.businesses.models import UserOnboardingState
    from apps.businesses.test_service_allowances import ServicesFixture
    from apps.crm.models import BusinessService
    from apps.crm.test_services_dashboard_ui import assert_disposable

    class CatalogueFormBrowserChecks(ServicesFixture, StaticLiveServerTestCase):
        port = 8768

        def setUp(self):
            assert_disposable()
            super().setUp()
            UserOnboardingState.objects.create(
                business=self.business,
                user=self.owner,
                completed_welcome=True,
                selected_journey="setup_business",
            )

        def test_native_invalid_create_theme_draft_save_and_archive(self):
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
                page.goto(self.live_server_url + reverse("business_service_create"))
                page.locator("[name=name]").fill("Browser catalogue service")
                page.locator("[name=unit_price]").fill("-4")
                page.get_by_role("button", name="Create service", exact=True).click()
                page.wait_for_load_state("networkidle")
                self.assertEqual(
                    page.locator("[name=name]").input_value(), "Browser catalogue service"
                )
                self.assertIn(
                    "Price cannot be negative.", page.locator(".mm-services-catalogue").inner_text()
                )
                page.locator("[name=unit_price]").fill("88.75")
                page.locator("[name=new_category_name]").fill("Browser category")
                page.locator('label[for="themeControlToggle"]:visible').first.click()
                self.assertEqual(
                    page.locator("[name=name]").input_value(), "Browser catalogue service"
                )
                self.assertEqual(
                    page.locator("[name=new_category_name]").input_value(), "Browser category"
                )
                page.get_by_role("button", name="Create service", exact=True).click()
                page.wait_for_load_state("networkidle")
                page.get_by_role(
                    "button", name="Archive Browser catalogue service", exact=True
                ).click()
                page.wait_for_load_state("networkidle")
                browser.close()
            service = BusinessService.objects.get(
                business=self.business, name="Browser catalogue service"
            )
            self.assertEqual(str(service.unit_price), "88.75")
            self.assertEqual(service.category.name, "Browser category")
            self.assertFalse(service.is_active)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--side", choices=["before", "after"], required=True)
    args = parser.parse_args()
    capture(args.session, args.side)
