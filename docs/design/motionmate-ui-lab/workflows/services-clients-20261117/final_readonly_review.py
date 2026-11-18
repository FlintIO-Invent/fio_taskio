"""Task-owned final read-only delta and equivalent-profile comparison."""

import argparse
import json
import os
import time

from playwright.sync_api import expect, sync_playwright
from services_clients_browser_check import METRICS, SIZES, axe, health, login
from ui_preview.core import load_session, verify_database, verify_source


def forms_delta(browser, root, state, out):
    """Final label-only fix, dynamic locality preservation, and equivalent lists."""
    cases = []
    for side in ("before", "after"):
        origin, identity = health(state, side)
        context = browser.new_context(reduced_motion="reduce", service_workers="block")
        context.route(
            "**/*",
            lambda route, request, origin=origin: (
                route.continue_() if route.request.url.startswith(origin + "/") else route.abort()
            ),
        )
        page = context.new_page()
        login(page, origin, state, "clients.owner@preview.test")
        customer = identity["fixtures"]["clients_review"]["contexts"]["populated"]["client_ids"][0]
        for width, height in SIZES:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ("light", "dark"):
                page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                response = page.goto(
                    origin + "/crm/staff/clients/?q=populated.clients.preview.test",
                    wait_until="networkidle",
                )
                checks = {"status": response.status == 200}
                if side == "after":
                    checks["original_13"] = (
                        "13 clients in this view"
                        in page.locator(".mm-services-clients").inner_text()
                    )
                page.screenshot(
                    path=str(out / f"{side}-directory-{width}-{theme}.png"), full_page=True
                )
                cases.append(
                    dict(
                        side=side,
                        screen="directory",
                        width=width,
                        theme=theme,
                        checks=checks,
                        **{"pass": all(checks.values())},
                    )
                )
                if side == "before":
                    continue
                for mode, path in [
                    ("create", "/crm/staff/clients/create/"),
                    ("edit", f"/crm/staff/clients/{customer}/edit/"),
                ]:
                    response = page.goto(origin + path, wait_until="networkidle")
                    page.evaluate("document.fonts.ready")
                    label = page.locator("label[for=id_postal_code]")
                    checks = {
                        "status": response.status == 200,
                        "optional_once_sint_maarten": label.inner_text().lower().count("optional")
                        == 1,
                        "fields_32": page.locator(
                            "[data-client-form] [name]:not([type=hidden])"
                        ).count()
                        == 32,
                    }
                    country = page.locator("[name=country]")

                    def set_country(value, country=country):
                        if country.evaluate("e=>e.tagName") == "SELECT":
                            country.select_option(label=value)
                        else:
                            country.fill(value)
                            country.dispatch_event("change")

                    set_country("Netherlands")
                    page.locator("[name=district]").fill("Amsterdam")
                    checks["optional_once_netherlands"] = (
                        label.inner_text().lower().count("optional") == 1
                    )
                    set_country("Sint Maarten")
                    checks["locality_value_retained"] = (
                        page.locator("[name=district]").input_value() == "Amsterdam"
                    )
                    metrics = page.evaluate(METRICS)
                    result = axe(page, ".mm-services-clients")
                    checks.update(
                        reflow=metrics["documentWidth"] <= width,
                        targets=not metrics["targets"],
                        axe=not result["violations"],
                    )
                    page.screenshot(
                        path=str(out / f"after-{mode}-{width}-{theme}.png"), full_page=True
                    )
                    cases.append(
                        dict(
                            side=side,
                            screen=mode,
                            width=width,
                            theme=theme,
                            checks=checks,
                            metrics=metrics,
                            axe=result,
                            **{"pass": all(checks.values())},
                        )
                    )
        context.close()
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contacts-only", action="store_true")
    parser.add_argument("--forms-only", action="store_true")
    args = parser.parse_args()
    root, state = load_session("/tmp/motionmate-preview-session-p29z5cgt")
    for side in ("before", "after"):
        verify_source(state[side]["source"])
        verify_database(root, state, side)
    out = root / "after/evidence" / f"clients-final-readonly-{time.time_ns()}"
    out.mkdir(exist_ok=False)
    cases = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ["PWA_CHROMIUM"])
        if args.forms_only:
            cases = forms_delta(browser, root, state, out)
        for side in ["after"] if args.contacts_only else ["before", "after"]:
            if args.forms_only:
                break
            origin, identity = health(state, side)
            fixtures = identity["fixtures"]
            # Same unassigned, no-history fixture permits an actual visual comparison;
            # the assigned-staff BEFORE fixture has an existing HTTP 500.
            for scenario in (
                ["contacts"]
                if args.contacts_only
                else ["no-history", "contacts", "grace", "restricted", "locked"]
            ):
                email = (
                    "clients.no-history.owner@preview.test"
                    if scenario == "no-history"
                    else "clients.owner@preview.test"
                    if scenario == "contacts"
                    else f"{scenario}.owner@preview.test"
                )
                if scenario in ("contacts", "no-history"):
                    key = "populated" if scenario == "contacts" else scenario
                    customer = fixtures["clients_review"]["contexts"][key]["client_ids"][0]
                else:
                    customer = next(
                        r["id"]
                        for r in fixtures["inventory"]["crm.Client"]
                        if r["email"] == f"client-0@{scenario}.preview.test"
                    )
                if side == "before" and scenario == "contacts":
                    continue  # Known assigned-staff 500 retained in main BEFORE evidence.
                context = browser.new_context(reduced_motion="reduce", service_workers="block")
                context.route(
                    "**/*",
                    lambda route, request, origin=origin: (
                        route.continue_()
                        if route.request.url.startswith(origin + "/")
                        else route.abort()
                    ),
                )
                page = context.new_page()
                login(page, origin, state, email, allow_restricted=True)
                sizes = SIZES if scenario in ("contacts", "no-history") else [SIZES[0], SIZES[2]]
                for width, height in sizes:
                    page.set_viewport_size({"width": width, "height": height})
                    for theme in ("light", "dark"):
                        page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                        response = page.goto(
                            origin + f"/crm/staff/clients/{customer}/", wait_until="networkidle"
                        )
                        row = dict(
                            side=side,
                            scenario=scenario,
                            width=width,
                            theme=theme,
                            status=response.status,
                            checks={},
                        )
                        checks = row["checks"]
                        checks["http200"] = response.status == 200
                        if side == "after":
                            if scenario == "contacts":
                                page.locator(f"#business-{customer} summary").click()
                                expect(page.locator(f"#business-{customer}")).to_have_attribute(
                                    "open", ""
                                )
                                # Owned preview guard rewrites mailto/tel/external hrefs;
                                # true destinations are asserted in the 15-test Django suite.
                                checks["secondary_links"] = all(
                                    page.get_by_role("link", name=name, exact=True).count()
                                    for name in ("office@clients.preview.test", "+1 721 555 0199")
                                )
                                checks["website_and_whatsapp_present"] = all(
                                    page.get_by_role("link", name=name, exact=True).count()
                                    for name in ("https://example.test", "+1 721 555 0198")
                                )
                            row["metrics"] = page.evaluate(METRICS)
                            row["axe"] = axe(page, ".mm-services-clients")
                            checks["reflow"] = row["metrics"]["documentWidth"] <= width
                            checks["targets"] = not row["metrics"]["targets"]
                            checks["axe"] = not row["axe"]["violations"]
                            if scenario in ("grace", "restricted", "locked"):
                                readonly = scenario == "restricted"
                                checks["modify_controls"] = page.locator(
                                    "[data-client-archive]"
                                ).count() == int(not readonly)
                                checks["edit_controls"] = page.locator(
                                    '.mm-sc-header a[href$="/edit/"]'
                                ).count() == int(not readonly)
                                checks["read_only_notice"] = (
                                    "This workspace is read-only."
                                    in page.locator(".mm-services-clients").inner_text()
                                ) == readonly
                        page.screenshot(
                            path=str(out / f"{side}-{scenario}-{width}-{theme}.png"), full_page=True
                        )
                        if side == "after" and scenario == "contacts":
                            # No financial writes: exercise the existing invoice GET and return.
                            href = page.locator("#client-invoices article a").first.get_attribute(
                                "href"
                            )
                            invoice = page.request.get(origin + href)
                            checks["existing_invoice_get"] = invoice.status == 200
                            page.locator("[data-client-archive] button").click()
                            modal = page.locator("#clientsArchiveModal")
                            expect(
                                modal.get_by_role("button", name="Cancel", exact=True)
                            ).to_be_focused()
                            row["modal_axe"] = axe(page, "#clientsArchiveModal")
                            checks["modal_axe"] = not row["modal_axe"]["violations"]
                            page.screenshot(path=str(out / f"archive-{width}-{theme}.png"))
                            page.keyboard.press("Escape")
                            expect(modal).not_to_be_visible()
                            expect(page.locator("[data-client-archive] button")).to_be_focused()
                            checks["escape_focus"] = True
                        row["pass"] = all(checks.values())
                        cases.append(row)
                        (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
                context.close()
        browser.close()
    result = {"cases": cases, "pass": all(row["pass"] for row in cases)}
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"evidence": str(out), "cases": len(cases), "pass": result["pass"]}))
    if not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
