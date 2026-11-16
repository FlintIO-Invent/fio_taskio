"""Actual Django BEFORE/AFTER review on owned disposable sessions, no external requests."""

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from ui_preview.cli import health
from ui_preview.core import REPO, load_session, verify_database, verify_source

SIZES = (1440, 768, 390, 320)


def run(session, output):
    root, state = load_session(session)
    identities = {}
    snapshots = {}
    for side in ("before", "after"):
        verify_source(state[side]["source"])
        identities[side] = verify_database(root, state, side)
        snapshots[side] = health(state, side)
    if snapshots["before"]["fixtures"] != snapshots["after"]["fixtures"]:
        raise RuntimeError("Fixture identities differ; do not reset review data.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    fixtures = snapshots["after"]["fixtures"]["appointments_review"]
    first = fixtures["appointments"][0]["id"]
    cases = {
        "workspace": "/appointments/",
        "detail": f"/appointments/{first}/",
        "form": "/appointments/create/",
        "public": f"/book/{fixtures['slug']}/",
        "request": f"/crm/staff/leads/{fixtures['requests']['missing']}/",
    }
    report = {
        "identities": identities,
        "source": {s: snapshots[s]["source_sha256"] for s in snapshots},
        "cases": [],
        "tasks": [],
        "errors": [],
        "page_errors": [],
        "blocked_requests": [],
        "supplemental_axe": [],
    }
    axe = (REPO / "ui-lab/services-dashboard/tools/node_modules/axe-core/axe.min.js").read_text()
    font = (
        REPO / "ui-lab/services-dashboard/shared/assets/nunito-sans-latin-wght-normal.woff2"
    ).read_bytes()
    origins = {f"http://127.0.0.1:{state[s]['http_port']}" for s in ("before", "after")}

    def network(route):
        url = route.request.url
        if any(url.startswith(origin + "/") for origin in origins):
            route.continue_()
        elif url.startswith("https://fonts.googleapis.com/"):
            route.fulfill(
                content_type="text/css",
                body="@font-face{font-family:'Nunito Sans';font-weight:200 1000;src:url('https://fonts.gstatic.com/bookings-preview.woff2')}",
            )
        elif url == "https://fonts.gstatic.com/bookings-preview.woff2":
            route.fulfill(content_type="font/woff2", body=font)
        else:
            report["blocked_requests"].append(url)
            route.abort()

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
        report["browser"] = browser.version
        for side in ("before", "after"):
            origin = f"http://127.0.0.1:{state[side]['http_port']}"
            context = browser.new_context(service_workers="block", reduced_motion="reduce")
            context.route("**/*", network)
            context.add_init_script("localStorage.setItem('phoenixTheme', window.name || 'light');")
            page = context.new_page()
            page.on(
                "pageerror",
                lambda error, side=side: report["page_errors"].append(
                    {"side": side, "error": str(error)}
                ),
            )
            page.goto(origin + "/accounts/login/")
            page.locator("input[name=email]").fill("bookings.owner@preview.test")
            page.locator("input[name=password]").fill(state["password"])
            page.get_by_role("button", name="Sign In", exact=True).click()
            page.wait_for_url("**/crm/agent/dashboard/")
            for theme in ("light", "dark"):
                page.evaluate(
                    "theme=>{window.name=theme;localStorage.setItem('phoenixTheme',theme)}", theme
                )
                for width in SIZES:
                    page.set_viewport_size(
                        {"width": width, "height": 960 if width == 1440 else 900}
                    )
                    for name, path in cases.items():
                        case = {"side": side, "view": name, "width": width, "theme": theme}
                        try:
                            response = page.goto(origin + path, wait_until="networkidle")
                            assert response.status == 200, response.status
                            page.evaluate("document.fonts.ready")
                            filename = f"{side}-{name}-{width}-{theme}.png"
                            page.screenshot(path=str(output / filename), full_page=True)
                            case["screenshot"] = filename
                            case["overflow"] = page.evaluate(
                                "document.documentElement.scrollWidth > innerWidth + 1"
                            )
                            if side == "after":
                                assert not case["overflow"], "Document overflow"
                                expect(page.locator(".mm-sb-content h1")).to_have_count(1)
                                awaitable = """async()=>{const r=await axe.run('.mm-sb-content',{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:r.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),incomplete:r.incomplete.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))}}"""
                                page.add_script_tag(content=axe)
                                case["axe"] = page.evaluate(awaitable)
                        except Exception as error:
                            case["error"] = str(error)
                            report["errors"].append(case.copy())
                        report["cases"].append(case)
            if side == "after":

                def task(name, action):
                    try:
                        action()
                        report["tasks"].append({"name": name, "passed": True})
                    except Exception as error:
                        report["tasks"].append({"name": name, "passed": False, "error": str(error)})

                def status_dialog(page=page, origin=origin):
                    page.goto(origin + cases["detail"])
                    page.get_by_role("button", name="Cancel Appointment", exact=True).click()
                    modal = page.locator("#bookingStatusConfirmation")
                    expect(modal).to_be_visible()
                    page.screenshot(path=str(output / "after-status-dialog.png"), full_page=True)
                    page.add_script_tag(content=axe)
                    audit = page.evaluate(
                        "async()=>{const r=await axe.run('#bookingStatusConfirmation');return {violations:r.violations,incomplete:r.incomplete}}"
                    )
                    report["supplemental_axe"].append({"view": "status-dialog", **audit})
                    assert not audit["violations"], "Status dialog accessibility findings"
                    page.keyboard.press("Escape")
                    expect(modal).not_to_be_visible()
                    expect(
                        page.get_by_role("button", name="Cancel Appointment", exact=True)
                    ).to_be_focused()

                task("Terminal dialog cancel/Escape preserves status", status_dialog)

                def draft(page=page, origin=origin):
                    page.goto(origin + cases["form"])
                    page.locator("#id_title").fill("Unsaved local draft")
                    page.locator("#id_notes").fill("Keep this note")
                    page.get_by_role("button", name="Add a new client", exact=True).click()
                    modal = page.locator("#draftClientModal")
                    expect(modal).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(modal).not_to_be_visible()
                    expect(page.locator("#id_title")).to_have_value("Unsaved local draft")
                    expect(page.locator("#id_notes")).to_have_value("Keep this note")

                task("Inline Client modal retains appointment draft", draft)

                def public_review(page=page, origin=origin):
                    page.goto(origin + cases["public"])
                    page.locator("#id_booking_intent").select_option("book_later")
                    page.locator("#id_service").select_option(index=1)
                    page.locator("[data-booking-wizard-next]").click()
                    expect(page.locator("[data-book-later-section]")).to_be_visible()
                    page.locator("[data-booking-wizard-next]").click()
                    page.locator("#id_client_type").select_option("INDIVIDUAL")
                    for name, value in {
                        "first_name": "Public",
                        "last_name": "Review",
                        "email": "review@example.test",
                        "phone": "+17215550182",
                    }.items():
                        page.locator("#id_" + name).fill(value)
                    page.locator("[data-booking-wizard-next]").click()
                    page.locator("#id_street_address").fill("12 Review Road")
                    page.locator("#id_consent_to_contact").check()
                    # Review is local; a page action updates its display on entering the step.
                    page.locator('[data-booking-review-edit="2"]').click()
                    page.locator("[data-booking-wizard-next]").click()
                    expect(page.locator("[data-booking-review-values]")).to_contain_text(
                        "Public Review"
                    )
                    expect(page.locator("[data-booking-review-values]")).to_contain_text(
                        "No appointment will be scheduled"
                    )
                    page.screenshot(path=str(output / "after-public-review.png"), full_page=True)

                task("Contact intent four-step review and edit", public_review)

                # Additional server-bound states; no mutations of review records.
                for name, path in {
                    "invalid-filter": "/appointments/?staff=999999999",
                    "request-create": "/crm/staff/leads/create/",
                    "completion": f"/crm/staff/leads/{fixtures['requests']['missing']}/convert-to-client/",
                    "terminal": f"/appointments/{fixtures['appointments'][1]['id']}/",
                }.items():
                    response = page.goto(origin + path, wait_until="networkidle")
                    report["tasks"].append(
                        {
                            "name": name + " GET",
                            "passed": response.status == 200,
                            "status": response.status,
                        }
                    )
                    page.screenshot(path=str(output / f"after-{name}.png"), full_page=True)

                def public_slots(page=page, origin=origin):
                    page.goto(origin + cases["public"])
                    page.locator("#id_service").select_option(index=1)
                    page.locator("[data-booking-wizard-next]").click()
                    page.locator("#id_staff_member").select_option(index=1)
                    dates = page.locator("[data-slot-date-grid] button:not(:disabled)")
                    expect(dates.first).to_be_visible()
                    dates.first.click()
                    expect(
                        page.locator("[data-slot-date-grid] button[aria-pressed=true]")
                    ).to_be_focused()
                    times = page.locator("[data-slot-time-grid] button")
                    expect(times.first).to_be_visible()
                    times.first.click()
                    expect(
                        page.locator("[data-slot-time-grid] button[aria-pressed=true]")
                    ).to_be_focused()
                    value = page.locator("#id_preferred_time").input_value()
                    page.locator("[data-booking-wizard-prev]").click()
                    page.locator("#id_booking_intent").select_option("book_later")
                    expect(page.locator("#id_preferred_time")).to_have_value(value)
                    assert not page.locator("#id_preferred_time").is_disabled()

                task("Slot keyboard focus and preserved stale-value contract", public_slots)

                def related(page=page, origin=origin):
                    page.goto(origin + cases["detail"])
                    page.locator(".mm-sb-related summary").click()
                    expect(
                        page.get_by_role("link", name="View Client", exact=True).first
                    ).to_be_visible()
                    page.locator(".mm-sb-related summary").press("Escape")
                    assert not page.locator(".mm-sb-related").evaluate("el=>el.open")

                task("Related actions disclosure and Escape", related)

                # RTL and non-reduced motion stay page-local and retain the Phoenix shell.
                page.evaluate("localStorage.setItem('phoenixIsRTL','true')")
                page.emulate_media(reduced_motion="no-preference")
                for name in ("workspace", "form", "public"):
                    page.goto(origin + cases[name], wait_until="networkidle")
                    report["tasks"].append(
                        {
                            "name": name + " RTL/normal motion",
                            "passed": not page.evaluate(
                                "document.documentElement.scrollWidth>innerWidth+1"
                            ),
                        }
                    )
                    page.screenshot(path=str(output / f"after-{name}-rtl.png"), full_page=True)
                page.evaluate("localStorage.setItem('phoenixIsRTL','false')")
                page.emulate_media(reduced_motion="reduce")
                # Text enlargement checks actual CSS reflow, independently from device screenshots.
                page.goto(origin + cases["form"])
                page.add_style_tag(content=".mm-sb-content{font-size:200%!important}")
                report["tasks"].append(
                    {
                        "name": "200 percent content text enlargement",
                        "passed": not page.evaluate(
                            "document.documentElement.scrollWidth>innerWidth+1"
                        ),
                    }
                )

                for account in ["admin", "staff", "accountant", "viewer"]:
                    page.goto(origin + "/accounts/logout/")
                    page.goto(origin + "/accounts/login/")
                    page.locator("input[name=email]").fill(f"bookings.{account}@preview.test")
                    page.locator("input[name=password]").fill(state["password"])
                    page.get_by_role("button", name="Sign In", exact=True).click()
                    page.wait_for_url("**/crm/agent/dashboard/")
                    page.goto(origin + cases["workspace"])
                    count = page.get_by_role("link", name="New Appointment", exact=True).count()
                    report["tasks"].append(
                        {
                            "name": account + " workspace controls",
                            "passed": count == int(account in {"admin", "staff"}),
                        }
                    )
                    page.goto(origin + cases["detail"])
                    count = page.get_by_role(
                        "button", name="Cancel Appointment", exact=True
                    ).count()
                    report["tasks"].append(
                        {
                            "name": account + " status controls",
                            "passed": count == int(account in {"admin", "staff"}),
                        }
                    )
                    page.screenshot(path=str(output / f"after-role-{account}.png"), full_page=True)
                for scenario in ["empty", "long", "locked", "restricted", "grace"]:
                    page.goto(origin + "/accounts/logout/")
                    page.goto(origin + "/accounts/login/")
                    page.locator("input[name=email]").fill(f"{scenario}.owner@preview.test")
                    page.locator("input[name=password]").fill(state["password"])
                    page.get_by_role("button", name="Sign In", exact=True).click()
                    page.wait_for_url("**/crm/agent/dashboard/")
                    response = page.goto(origin + cases["workspace"], wait_until="networkidle")
                    report["tasks"].append(
                        {
                            "name": scenario + " workspace",
                            "passed": response.status in (200, 302)
                            and not page.evaluate(
                                "document.documentElement.scrollWidth>innerWidth+1"
                            ),
                        }
                    )
                    page.screenshot(
                        path=str(output / f"after-state-{scenario}.png"), full_page=True
                    )
                # Return to the same owner before comparing protected pages.
                page.goto(origin + "/accounts/logout/")
                page.goto(origin + "/accounts/login/")
                page.locator("input[name=email]").fill("bookings.owner@preview.test")
                page.locator("input[name=password]").fill(state["password"])
                page.get_by_role("button", name="Sign In", exact=True).click()
                page.wait_for_url("**/crm/agent/dashboard/")

            # Approved dashboard and shared public Logistics form, read only.
            page.set_viewport_size({"width": 1440, "height": 960})
            for name, path in {
                "dashboard": "/crm/agent/dashboard/",
                "logistics-application": "/logistics/apply/",
            }.items():
                response = page.goto(origin + path, wait_until="networkidle")
                page.mouse.move(1400, 800)
                page.wait_for_timeout(250)
                page.screenshot(path=str(output / f"{side}-protected-{name}.png"), full_page=True)
                report["tasks"].append(
                    {
                        "name": side + " protected " + name,
                        "passed": response.status == 200,
                        "booking_assets": page.locator(
                            'link[href*="services-bookings.css"]'
                        ).count(),
                    }
                )
            context.close()
        browser.close()
    report["new_axe_violations"] = sum(
        len(c.get("axe", {}).get("violations", [])) for c in report["cases"]
    )
    report["new_axe_violations"] += sum(len(c["violations"]) for c in report["supplemental_axe"])
    report["passed"] = (
        not report["errors"]
        and not report["new_axe_violations"]
        and all(t["passed"] for t in report["tasks"])
    )
    (output / "results.json").write_text(json.dumps(report, indent=2))
    gallery = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Appointments Django comparison</title><h1>Real Django BEFORE / AFTER</h1><p>Synthetic records; providers disabled.</p>'
    for side in ("before", "after"):
        gallery += f"<h2>{side.title()}</h2>"
        for case in report["cases"]:
            if case["side"] == side and "screenshot" in case:
                f = case["screenshot"]
                gallery += f'<p>{case["view"]} {case["width"]} {case["theme"]}<br><a href="{f}"><img src="{f}" width="320" alt="{case["view"]}"></a></p>'
    (output / "gallery.html").write_text(gallery + "</html>")
    print(
        json.dumps(
            {
                "output": str(output),
                "cases": len(report["cases"]),
                "errors": len(report["errors"]),
                "axe_violations": report["new_axe_violations"],
                "tasks": report["tasks"],
            },
            indent=2,
        )
    )
    return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(not run(args.session, args.output))
