"""Chromium exercises actual authentication/forms on owned, already-running apps."""

import json
import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright
from ui_preview.cli import health, start
from ui_preview.core import (
    SIDES,
    stop_side,
    verify_database,
    verify_source,
    write_json,
)

SIZES = [(1440, 900), (768, 1024), (390, 844)]


def validate(root, state):
    before = health(state, "before")
    after = health(state, "after")
    if before["fixtures"] != after["fixtures"]:
        raise RuntimeError("Initial fixture inventories differ.")
    if (
        before["database"] == after["database"]
        or before["cookie_name"] == after["cookie_name"]
        or before["csrf_cookie_name"] == after["csrf_cookie_name"]
    ):
        raise RuntimeError("Preview database/cookie isolation is absent.")
    identities = {name: verify_database(root, state, name) for name in SIDES}
    if identities["before"]["system_identifier"] == identities["after"]["system_identifier"]:
        raise RuntimeError("Expected two independent PostgreSQL clusters.")
    out = root / "evidence"
    out.mkdir(exist_ok=True)
    report = {
        "checks": [],
        "identities": identities,
        "accounts": [],
        "blockedBrowserRequests": [],
        "pageErrors": [],
        "httpErrors": [],
        "unavailable": [
            "External Unicons/Turf/maps and service workers blocked by CSP",
            "Provider endpoints and financial writes explicitly unavailable",
            "BEFORE retains its original missing mobile search modal",
        ],
    }

    def check(text):
        report["checks"].append(text)

    origins = {f"http://127.0.0.1:{state[name]['http_port']}" for name in SIDES}
    origins.add(f"http://127.0.0.1:{state['launcher_port']}")
    fixtures = before["fixtures"]
    accounts = fixtures["accounts"]
    # None selects the browser installed by this version of Playwright.
    chromium = os.environ.get("PWA_CHROMIUM") or None

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium)
        report["browser"] = browser.version
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            service_workers="block",
            reduced_motion="reduce",
        )

        def network(route):
            if any(route.request.url.startswith(origin + "/") for origin in origins):
                route.continue_()
            else:
                report["blockedBrowserRequests"].append(
                    {"url": route.request.url, "reason": "route policy"}
                )
                route.abort()

        context.route("**/*", network)
        pages = {name: context.new_page() for name in SIDES}
        for page in pages.values():
            page.on("pageerror", lambda error: report["pageErrors"].append(str(error)))
            page.on(
                "requestfailed",
                lambda req: report["blockedBrowserRequests"].append(
                    {"url": req.url, "reason": req.failure}
                ),
            )

        def base(name):
            return f"http://127.0.0.1:{state[name]['http_port']}"

        def visit(name, path):
            response = pages[name].goto(base(name) + path, wait_until="networkidle")
            if response.status >= 400:
                raise AssertionError(f"{name} {path}: HTTP {response.status}")
            return response

        def login(name, email):
            page = pages[name]
            visit(name, "/accounts/logout/")
            visit(name, "/accounts/login/")
            assert page.locator("input[name=csrfmiddlewaretoken]").input_value()
            page.locator("input[name=email]").fill(email)
            page.locator("input[name=password]").fill(state["password"])
            with page.expect_navigation(wait_until="networkidle"):
                page.get_by_role("button", name="Sign In", exact=True).click()
            assert "/crm/agent/dashboard/" in page.url, (name, email, page.url)
            return page

        def dialog_focus(page, dialog, key):
            page.keyboard.press(key)
            if not page.evaluate("document.hasFocus()"):
                assert page.evaluate("document.activeElement===document.body")
                page.keyboard.press(key)
            assert dialog.evaluate("e=>e.contains(document.activeElement)")

        try:
            # Every identity uses the application's real login POST and membership resolver.
            for account in accounts:
                for name in SIDES:
                    page = login(name, account["email"])
                    text = page.locator(".content").all_text_contents()
                    assert account["business"] in "\n".join(text)
                    upgraded = (
                        Path(state[name]["source"])
                        / "src/templates/crm/agent_dashboard/includes/services_overview.html"
                    ).exists()
                    target = account["vertical"] == "SERVICE" and upgraded
                    marker = page.locator("body").evaluate(
                        "e=>e.classList.contains('mm-services-dashboard-page')"
                    )
                    assert marker == target
                    assert page.locator('link[href*="services-dashboard.css"]').count() == int(
                        target
                    )
                    assert page.locator('script[src*="services-dashboard.js"]').count() == int(
                        target
                    )
                    setup = page.locator(
                        '[data-bs-target="#onboardingGuidePanel"],[data-bs-target="#onboardingWelcomeModal"]'
                    ).count()
                    assert bool(setup) == (account["role"] in {"owner", "admin"})
                    if account["scenario"] == "restricted":
                        assert "temporarily read-only" in page.locator("body").inner_text()
                    if account["scenario"] == "grace":
                        assert "could not process" in page.locator("body").inner_text()
                    if account["scenario"] == "locked":
                        assert "Appointments Locked" in page.locator(".content").inner_text()
                    if account["scenario"] == "empty":
                        assert "No upcoming appointments" in page.locator(".content").inner_text()
                    report["accounts"].append({"side": name, **account, "pass": True})
            check(
                f"{len(accounts) * 2} real login/role/state checks; native tenant selection, subscriptions and dashboard asset boundary"
            )

            for name in SIDES:
                login(name, "owner@preview.test")
            # Cookie names are host-level, so test both pages in ONE browser context.
            cookie_names = {c["name"] for c in context.cookies()}
            for h in (before, after):
                assert {h["cookie_name"], h["csrf_cookie_name"]} <= cookie_names
            assert "sessionid" not in cookie_names and "csrftoken" not in cookie_names
            token = pages["before"].locator("input[name=csrfmiddlewaretoken]").first.input_value()
            reject = context.request.post(
                base("after") + "/crm/agent/dashboard/",
                form={"onboarding_action": "continue_later", "csrfmiddlewaretoken": token},
            )
            assert reject.status == 403
            visit("before", "/accounts/logout/")
            visit("after", "/crm/agent/dashboard/")
            assert "/accounts/login" not in pages["after"].url
            login("before", "viewer@preview.test")
            assert pages["before"].locator('[data-bs-target="#onboardingGuidePanel"]').count() == 0
            assert pages["after"].locator('[data-bs-target="#onboardingGuidePanel"]').count() == 1
            check(
                "Simultaneous sessions, separate cookies/CSRF, BEFORE logout/role switch leaves AFTER owner authenticated; cross-side CSRF rejected"
            )

            for name in SIDES:
                page = login(name, "owner@preview.test")
                source = verify_source(state[name]["source"])
                if source.get("reconstruction"):
                    assert page.locator("h4", has_text="Upcoming Activity").count() == 1
                    assert page.locator(".mm-services-dashboard").count() == 0
                for width, height in SIZES:
                    page.set_viewport_size({"width": width, "height": height})
                    for theme in ("light", "dark"):
                        page.evaluate('theme=>localStorage.setItem("phoenixTheme",theme)', theme)
                        visit(name, "/crm/agent/dashboard/")
                        assert (
                            page.locator("html").get_attribute("data-bs-theme") or "light"
                        ) == theme
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                        page.evaluate("document.fonts.ready")
                        for full in (False, True):
                            page.screenshot(
                                path=str(
                                    out
                                    / f"{name}-{width}-{theme}-{'full' if full else 'viewport'}.png"
                                ),
                                full_page=full,
                                animations="disabled",
                            )
                page.locator("label[for=themeControlToggle]:visible").click()
                selected = page.locator("html").get_attribute("data-bs-theme") or "light"
                visit(name, "/crm/agent/dashboard/")
                assert (page.locator("html").get_attribute("data-bs-theme") or "light") == selected
                page.locator("#navbarDropdownUser").click()
                page.locator(".dropdown-profile.show").wait_for(state="visible")
                page.keyboard.press("Escape")
                page.locator(".dropdown-profile.show").wait_for(state="hidden")
                page.get_by_role("button", name="Toggle Navigation").click()
                page.locator("#navbarVerticalCollapse.show").wait_for(state="visible")
                page.get_by_role("button", name="Toggle Navigation").click()
                page.locator("#navbarVerticalCollapse.show").wait_for(state="hidden")
                assert page.locator('[data-bs-target="#searchBoxModal"]').count() == int(
                    not source.get("files", {}).get(
                        "src/templates/crm/agent_dashboard/includes/services_overview.html"
                    )
                )
                # Actual existing details/list links, no simulated route-intent layer.
                for pattern in [
                    r"^/appointments/\d+/$",
                    r"^/crm/staff/leads/\d+/$",
                    r"^/billings/\d+/$",
                ]:
                    links = page.locator(".content a[href]").evaluate_all(
                        'els=>els.map(e=>e.getAttribute("href"))'
                    )
                    href = next(h for h in links if re.match(pattern, h))
                    link = page.locator(f'.content a[href="{href}"]').first
                    with page.expect_navigation(wait_until="networkidle") as response:
                        link.click()
                    assert response.value.status == 200 and page.url == base(name) + href
                    visit(name, "/crm/agent/dashboard/")
                href = next(
                    h
                    for h in page.locator(".content a[href]").evaluate_all(
                        'els=>els.map(e=>e.getAttribute("href"))'
                    )
                    if "state=needs_follow_up" in h
                )
                with page.expect_navigation(wait_until="networkidle") as response:
                    page.locator(f'.content a[href="{href}"]').first.click()
                assert response.value.status == 200 and "state=needs_follow_up" in page.url
                visit(name, "/crm/agent/dashboard/")
                booking = page.locator('.content a[target="_blank"]').filter(
                    has_text=re.compile("Open")
                )
                if booking.count():
                    with page.expect_popup() as event:
                        booking.first.click()
                    popup = event.value
                    popup.wait_for_load_state("networkidle")
                    assert (
                        popup.url.startswith(base(name) + "/book/")
                        and popup.locator("form").count()
                    )
                    popup.close()
                    page.bring_to_front()
                disabled = context.request.post(base(name) + "/billing/payment-recovery/", form={})
                assert disabled.status == 409
                disabled = context.request.post(base(name) + "/billings/1/", form={})
                assert disabled.status == 409
            check(
                "Both real dashboards: six responsive/theme captures, theme persistence, menus, mobile navigation, appointment/request/invoice details, follow-up/public booking links; provider/financial POSTs denied"
            )

            for name in SIDES:
                page = login(name, "validation.owner@preview.test")
                modal = page.locator("#onboardingWelcomeModal")
                # A previous real POST can complete welcome. Reopen the actual
                # Bootstrap component for repeat checks; never reset review data.
                if not modal.is_visible():
                    modal.evaluate("e=>bootstrap.Modal.getOrCreateInstance(e).show()")
                modal.get_by_role("button", name="Close", exact=True).wait_for(state="visible")
                modal.get_by_role("button", name="Close", exact=True).focus()
                for _ in range(7):
                    dialog_focus(page, modal, "Tab")
                form = modal.locator("form").filter(
                    has=page.locator("input[name=selected_journey][value=setup_business]")
                )
                assert form.locator("input[name=open_guide_after_select]").input_value() == "1"
                with page.expect_navigation(wait_until="networkidle"):
                    form.locator("button[type=submit]").click()
                assert page.url.endswith("?setup_guide=1")
                panel = page.locator("#onboardingGuidePanel")
                panel.get_by_role("button", name="Close", exact=True).wait_for(state="visible")
                page.keyboard.press("Escape")
                assert "show" in panel.get_attribute("class")
                page.screenshot(
                    path=str(out / f"{name}-onboarding.png"), full_page=True, animations="disabled"
                )
                with page.expect_navigation(wait_until="networkidle"):
                    panel.get_by_role("button", name="Next", exact=True).click()
                with page.expect_navigation(wait_until="networkidle"):
                    panel.get_by_role("button", name="Back", exact=True).click()
                with page.expect_navigation(wait_until="networkidle"):
                    panel.get_by_role("button", name="Close", exact=True).click()
                assert not page.url.endswith("?setup_guide=1")
            check(
                "Both native onboarding modal/guide flows: keyboard containment, real CSRF select journey/Next/Back/close POSTs and static Escape behavior; dedicated validation accounts only"
            )

            unchanged = {}
            for email in [
                "owner@preview.test",
                "logistics.owner@preview.test",
                "logistics.staff@preview.test",
            ]:
                views = (
                    ["/appointments/", "/crm/staff/clients/", "/billings/"]
                    if email == "owner@preview.test"
                    else ["/crm/agent/dashboard/"]
                )
                for name in SIDES:
                    page = login(name, email)
                    page.set_viewport_size({"width": 1440, "height": 900})
                    for path in views:
                        visit(name, path)
                        assert (
                            page.locator(
                                'link[href*="services-dashboard.css"],script[src*="services-dashboard.js"]'
                            ).count()
                            == 0
                        )
                        text = "\n".join(page.locator(".content").all_text_contents()).replace(
                            base(name), "PREVIEW_ORIGIN"
                        )
                        unchanged[name, email, path] = " ".join(text.split())
                        page.screenshot(
                            path=str(
                                out
                                / f"{name}-unchanged-{email.split('@')[0]}-{path.strip('/').replace('/', '-')}.png"
                            ),
                            full_page=True,
                            animations="disabled",
                        )
                for path in views:
                    assert unchanged["before", email, path] == unchanged["after", email, path], (
                        email,
                        path,
                    )
            check(
                "Other Services pages and Logistics owner/staff content and dashboard asset isolation match across source versions"
            )

            for name in SIDES:
                login(name, "owner@preview.test")
            stop_side(root, state, "before")
            assert health(state, "after")["side"] == "after"
            start(root, state, ["before"])
            visit("before", "/crm/agent/dashboard/")
            assert "/accounts/login/" not in pages["before"].url
            check(
                "BEFORE server+cluster stop/start independently; AFTER stays live; login persists across restart"
            )
            for name in SIDES:
                verify_source(state[name]["source"])
            assert not report["pageErrors"], report["pageErrors"]
            report["pass"] = True
        except Exception as error:
            report.update({"pass": False, "error": str(error)})
            for name, page in pages.items():
                page.screenshot(path=str(out / f"{name}-failure.png"), full_page=True)
            raise
        finally:
            write_json(out / "validation.json", report)
            context.close()
            browser.close()
    print(
        json.dumps(
            {"pass": True, "checks": report["checks"], "report": str(out / "validation.json")},
            indent=2,
        )
    )
