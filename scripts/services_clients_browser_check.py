"""Real Django Clients review on verified owned preview sessions only."""

import argparse
import json
import os
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import sync_playwright
from ui_preview.core import REPO, load_session, verify_database, verify_source

SIZES = [(1440, 900), (768, 1024), (390, 844), (320, 844)]
AXE_PATH = REPO / "ui-lab/services-dashboard/tools/node_modules/axe-core/axe.min.js"
METRICS = """() => {
 const root=document.querySelector('.mm-services-clients')||document.querySelector('.content')||document.body;
 const visible=e=>e.checkVisibility({checkVisibilityCSS:true,checkOpacity:true})&&!e.closest('.modal:not(.show)');
 const controls=[...root.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,summary')].filter(visible).map(e=>{
  const hit=e.type==='checkbox'?(e.closest('label')||e):e;const r=hit.getBoundingClientRect();
  return {label:e.getAttribute('aria-label')||e.name||e.textContent.trim().slice(0,80),width:r.width,height:r.height};
 });
 return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,theme:document.documentElement.dataset.bsTheme||'light',
  clientScope:!!document.querySelector('.mm-services-clients'),font:getComputedStyle(root).fontFamily,
  targets:controls.filter(c=>c.width<43.9||c.height<43.9),
  fields:[...root.querySelectorAll('form [name]:not([type=hidden])')].map(e=>e.name),
  dataRows:root.querySelectorAll('[data-client-id]').length,ids:[...root.querySelectorAll('[data-client-id]')].map(e=>e.dataset.clientId)};
}"""


def health(state, side):
    origin = f"http://127.0.0.1:{state[side]['http_port']}"
    with build_opener(ProxyHandler({})).open(origin + "/_preview/health", timeout=5) as response:
        value = json.load(response)
    if (
        value["session"] != state["id"]
        or value["side"] != side
        or value["database"] != state[side]["database"]
    ):
        raise RuntimeError("Clients browser listener identity differs.")
    return origin, value


def login(page, origin, state, email, allow_restricted=False):
    page.goto(origin + "/accounts/logout/", wait_until="networkidle")
    page.goto(origin + "/accounts/login/", wait_until="networkidle")
    page.locator("input[name=email]").fill(email)
    page.locator("input[name=password]").fill(state["password"])
    with page.expect_navigation(wait_until="networkidle"):
        page.get_by_role("button", name="Sign In", exact=True).click()
    if not allow_restricted and "/crm/agent/dashboard/" not in page.url:
        raise AssertionError("Real Django login did not reach the workspace.")


def axe(page, scope=None):
    page.evaluate(AXE_PATH.read_text())
    return page.evaluate(
        """async scope=>{const r=await axe.run(scope||document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {passes:r.passes.length,violations:r.violations,incomplete:r.incomplete};}""",
        scope,
    )


def capture(browser, origin, state, side, out, fixtures):
    context = browser.new_context(reduced_motion="reduce", service_workers="block")
    context.route(
        "**/*",
        lambda route: (
            route.continue_() if route.request.url.startswith(origin + "/") else route.abort()
        ),
    )
    page = context.new_page()
    errors, failures = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("requestfailed", lambda r: failures.append({"url": r.url, "failure": r.failure}))
    review = fixtures["clients_review"]
    target = review["contexts"]["populated"]["client_ids"][0]
    paths = [
        ("list", "/crm/staff/clients/"),
        ("profile", f"/crm/staff/clients/{target}/"),
        ("create", "/crm/staff/clients/create/"),
        ("edit", f"/crm/staff/clients/{target}/edit/"),
        ("upload", "/crm/staff/data-import/clients/"),
        ("appointment-draft", "/appointments/create/"),
        ("request-draft", "/crm/staff/leads/create/"),
    ]
    login(page, origin, state, "clients.owner@preview.test")
    cases = []
    for width, height in SIZES:
        page.set_viewport_size({"width": width, "height": height})
        for theme in ("light", "dark"):
            page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
            for label, path in paths:
                response = page.goto(origin + path, wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                metrics = page.evaluate(METRICS)
                result = {
                    "screen": label,
                    "width": width,
                    "theme": theme,
                    "status": response.status,
                    "metrics": metrics,
                    "axe": axe(page) if response.status < 400 else None,
                    "content_axe": axe(page, ".mm-services-clients")
                    if metrics["clientScope"] and response.status < 400
                    else None,
                }
                name = f"{label}-{width}-{theme}"
                for suffix, full in [("viewport", False), ("full", True)]:
                    page.screenshot(
                        path=str(out / f"{name}-{suffix}.png"),
                        full_page=full,
                        animations="disabled",
                    )
                cases.append(result)
                (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    # Shared templates stay on Logistics' existing presentation for every role.
    logistics = []
    for role in ("owner", "staff", "accountant", "viewer"):
        login(page, origin, state, f"clients.logistics.{role}@preview.test", allow_restricted=True)
        customer = review["contexts"]["logistics"]["client_ids"][0]
        for path in ["/crm/staff/clients/", f"/crm/staff/clients/{customer}/"]:
            response = page.goto(origin + path, wait_until="networkidle")
            logistics.append(
                {
                    "role": role,
                    "path": path,
                    "status": response.status,
                    "new_assets": page.locator(
                        '[href*="services-clients.css"],[src*="services-clients.js"]'
                    ).count(),
                    "content": page.locator(".content").inner_text()
                    if response.status < 400
                    else f"HTTP {response.status}: baseline page unavailable",
                }
            )
    context.close()
    return {
        "side": side,
        "source": json.loads((Path(state[side]["source"]) / "source.json").read_text())["sha256"],
        "fixture_inventory": fixtures["clients_review"]["client_inventory_sha256"],
        "cases": cases,
        "logistics": logistics,
        "page_errors": errors,
        "failed_requests": failures,
    }


def journeys(browser, origin, state, side, out, fixtures):
    from urllib.parse import urlencode
    from uuid import uuid4

    from playwright.sync_api import expect

    results = []
    original = fixtures["clients_review"]["contexts"]["populated"]["client_ids"][0]
    for width, height in SIZES:
        for theme in (
            [os.environ["CLIENTS_REVIEW_THEME"]]
            if os.environ.get("CLIENTS_REVIEW_THEME")
            else ["light", "dark"]
        ):
            context = browser.new_context(
                viewport={"width": width, "height": height},
                reduced_motion="reduce",
                service_workers="block",
            )
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith(origin + "/")
                    else route.abort()
                ),
            )
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
            token = uuid4().hex[:14]
            result = {
                "width": width,
                "theme": theme,
                "checks": [],
                "created_only_for_validation": token,
            }

            def check(name, passed=True, result=result):
                if not passed:
                    raise AssertionError(name)
                result["checks"].append(name)

            def visit(path, page=page):
                assert path.startswith("/") and not path.startswith("//")
                response = page.goto(origin + path, wait_until="networkidle")
                assert response.status < 400, (path, response.status)
                return response

            try:
                login(page, origin, state, "clients.validation@preview.test")
                page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                visit("/crm/staff/clients/")
                page.locator("[name=q]").fill("Harbour Dental")
                with page.expect_navigation(wait_until="networkidle"):
                    page.locator(".mm-sc-filter [type=submit]").click()
                check("server company search", page.locator("[data-client-id]").count() == 1)
                visit("/crm/staff/clients/?district=COLE_BAY&is_active=false")
                check("combined server filters", page.locator("[data-client-id]").count() == 1)
                visit("/crm/staff/clients/?is_active=0&q=populated.clients.preview.test")
                check("historical inactive alias", page.locator("[data-client-id]").count() == 1)
                visit(
                    "/crm/staff/clients/?"
                    + urlencode({"q": "populated.clients.preview.test", "is_active": "1"})
                )
                check(
                    "historical active alias",
                    "Farah Ali" not in page.locator("#clientsTable").inner_text(),
                )
                visit("/crm/staff/clients/?" + urlencode({"q": "populated.clients.preview.test"}))
                check("ten-row native pagination", page.locator("[data-client-id]").count() == 10)
                page.locator("[data-list-pagination=next]").click()
                check(
                    "next page preserves filtered dataset",
                    page.locator("[data-client-id]").count() == 3,
                )
                page.locator('[data-list-view="*"]').click()
                check(
                    "View all uses existing List.js", page.locator("[data-client-id]").count() == 13
                )
                page.locator(f'[data-client-id="{original}"] input').check()
                expect(page.locator("[data-client-selected-count]")).to_have_text("1 selected")
                page.locator("[data-client-sort]").select_option("company")
                check(
                    "company sort binds existing List.js",
                    "Camille" in page.locator(".mm-sc-record-name").first.inner_text(),
                )
                expect(page.locator("[data-client-selected-count]")).to_have_text("1 selected")
                page.locator("[data-client-sort-direction]").click()
                check(
                    "descending sort",
                    "Alice" in page.locator(".mm-sc-record-name").first.inner_text(),
                )
                page.locator("[data-client-clear-selection]").click()
                check(
                    "clear all selection", page.locator("[data-bulk-select]").is_checked() is False
                )

                visit("/crm/staff/clients/create/")
                page.locator("[data-client-form] [type=submit]").click()
                expect(page.locator("[data-clients-error-summary]")).to_be_visible()
                check(
                    "client error summary focus",
                    page.locator("[data-clients-error-summary]").evaluate(
                        "(e)=>e===document.activeElement"
                    ),
                )
                page.locator("[data-client-form] details").evaluate_all(
                    "(els)=>els.forEach(e=>e.open=true)"
                )
                email = f"{token}@validation.clients.preview.test"
                values = {
                    "client_type": "INDIVIDUAL",
                    "first_name": "Riley",
                    "last_name": token,
                    "company_name": f"Review {token}",
                    "email": email,
                    "phone": "+1721" + str(int(token[:8], 16)).zfill(10),
                    "business_legal_name": f"Legal {token}",
                    "trade_name": f"Trade {token}",
                    "industry": "Hospitality",
                    "business_description": "Preserve the complete client profile.",
                    "website": "https://example.test",
                    "registration_number": token,
                    "job_title": "Coordinator",
                    "department": "Operations",
                    "secondary_email": f"secondary-{email}",
                    "secondary_phone": "+17215550190",
                    "whatsapp_number": "+17215550191",
                    "preferred_language": "English",
                    "preferred_contact_method": "PHONE",
                    "lead_source": "REFERRAL",
                    "client_status": "ACTIVE",
                    "priority": "HIGH",
                    "assigned_to": "",
                    "interested_services": "Studio maintenance",
                    "street_address": "21 Test Street",
                    "country": "Netherlands",
                    "district": "Amsterdam",
                    "postal_code": "1012ab",
                    "message": "Initial context",
                    "communication_notes": "Call for changes",
                    "notes": "Unsaved note " + token,
                    "consent_to_contact": True,
                }
                # Country selection swaps the existing address control without losing the draft.
                page.locator("[name=country]").select_option("Netherlands")
                for name, value in values.items():
                    if name == "country":
                        continue
                    field = page.locator(f'[data-client-form] [name="{name}"]')
                    if name == "consent_to_contact":
                        field.set_checked(value)
                    elif field.evaluate("(e)=>e.tagName") == "SELECT":
                        field.select_option(value)
                    else:
                        field.fill(value)
                check(
                    "Individual retains company requirement",
                    page.locator("[name=company_name]").get_attribute("required") is not None,
                )
                page.locator("[name=email]").fill("invalid")
                # Native submit bypasses progressive validation to exercise the real Django error response.
                with page.expect_navigation(wait_until="networkidle"):
                    page.locator("[data-client-form]").evaluate("(e)=>e.submit()")
                expect(page.locator("[name=email]")).to_have_attribute("aria-invalid", "true")
                expect(page.locator("[name=notes]")).to_have_value(values["notes"])
                check(
                    "server error preserves full draft and focuses summary",
                    page.locator("[data-clients-error-summary]").evaluate(
                        "(e)=>e===document.activeElement"
                    ),
                )
                page.locator("[name=email]").fill(email)
                page.locator('label[for="themeControlToggle"]:visible').click()
                expect(page.locator("[name=notes]")).to_have_value(values["notes"])
                check("existing theme toggle preserves form draft")
                with page.expect_navigation(wait_until="networkidle"):
                    page.locator("[data-client-form] [type=submit]").click()
                check(
                    "creation returns the existing directory",
                    page.url == origin + "/crm/staff/clients/",
                )
                visit("/crm/staff/clients/?" + urlencode({"q": email}))
                check(
                    "created client exists exactly once",
                    page.locator("[data-client-id]").count() == 1,
                )
                profile = page.locator(".mm-sc-record-name").get_attribute("href")
                check(
                    "new client has an actual record URL", profile.startswith("/crm/staff/clients/")
                )
                visit(profile + "edit/")
                for name, value in values.items():
                    field = page.locator(f'[data-client-form] [name="{name}"]')
                    expected = "1012 AB" if name == "postal_code" else value
                    if name == "consent_to_contact":
                        check("stored contact consent", field.is_checked() == value)
                    else:
                        check("stored field " + name, field.input_value() == expected)
                page.locator("#tab-notes summary").click() if not page.locator(
                    "#tab-notes"
                ).evaluate("(e)=>e.open") else None
                page.locator("[name=notes]").fill("Updated note " + token)
                with page.expect_navigation(wait_until="networkidle"):
                    page.locator("[data-client-form] [type=submit]").click()
                check("edit returns same client profile", page.url == origin + profile)
                expect(page.locator(".mm-sc-note").first).to_contain_text("Updated note " + token)
                schedule = page.get_by_role("link", name="Schedule Appointment", exact=True)
                check(
                    "appointment link retains client query",
                    "?client_id=" in schedule.get_attribute("href"),
                )
                with page.expect_navigation(wait_until="networkidle"):
                    schedule.click()
                check(
                    "appointment form preselects client",
                    page.locator("#id_client").input_value() == profile.rstrip("/").split("/")[-1],
                )

                for destination, path in [
                    ("appointment", "/appointments/create/"),
                    ("lead", "/crm/staff/leads/create/"),
                ]:
                    visit(path)
                    page.locator("#id_notes").fill("Parent draft " + token)
                    if destination == "appointment":
                        page.locator("#id_title").fill("Unsaved appointment " + token)
                    page.locator('[data-bs-target="#draftClientModal"]').click()
                    modal = page.locator("#draftClientModal")
                    expect(modal).to_be_visible()
                    modal.get_by_role("button", name="Cancel", exact=True).click()
                    expect(modal).not_to_be_visible()
                    expect(page.locator("#id_notes")).to_have_value("Parent draft " + token)
                    page.locator('[data-bs-target="#draftClientModal"]').click()
                    quick = {
                        "first_name": "   ",
                        "last_name": "Inline",
                        "company_name": f"Inline {token} {destination}",
                        "email": f"{destination}-{email}",
                        "phone": "+1721" + str(int(token[-8:], 16)).zfill(10),
                        "street_address": "12 Inline Street",
                    }
                    for name, value in quick.items():
                        modal.locator(f'[name="new_client-{name}"]').fill(value)
                    with page.expect_response(
                        lambda response: (
                            response.request.method == "POST"
                            and response.url.endswith("/crm/staff/clients/quick-create/")
                        )
                    ) as invalid:
                        modal.locator("[type=submit]").click()
                    check(destination + " inline real validation", invalid.value.status == 400)
                    expect(modal.locator("[data-draft-client-errors]")).to_be_visible()
                    expect(modal.locator('[name="new_client-first_name"]')).to_have_attribute(
                        "aria-invalid", "true"
                    )
                    page.screenshot(
                        path=str(out / f"inline-error-{destination}-{width}-{theme}.png")
                    )
                    modal.locator('[name="new_client-first_name"]').fill("Riley")
                    with page.expect_response(
                        lambda response: (
                            response.request.method == "POST"
                            and response.url.endswith("/crm/staff/clients/quick-create/")
                        )
                    ) as saved:
                        modal.locator("[type=submit]").click()
                    check(destination + " inline actual creation", saved.value.status == 201)
                    created = saved.value.json()["client"]
                    expect(modal).not_to_be_visible()
                    expect(page.locator("#id_notes")).to_have_value("Parent draft " + token)
                    if destination == "appointment":
                        expect(page.locator("#id_title")).to_have_value(
                            "Unsaved appointment " + token
                        )
                        expect(page.locator("#id_client")).to_have_value(str(created["id"]))
                    else:
                        expect(page.locator("#id_email")).to_have_value(quick["email"])
                    check(destination + " parent draft and destination preserved")
                    check(
                        destination + " modal focus return",
                        page.locator('[data-bs-target="#draftClientModal"]').evaluate(
                            "(e)=>e===document.activeElement"
                        ),
                    )

                visit(profile)
                trigger = page.locator("[data-client-archive] [type=submit]")
                trigger.click()
                dialog = page.locator("#clientsArchiveModal")
                expect(dialog).to_be_visible()
                expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_focused()
                page.keyboard.press("Escape")
                expect(dialog).not_to_be_visible()
                check(
                    "archive Escape returns focus",
                    trigger.evaluate("(e)=>e===document.activeElement"),
                )
                trigger.click()
                page.screenshot(path=str(out / f"archive-{width}-{theme}.png"))
                with page.expect_navigation(wait_until="networkidle"):
                    dialog.locator("[data-client-archive-confirm]").click()
                check("archive actual POST return", page.url == origin + "/crm/staff/clients/")
                expect(page.locator(".mm-services-clients")).to_contain_text(
                    "Existing invoices and appointments were kept."
                )
                visit("/crm/staff/clients/?" + urlencode({"q": email, "is_active": "false"}))
                check(
                    "archived record retained and inactive",
                    page.locator("[data-client-id]").count() == 1,
                )

                visit("/crm/staff/data-import/clients/")
                csv_token = uuid4().hex[:14]
                csv_email = f"csv-{csv_token}@validation.clients.preview.test"
                payload = (
                    "first_name,last_name,email,phone,company_name,street_address\n"
                    + f"CSV,{csv_token},{csv_email},,CSV-{csv_token},12 CSV Street\n"
                    + f",,,,Studio-{csv_token},\n"
                    + "Alice,Thompson,alice@populated.clients.preview.test,+1 721 555 0101,Seabreeze Studio,18 Front Street\n"
                )
                page.locator("[name=csv_file]").set_input_files(
                    {
                        "name": f"clients-{token}.csv",
                        "mimeType": "text/csv",
                        "buffer": payload.encode(),
                    }
                )
                with page.expect_navigation(wait_until="networkidle"):
                    page.get_by_role("button", name="Validate and preview", exact=True).click()
                expect(
                    page.get_by_role("button", name="Confirm Client Import", exact=True)
                ).to_be_visible()
                check(
                    "actual stored preview and optional columns",
                    page.locator('[data-services-clients="import-preview"]').count() == 1,
                )
                execute_form = page.locator('form[action$="/execute/"]')
                execute_url = execute_form.get_attribute("action")
                csrf = execute_form.locator("[name=csrfmiddlewaretoken]").input_value()
                page.screenshot(path=str(out / f"csv-preview-{width}-{theme}.png"), full_page=True)
                with page.expect_navigation(wait_until="networkidle"):
                    execute_form.locator("[type=submit]").click()
                expect(page.locator('[data-services-clients="import-result"]')).to_contain_text(
                    "Import complete"
                )
                check("real CSV confirmation result")
                replay = context.request.post(
                    origin + execute_url,
                    form={"csrfmiddlewaretoken": csrf},
                    headers={"Referer": origin + "/"},
                )
                check("CSV confirmation replay accepted without duplicate", replay.status == 200)
                visit("/crm/staff/clients/?" + urlencode({"q": csv_email}))
                check(
                    "CSV retry created one matching client",
                    page.locator("[data-client-id]").count() == 1,
                )
                visit("/crm/staff/data-import/clients/")
                page.locator("[name=csv_file]").set_input_files(
                    {
                        "name": "invalid.csv",
                        "mimeType": "text/csv",
                        "buffer": b"email\ninvalid-email\n",
                    }
                )
                with page.expect_navigation(wait_until="networkidle"):
                    page.get_by_role("button", name="Validate and preview", exact=True).click()
                check(
                    "blocked CSV has no confirm action",
                    page.locator('form[action$="/execute/"]').count() == 0,
                )
                denied = context.request.post(
                    origin + "/crm/staff/clients/quick-create/",
                    form={"new_client-first_name": "No CSRF"},
                )
                check("real CSRF rejection", denied.status == 403)
                foreign_id = fixtures["clients_review"]["contexts"]["long"]["client_ids"][0]
                denied = context.request.get(origin + f"/crm/staff/clients/{foreign_id}/")
                check("real cross-tenant rejection", denied.status == 404)
                page.screenshot(path=str(out / f"csv-blocked-{width}-{theme}.png"), full_page=True)
                result["content_axe"] = axe(page, ".mm-services-clients")
                check("interactive content accessibility", not result["content_axe"]["violations"])
                check(
                    "no reflow after real workflow",
                    page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),
                )
                result["pass"] = True
            except Exception as error:
                result["pass"] = False
                result["exception"] = str(error)
                page.screenshot(path=str(out / f"failure-{width}-{theme}.png"), full_page=True)
            result["page_errors"] = errors
            if errors:
                result["pass"] = False
            results.append(result)
            (out / "journeys.json").write_text(json.dumps(results, indent=2) + "\n")
            context.close()
    return {
        "cases": results,
        "pass": all(result["pass"] for result in results),
        "assertions": sum(len(result["checks"]) for result in results),
    }


def states(browser, origin, state, side, out, fixtures):
    """Read-only role, entitlement, long/empty and expanded-form review."""
    cases = []
    contexts = fixtures["clients_review"]["contexts"]
    combinations = []
    for role in ["owner", "admin", "staff", "accountant", "viewer"]:
        for width, height, theme in [(1440, 900, "light"), (390, 844, "dark")]:
            combinations.append(
                (
                    "role-" + role,
                    f"clients.{role}@preview.test",
                    contexts["populated"]["client_ids"][0],
                    width,
                    height,
                    theme,
                    "profile",
                    role,
                )
            )
    for scenario in [
        "empty",
        "long",
        "partial",
        "no-history",
        "quota",
        "no-invoices",
        "no-appointments",
    ]:
        for width, height in SIZES:
            for theme in ["light", "dark"]:
                customer = (
                    contexts[scenario]["client_ids"][0]
                    if contexts[scenario]["client_ids"]
                    else None
                )
                screen = (
                    "list"
                    if scenario == "empty"
                    else "create"
                    if scenario == "quota"
                    else "profile"
                )
                combinations.append(
                    (
                        scenario,
                        f"clients.{scenario}.owner@preview.test",
                        customer,
                        width,
                        height,
                        theme,
                        screen,
                        "owner",
                    )
                )
    for width, height in SIZES:
        for theme in ["light", "dark"]:
            combinations.append(
                (
                    "all-fields",
                    "clients.owner@preview.test",
                    contexts["populated"]["client_ids"][0],
                    width,
                    height,
                    theme,
                    "edit",
                    "owner",
                )
            )
    for scenario, email, customer, width, height, theme, screen, role in combinations:
        context = browser.new_context(
            viewport={"width": width, "height": height},
            reduced_motion="reduce",
            service_workers="block",
        )
        context.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith(origin + "/") else route.abort()
            ),
        )
        page = context.new_page()
        result = {"scenario": scenario, "width": width, "theme": theme, "checks": {}}
        try:
            login(page, origin, state, email)
            page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
            path = (
                "/crm/staff/clients/"
                if screen == "list"
                else "/crm/staff/clients/create/"
                if screen == "create"
                else f"/crm/staff/clients/{customer}/" + ("edit/" if screen == "edit" else "")
            )
            response = page.goto(origin + path, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            if scenario == "all-fields":
                page.locator("[data-client-form] details").evaluate_all(
                    "(els)=>els.forEach(e=>e.open=true)"
                )
            metrics = page.evaluate(METRICS)
            result["metrics"] = metrics
            result["axe"] = axe(page, ".mm-services-clients")
            checks = result["checks"]
            checks.update(
                status=response.status == 200,
                reflow=metrics["documentWidth"] <= width,
                targets=not metrics["targets"],
                axe=not result["axe"]["violations"],
            )
            if scenario.startswith("role-"):
                checks["archive_role"] = page.locator("[data-client-archive]").count() == int(
                    role in ["owner", "admin"]
                )
                checks["edit_role"] = page.locator(
                    '.mm-sc-header a[href$="/edit/"]'
                ).count() == int(role != "viewer")
                checks["appointment_role"] = page.get_by_role(
                    "link", name="Schedule Appointment", exact=True
                ).count() == int(role in ["owner", "admin", "staff"])
                checks["billing_reads_preserved"] = page.locator("#client-invoices").count() == 1
            if scenario == "no-invoices":
                checks["invoices_absent"] = page.locator("#client-invoices").count() == 0
            if scenario == "no-appointments":
                checks["appointments_absent"] = page.locator("#client-appointments").count() == 0
            if scenario == "no-history":
                checks["honest_empty_history"] = (
                    "No invoices to display" in page.locator(".mm-services-clients").inner_text()
                    and "No upcoming appointments"
                    in page.locator(".mm-services-clients").inner_text()
                )
            if scenario == "quota":
                checks["creation_blocked"] = page.locator("[data-client-form]").count() == 0
            if scenario == "all-fields":
                checks["all_32_fields_visible"] = page.locator(
                    "[data-client-form] [name]:not([type=hidden])"
                ).evaluate_all("(els)=>els.length===32&&els.every(e=>e.checkVisibility())")
                checks["all_32_labels"] = page.locator(
                    "[data-client-form] [name]:not([type=hidden])"
                ).evaluate_all("(els)=>els.every(e=>e.labels.length)")
            page.screenshot(path=str(out / f"{scenario}-{width}-{theme}.png"), full_page=True)
            result["pass"] = all(checks.values())
        except Exception as error:
            result.update(pass_=False, exception=str(error))
            result["pass"] = False
        cases.append(result)
        (out / "states.json").write_text(json.dumps(cases, indent=2) + "\n")
        context.close()
    # Real Phoenix RTL asset path, plus scoped logical layout in each theme.
    for theme in ["light", "dark"]:
        context = browser.new_context(
            viewport={"width": 390, "height": 844}, service_workers="block"
        )
        context.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith(origin + "/") else route.abort()
            ),
        )
        page = context.new_page()
        login(page, origin, state, "clients.owner@preview.test")
        page.evaluate(
            "t=>{localStorage.setItem('phoenixIsRTL','true');localStorage.setItem('phoenixTheme',t)}",
            theme,
        )
        page.goto(origin + "/crm/staff/clients/", wait_until="networkidle")
        good = page.locator("html").get_attribute("dir") == "rtl" and page.evaluate(
            "document.documentElement.scrollWidth<=innerWidth+1"
        )
        page.screenshot(path=str(out / f"rtl-390-{theme}.png"), full_page=True)
        cases.append({"scenario": "rtl", "width": 390, "theme": theme, "pass": good})
        context.close()
    return {"cases": cases, "pass": all(case["pass"] for case in cases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--side", choices=["before", "after"], required=True)
    parser.add_argument("--mode", choices=["capture", "journey", "states"], required=True)
    parser.add_argument("--width", type=int, choices=[1440, 768, 390, 320])
    parser.add_argument("--theme", choices=["light", "dark"])
    args = parser.parse_args()
    if args.width:
        global SIZES
        SIZES = [(width, height) for width, height in SIZES if width == args.width]
    if args.theme:
        os.environ["CLIENTS_REVIEW_THEME"] = args.theme
    root, state = load_session(args.session)
    verify_source(state[args.side]["source"])
    verify_database(root, state, args.side)
    origin, identity = health(state, args.side)
    out = root / args.side / "evidence" / f"clients-{args.mode}-{time.time_ns()}"
    out.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get("PWA_CHROMIUM"))
        operation = {"capture": capture, "journey": journeys, "states": states}[args.mode]
        result = operation(browser, origin, state, args.side, out, identity["fixtures"])
        browser.close()
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "evidence": str(out),
                "side": args.side,
                "mode": args.mode,
                "cases": len(result.get("cases", [])),
                "page_errors": len(result.get("page_errors", [])),
            },
            indent=2,
        )
    )
    if args.mode != "capture" and not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

# Exposed only to the guarded disposable Django runner, never the static review CLI.
if os.environ.get("DJANGO_SETTINGS_MODULE") == "taskio.services_test_settings":
    from concurrent.futures import ThreadPoolExecutor

    from django.contrib.staticfiles.testing import StaticLiveServerTestCase
    from django.urls import reverse
    from playwright.sync_api import expect

    from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
    from apps.businesses.test_service_allowances import ServicesFixture
    from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
    from apps.crm.models import Client
    from apps.crm.test_services_dashboard_ui import assert_disposable

    class LogisticsClientsBrowserChecks(ServicesFixture, StaticLiveServerTestCase):
        port = 8768

        def setUp(self):
            assert_disposable()
            super().setUp()
            self.logistics = Business.objects.create(
                name="Logistics Clients Browser",
                slug="clients-browser-logistics",
                vertical="LOGISTICS",
            )
            plan = ClarivoPlan.objects.get(slug="logistics")
            plan.is_active = True
            plan.save(update_fields=["is_active"])
            BusinessSubscription.objects.create(
                business=self.logistics, plan=plan, status="active", billing_interval="yearly"
            )
            self.logistics_member = BusinessUser.objects.create(
                business=self.logistics, user=self.owner, role="owner"
            )
            self.logistics_client = Client.objects.create(
                business=self.logistics,
                first_name="Logistics",
                last_name="Customer",
                email="logistics-ui@example.test",
                phone="+17215550100",
                company_name="Port Office",
                street_address="12 Port Street",
            )

        def test_all_roles_retain_logistics_rendering_on_four_widths_and_both_themes(self):
            out = (
                Path(os.environ["SERVICES_DASHBOARD_UI_ROOT"])
                / "evidence"
                / f"clients-logistics-browser-{time.time_ns()}"
            )
            out.mkdir(parents=True, exist_ok=False)
            rows = []

            def activate(role):
                self.logistics_member.role = role
                self.logistics_member.save(update_fields=["role"])
                self.client.force_login(self.owner)
                session = self.client.session
                session[CURRENT_BUSINESS_SESSION_KEY] = self.logistics.pk
                session.save()
                cookie = self.client.cookies["sessionid"].value
                from django.db import connections

                connections.close_all()
                return cookie

            with ThreadPoolExecutor(max_workers=1) as database, sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
                for role in ["owner", "admin", "staff", "accountant", "viewer"]:
                    cookie = database.submit(activate, role).result()
                    context = browser.new_context(reduced_motion="reduce", service_workers="block")
                    context.add_cookies(
                        [{"name": "sessionid", "value": cookie, "url": self.live_server_url}]
                    )
                    context.route(
                        "**/*",
                        lambda route: (
                            route.continue_()
                            if route.request.url.startswith(self.live_server_url + "/")
                            else route.abort()
                        ),
                    )
                    page = context.new_page()
                    for width, height in SIZES:
                        page.set_viewport_size({"width": width, "height": height})
                        for theme in ["light", "dark"]:
                            page.goto(
                                self.live_server_url + reverse("staff_client_list"),
                                wait_until="networkidle",
                            )
                            page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                            for screen, path in [
                                ("list", reverse("staff_client_list")),
                                (
                                    "profile",
                                    reverse("staff_client_detail", args=[self.logistics_client.pk]),
                                ),
                            ]:
                                response = page.goto(
                                    self.live_server_url + path, wait_until="networkidle"
                                )
                                self.assertEqual(response.status, 200)
                                expect(page.locator("body")).to_have_class("logistics-workspace")
                                expect(page.locator(".mm-services-clients")).to_have_count(0)
                                expect(
                                    page.locator(
                                        '[href*="services-clients.css"],[src*="services-clients.js"]'
                                    )
                                ).to_have_count(0)
                                if screen == "profile":
                                    expect(
                                        page.get_by_role("button", name="Archive", exact=True)
                                    ).to_have_count(int(role in ["owner", "admin"]))
                                self.assertLessEqual(
                                    page.evaluate("document.documentElement.scrollWidth"), width + 1
                                )
                                page.screenshot(
                                    path=str(out / f"{role}-{screen}-{width}-{theme}.png"),
                                    full_page=True,
                                )
                                rows.append(
                                    {
                                        "role": role,
                                        "screen": screen,
                                        "width": width,
                                        "theme": theme,
                                        "status": response.status,
                                        "services_assets": False,
                                    }
                                )
                    context.close()
                browser.close()
            (out / "results.json").write_text(
                json.dumps({"cases": rows, "pass": True}, indent=2) + "\n"
            )
