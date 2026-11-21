"""Real Team browser review; refuses unowned source, DB and HTTP identities."""

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright
from services_clients_browser_check import axe, health, login
from ui_preview.core import load_session, verify_database, verify_source

SCOPE = ".mm-services-team"


def capture(session_path, side):
    root, state = load_session(session_path)
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    origin, _ = health(state, side)
    out = Path(state[side]["directory"]) / "evidence/team"
    out.mkdir(parents=True, exist_ok=True)
    cases, errors, shots = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
        context = browser.new_context(reduced_motion="reduce", service_workers="block")
        context.route(
            "**/*", lambda r: r.continue_() if r.request.url.startswith(origin + "/") else r.abort()
        )
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        login(page, origin, state, "team.owner@preview.test", allow_restricted=True)
        for width, height in [(1440, 1000), (768, 1024), (390, 844), (320, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            for theme in ["light", "dark"]:
                page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                response = page.goto(origin + "/businesses/team/", wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                metrics = page.evaluate(
                    """() => {const r=document.querySelector('.mm-services-team')||document.querySelector('.content');return {overflow:document.documentElement.scrollWidth>innerWidth,h1:r.querySelectorAll('h1').length,font:getComputedStyle(r).fontFamily,small:[...r.querySelectorAll('a,button,input:not([type=hidden]),select,summary')].filter(e=>e.checkVisibility({checkVisibilityCSS:true})).map(e=>({name:e.name||e.textContent.trim().slice(0,60),w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height})).filter(e=>e.w<43.9||e.h<43.9)}}"""
                )
                scoped = page.locator(SCOPE).count() > 0
                results = axe(page, SCOPE if scoped else ".content")
                case = {
                    "width": width,
                    "theme": theme,
                    "status": response.status,
                    "metrics": metrics,
                    "axe": results,
                }
                if (width, theme) in [(1440, "light"), (390, "dark")]:
                    shot = out / f"team-{width}-{theme}.png"
                    page.screenshot(path=str(shot), full_page=True, animations="disabled")
                    shots.append(str(shot))
                cases.append(case)
                (out / "cases-progress.json").write_text(json.dumps(cases, indent=2) + "\n")
                if side == "after":
                    assert (
                        response.status == 200 and metrics["h1"] == 1 and not metrics["overflow"]
                    ), case
                    assert not results["violations"], results["violations"]
                    assert not metrics["small"], metrics["small"]
        scenarios = []
        for scenario in ["empty", "long", "readonly", "starter", "logistics"]:
            login(
                page,
                origin,
                state,
                "team." + scenario + ".owner@preview.test",
                allow_restricted=True,
            )
            response = page.goto(origin + "/businesses/team/", wait_until="networkidle")
            scenarios.append(
                {
                    "scenario": scenario,
                    "status": response.status,
                    "overflow": page.evaluate("document.documentElement.scrollWidth>innerWidth"),
                    "services_assets": page.locator('[href*="services-team.css"]').count(),
                }
            )
            assert response.status == 200
            if scenario == "logistics":
                assert page.locator('[href*="services-team.css"]').count() == 0
            elif side == "after":
                assert not scenarios[-1]["overflow"]
        roles = []
        for role in ["admin", "staff", "accountant", "viewer"]:
            login(page, origin, state, "team." + role + "@preview.test", allow_restricted=True)
            response = page.goto(origin + "/businesses/team/", wait_until="networkidle")
            roles.append({"role": role, "status": response.status})
            assert response.status == (200 if role == "admin" else 403)
        journey = {}
        if side == "after":
            login(page, origin, state, "team.owner@preview.test", allow_restricted=True)
            page.goto(origin + "/businesses/team/", wait_until="networkidle")
            page.get_by_role("link", name="Invite team member", exact=True).click()
            form = page.locator("[data-team-invite]")
            form.locator("[name=email]").fill("bad-email")
            with page.expect_navigation(wait_until="networkidle"):
                form.get_by_role("button", name="Send invitation").click()
            assert page.get_by_text("Enter a valid email address.", exact=True).count()
            email = "browser-" + uuid4().hex[:10] + "@preview.test"
            form = page.locator("[data-team-invite]")
            form.locator("[name=email]").fill(email)
            form.locator("[name=role]").select_option("staff")
            with page.expect_navigation(wait_until="networkidle"):
                form.get_by_role("button", name="Send invitation").click()
            row = page.locator(".mm-pending tr").filter(has_text=email)
            assert row.count() == 1
            accept = row.locator("code").inner_text().strip()
            login_context = browser.new_context(service_workers="block")
            login_context.route(
                "**/*",
                lambda r: r.continue_() if r.request.url.startswith(origin + "/") else r.abort(),
            )
            accept_page = login_context.new_page()
            accept_page.goto(accept, wait_until="networkidle")
            for name, value in {
                "first_name": "Browser",
                "last_name": "Invitee",
                "password1": state["password"],
                "password2": state["password"],
            }.items():
                accept_page.locator("[name=" + name + "]").fill(value)
            with accept_page.expect_navigation(wait_until="networkidle"):
                accept_page.get_by_role("button", name="Create account and join workspace").click()
            assert "/crm/agent/dashboard/" in accept_page.url
            login_context.close()
            page.goto(origin + "/businesses/team/", wait_until="networkidle")
            row = page.locator("[data-membership-id]").filter(has_text=email)
            page.once("dialog", lambda dialog: dialog.accept())
            with page.expect_navigation(wait_until="networkidle"):
                row.get_by_role("button", name="Remove " + email, exact=True).click()
            row = page.locator("[data-membership-id]").filter(has_text=email)
            assert row.get_by_text("Inactive", exact=True).count() == 1
            page.locator("#id_email").fill("draft@preview.test")
            page.evaluate("document.documentElement.dataset.bsTheme='dark'")
            assert page.locator("#id_email").input_value() == "draft@preview.test"
            page.evaluate("document.documentElement.dir='rtl'")
            assert not page.evaluate("document.documentElement.scrollWidth>innerWidth")
            journey = {
                "invalid_draft": True,
                "native_invite_and_signup": True,
                "soft_deactivate": True,
                "theme_draft": True,
                "rtl_reflow": True,
            }
        context.close()
        browser.close()
    report = {
        "side": side,
        "cases": cases,
        "scenarios": scenarios,
        "roles": roles,
        "journey": journey,
        "page_errors": errors,
        "screenshots": shots,
        "known_limitation": "Existing-user acceptance controls remain excluded; fresh-user signup was exercised.",
    }
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    assert not errors, errors
    print(
        json.dumps(
            {
                "side": side,
                "cases": len(cases),
                "scenarios": len(scenarios),
                "roles": roles,
                "journey": journey,
                "evidence": str(out),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--side", choices=["before", "after"], required=True)
    args = parser.parse_args()
    capture(args.session, args.side)
