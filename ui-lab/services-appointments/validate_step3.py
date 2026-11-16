"""Connected UI Lab checks. Static loopback GETs only; no Django/database imports."""

import asyncio
import importlib.util
import json
import os
import threading
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "ui-lab"
OUT = LAB / "services-appointments/evidence/step3"
BROWSER = os.environ.get("PWA_CHROMIUM")
AXE = (LAB / "services-dashboard/tools/node_modules/axe-core/axe.min.js").read_text()
spec = importlib.util.spec_from_file_location(
    "lab_server", LAB / "services-dashboard/tools/serve.py"
)
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


async def prepare(browser, origin, width=1440, theme="light"):
    context = await browser.new_context(
        viewport={"width": width, "height": 1000 if width > 390 else 844},
        color_scheme=theme,
        reduced_motion="reduce",
        service_workers="block",
    )
    page = await context.new_page()
    issues = {"errors": [], "failures": [], "requests": []}
    page.on("pageerror", lambda error: issues["errors"].append(str(error)))
    page.on(
        "requestfailed",
        lambda request: issues["failures"].append({"url": request.url, "failure": request.failure}),
    )
    page.on(
        "request",
        lambda request: issues["requests"].append({"url": request.url, "method": request.method}),
    )
    await page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(origin + "/") and route.request.method == "GET"
            else route.abort()
        ),
    )
    return context, page, issues


async def open_page(page, origin, query):
    await page.goto(origin + "/services-appointments/dist/?" + query, wait_until="networkidle")
    await page.wait_for_function("() => window.labReady===true")
    await page.evaluate("document.fonts.ready")


async def capture(page, label):
    await page.evaluate("window.scrollTo(0,0)")
    for full in (False, True):
        await page.screenshot(
            path=str(OUT / "screenshots" / f"{label}-{'full' if full else 'viewport'}.png"),
            full_page=full,
            animations="disabled",
        )


async def audit(page):
    await page.evaluate(AXE)
    return await page.evaluate(
        """async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),incomplete:r.incomplete.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),passes:r.passes.length}}"""
    )


async def metrics(page):
    return await page.evaluate("""()=>{
    const visible=e=>e.checkVisibility({checkVisibilityCSS:true})&&!e.closest('dialog:not([open])');
    const controls=[...document.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,summary')].filter(visible);
    const small=controls.filter(e=>{const target=e.matches('[type=checkbox],[type=radio]')?e.closest('label'):e;const r=target.getBoundingClientRect();return r.width<43.9||r.height<43.9}).map(e=>({name:e.getAttribute('aria-label')||e.textContent.trim()||e.name,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}));
    return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,font:getComputedStyle(document.body).fontFamily,theme:document.documentElement.dataset.bsTheme,smallTargets:small,h1:document.querySelectorAll('h1').length,overflow:[...document.querySelectorAll('main *')].filter(e=>visible(e)&&e.getBoundingClientRect().right>innerWidth+1).map(e=>e.className)};
    }""")


async def matrix_case(browser, origin, view, width, theme, query="", label=None):
    context, page, issues = await prepare(browser, origin, width, theme)
    result = {"view": view, "width": width, "theme": theme, "query": query}
    try:
        await open_page(page, origin, f"view={view}&theme={theme}&{query}")
        result["metrics"] = await metrics(page)
        result["axe"] = await audit(page)
        await capture(page, label or f"{view}-{width}-{theme}")
        result["pass"] = (
            result["metrics"]["documentWidth"] <= width + 1
            and not result["metrics"]["smallTargets"]
            and not result["metrics"]["overflow"]
            and result["metrics"]["h1"] == 1
            and not result["axe"]["violations"]
            and not issues["errors"]
            and not issues["failures"]
        )
    except Exception as error:
        result["exception"] = str(error)
        result["pass"] = False
    result.update(issues)
    await context.close()
    print(
        ("PASS " if result["pass"] else "FAIL ") + (label or f"{view}-{width}-{theme}"), flush=True
    )
    return result


async def interactions(browser, origin, width, theme):
    context, page, issues = await prepare(browser, origin, width, theme)
    checks = []

    def check(ok, name):
        checks.append({"name": name, "pass": bool(ok)})
        if not ok:
            raise AssertionError(name)

    async def fill(form, values):
        for key, value in values.items():
            await form.locator(f'[name="{key}"]').fill(value)

    try:
        await open_page(page, origin, f"theme={theme}")
        await page.locator("#id_q").fill("Jamie")
        await page.locator("[data-preview-filter] button[type=submit]").click()
        check(
            await page.locator("[data-entry-id]").count() == 2,
            "synthetic search filters full supplied metadata",
        )
        await page.get_by_role("link", name="Reset", exact=True).click()
        await page.get_by_role("link", name="New Appointment", exact=True).click()
        check(
            await page.locator("h1").inner_text() == "New appointment", "connected creation screen"
        )
        form = page.locator("[data-appointment-form]")
        await form.locator("[type=submit]").click()
        check(await page.locator(".error-summary").count() == 1, "empty appointment validation")
        await fill(
            form,
            {
                "title": "Preserved synthetic draft",
                "start_time": "2026-11-16T09:00",
                "end_time": "2026-11-16T08:00",
                "notes": "Keep this note",
            },
        )
        await page.locator("#id_client").select_option("501")
        await form.locator("[type=submit]").click()
        check(
            "End must be after Start" in await page.locator(".error-summary").inner_text(),
            "invalid appointment time range",
        )
        await page.locator("[data-open=draftClientModal]").click()
        modal = page.locator("#draftClientModal")
        await modal.locator("[type=submit]").click()
        check(await modal.locator(".error-summary").count() == 1, "inline Client validation")
        await fill(
            modal,
            {
                "new_client-first_name": "Synthetic",
                "new_client-last_name": "Person",
                "new_client-company_name": "Example Test Company",
                "new_client-email": "person@example.test",
                "new_client-phone": "+1 555 010 0123",
                "new_client-street_address": "4 Synthetic Road",
            },
        )
        await modal.locator("[type=submit]").click()
        check(
            await page.locator("#id_title").input_value() == "Preserved synthetic draft"
            and await page.locator("#id_notes").input_value() == "Keep this note",
            "Client success preserves outer draft",
        )
        check(
            (await page.locator("#id_client option:checked").inner_text()).startswith(
                "Synthetic Person"
            ),
            "inline Client selected",
        )
        await page.locator("#id_end_time").fill("2026-11-16T10:00")
        await page.locator("[data-theme-toggle]").click()
        check(
            await page.locator("#id_notes").input_value() == "Keep this note",
            "theme preserves draft",
        )
        await page.get_by_role("link", name="Back to Appointments", exact=True).click()
        await page.get_by_role("link", name="New Appointment", exact=True).click()
        check(
            await page.locator("#id_title").input_value() == "Preserved synthetic draft",
            "navigation preserves draft",
        )
        await page.locator("[data-appointment-form] [type=submit]").click()
        await page.wait_for_function('() => window.labView==="detail"')
        check(
            await page.locator("h1").inner_text() == "Preserved synthetic draft",
            "synthetic creation connects to details",
        )
        await page.get_by_role("button", name="Cancel Appointment", exact=True).click()
        check(
            await page.locator("#statusDialog").evaluate("(e)=>e.open"),
            "terminal-action confirmation preview",
        )
        await page.keyboard.press("Escape")
        check(
            not await page.locator("#statusDialog").evaluate("(e)=>e.open"), "status dialog Escape"
        )
        await page.get_by_role("button", name="Cancel Appointment", exact=True).click()
        await page.locator("[data-confirm-status]").click()
        check(
            await page.get_by_role("button", name="Cancel Appointment", exact=True).count() == 0,
            "terminal preview has no extra transitions",
        )
        await page.get_by_role("link", name="Edit appointment", exact=True).click()
        await page.locator("[data-appointment-form] [type=submit]").click()
        await page.wait_for_function('() => window.labView==="detail"')
        check(
            "Cancelled" in await page.locator("main").inner_text(),
            "editing does not reopen terminal appointment",
        )
        await open_page(page, origin, f"view=public&theme={theme}")
        await page.locator("[data-public-form] [type=submit]").click()
        await page.locator("#id_staff_member").select_option("91")
        await page.locator("[data-book-date]").first.click()
        await page.locator("[data-book-time]").first.click()
        check(
            await page.evaluate("document.activeElement.dataset.bookTime") == "09:00",
            "slot selection preserves focus",
        )
        check(
            await page.locator("[data-book-time]").first.get_attribute("aria-pressed") == "true",
            "slot selection has accessible state",
        )
        await page.locator("[data-public-form] [type=submit]").click()
        await page.locator("#id_client_type").select_option("INDIVIDUAL")
        check(
            await page.locator("#id_company_name").count() == 0,
            "Individual hides irrelevant company input",
        )
        await fill(
            page.locator("[data-public-form]"),
            {
                "first_name": "Demo",
                "last_name": "Individual",
                "email": "individual@example.test",
                "phone": "+1 555 010 0123",
            },
        )
        await page.locator("[data-public-form] [type=submit]").click()
        await fill(page.locator("[data-public-form]"), {"street_address": "12 Synthetic Street"})
        await page.locator("#id_consent").check()
        check(
            "Demo Individual" in await page.locator(".booking-review").inner_text(),
            "compact review reflects entered contact",
        )
        await page.locator('[data-step="2"]').last.click()
        check(
            await page.locator("#id_email").input_value() == "individual@example.test",
            "review editing retains contact",
        )
        await page.locator("[data-public-form] [type=submit]").click()
        await page.locator("[data-public-form] [type=submit]").click()
        await page.wait_for_function('() => window.labView==="outcome"')
        check(
            await page.locator("h1").inner_text() == "Your appointment is scheduled",
            "Book now yields Scheduled outcome",
        )
        check(
            await page.evaluate('window.labState.rows.filter(r=>r.kind==="appointment").length')
            == 6,
            "public Book now projects directly into Appointments",
        )
        await page.get_by_role("link", name="Back to booking page", exact=True).click()
        await page.locator('.step-navigation [data-step="0"]').click()
        await page.locator("[name=booking_intent][value=book_later]").check()
        for _ in range(3):
            await page.locator("[data-public-form] [type=submit]").click()
        check(
            "Not scheduled" in await page.locator(".booking-review").inner_text(),
            "mode switch clears time in proposed contact flow",
        )
        await page.locator("[data-public-form] [type=submit]").click()
        await page.wait_for_function('() => window.labView==="outcome"')
        check(
            await page.locator("h1").inner_text() == "Request received",
            "contact intent remains unscheduled",
        )
        check(
            await page.evaluate('window.labState.rows.filter(r=>r.kind==="request").length') == 4,
            "contact request appears in follow-up without another appointment",
        )
        await open_page(page, origin, f"view=request&id=703&theme={theme}")
        await page.get_by_role("link", name="Complete client details", exact=True).click()
        await fill(
            page.locator("[data-completion-form]"),
            {"company_name": "Synthetic Client Ltd.", "street_address": "3 Synthetic Avenue"},
        )
        await page.locator("[data-completion-form] [type=submit]").click()
        await page.wait_for_function('() => window.labView==="client-saved"')
        check(
            "No appointment is scheduled yet" in await page.locator("main").inner_text(),
            "Client completion does not schedule appointment",
        )
        await page.locator(".review-bar summary").click()
        await page.locator("[data-proposal-resume]").click()
        check(
            "Schedule appointment from request" in await page.locator("h1").inner_text(),
            "D4 candidate handoff retains request scheduling context",
        )
        check(
            "Casey Laurent" in await page.locator("#id_client option:checked").inner_text(),
            "completion handoff selects the completed Client",
        )
        await open_page(page, origin, f"view=detail&theme={theme}")
        await page.locator(".context-menu summary").click()
        check(
            await page.locator(".context-menu").get_attribute("open") is not None,
            "related-action disclosure opens",
        )
        await page.keyboard.press("Escape")
        check(
            await page.locator(".context-menu").get_attribute("open") is None,
            "related-action disclosure Escape closes",
        )
        await page.get_by_role("link", name="Create Invoice", exact=True).click()
        check(
            await page.locator("#routePreview").evaluate("(e)=>e.open"),
            "invoice action remains route intent with no writer",
        )
        await page.keyboard.press("Escape")
        await open_page(page, origin, f"theme={theme}")
        count_before = await page.locator("[data-entry-kind=appointment]").count()
        await page.get_by_role("link", name="Create Request", exact=True).click()
        await fill(
            page.locator("[data-request-form]"),
            {
                "first_name": "Internal",
                "last_name": "Request",
                "company_name": "Synthetic Company",
                "email": "request@example.test",
                "phone": "+1 555 010 0123",
            },
        )
        await page.locator("[data-request-form] [type=submit]").click()
        await page.wait_for_function('() => window.labView==="workspace"')
        check(
            await page.locator("[data-entry-kind=appointment]").count() == count_before,
            "internal request does not schedule appointment",
        )
        check(
            await page.locator("[data-entry-kind=request]").count() == 4,
            "internal request returns to follow-up queue",
        )
        await open_page(page, origin, f"scenario=request-only&theme={theme}")
        check(
            await page.locator("[data-entry-kind=appointment]").count() == 0
            and await page.locator("main [data-route=appointment_create]").count() == 0,
            "request-only projection excludes appointments/writes",
        )
        await open_page(page, origin, f"scenario=appointments-only&theme={theme}")
        check(
            await page.locator("[data-entry-kind=request]").count() == 0
            and await page.get_by_role("link", name="Request history", exact=True).count() == 0,
            "appointment-only projection excludes request history",
        )
        await open_page(page, origin, f"scenario=viewer&view=detail&theme={theme}")
        check(
            await page.get_by_role("link", name="Edit appointment", exact=True).count() == 0
            and await page.locator("[data-status]").count() == 0,
            "viewer details are read-only",
        )
        await open_page(page, origin, f"scenario=read-only&view=public&theme={theme}")
        check(
            await page.locator("[data-public-form]").count() == 0,
            "restricted subscription does not offer public booking writes",
        )
        await open_page(page, origin, f"scenario=pagination&theme={theme}")
        check(await page.locator("[data-entry-id]").count() == 50, "fifty-row page size")
        await page.get_by_role("link", name="Next", exact=True).click()
        check(await page.locator("[data-entry-id]").count() == 2, "pagination remaining two rows")
        await open_page(page, origin, f"theme={theme}")
        if width < 1200:
            await page.get_by_role("button", name="Open navigation", exact=True).click()
            check(
                await page.locator("#navigationDrawer").evaluate("(e)=>e.open"),
                "mobile navigation opens",
            )
            await page.keyboard.press("Escape")
            check(
                await page.evaluate('document.activeElement.getAttribute("aria-label")')
                == "Open navigation",
                "drawer returns focus",
            )
        await page.keyboard.press("Tab")
        focus = await page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
        check(focus != "none", "visible keyboard focus")
        check(
            not issues["errors"] and not issues["failures"],
            "no browser errors/failed requests during tasks",
        )
    except Exception as error:
        checks.append({"name": str(error), "pass": False})
        await page.screenshot(
            path=str(OUT / f"interaction-failure-{width}-{theme}.png"), full_page=True
        )
    await context.close()
    print(f"Tasks {width}/{theme}: {sum(c['pass'] for c in checks)}/{len(checks)}", flush=True)
    return {
        "width": width,
        "theme": theme,
        "checks": checks,
        **issues,
        "pass": all(c["pass"] for c in checks),
    }


async def main():
    OUT.mkdir(exist_ok=True, parents=True)
    (OUT / "screenshots").mkdir(exist_ok=True)
    server = server_module.make_server(root=LAB)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                **({"executable_path": BROWSER} if BROWSER else {}), headless=True
            )
            tasks = []
            cases = []
            for width, theme in [(1440, "light"), (768, "dark"), (390, "light"), (320, "dark")]:
                tasks.append(await interactions(browser, origin, width, theme))
            if not os.environ.get("STEP3_TASKS_ONLY"):
                for view in ["workspace", "detail", "form", "public", "request"]:
                    for width in [1440, 768, 390, 320]:
                        for theme in ["light", "dark"]:
                            cases.append(await matrix_case(browser, origin, view, width, theme))
                for view, query, label in [
                    ("workspace", "scenario=long", "long"),
                    ("workspace", "scenario=empty", "empty"),
                    ("workspace", "scenario=invalid", "invalid"),
                    ("workspace", "scenario=locked", "locked"),
                    ("workspace", "scenario=loading", "loading"),
                    ("workspace", "scenario=error", "error"),
                    ("public", "scenario=no-slots", "no-slots"),
                    ("public", "scenario=read-only", "public-read-only"),
                    ("request", "id=703", "client-completion"),
                    ("outcome", "result=request", "request-outcome"),
                    ("outcome", "result=scheduled", "scheduled-outcome"),
                ]:
                    for theme in ["light", "dark"]:
                        cases.append(
                            await matrix_case(
                                browser, origin, view, 390, theme, query, f"{label}-390-{theme}"
                            )
                        )
            result = {
                "browser": browser.version,
                "cases": cases,
                "tasks": tasks,
                "pass": all(c["pass"] for c in cases + tasks),
            }
            (
                OUT
                / ("tasks-only.json" if os.environ.get("STEP3_TASKS_ONLY") else "validation.json")
            ).write_text(json.dumps(result, indent=2) + "\n")
            await browser.close()
            print(
                json.dumps(
                    {
                        "cases": len(cases),
                        "taskChecks": sum(len(x["checks"]) for x in tasks),
                        "pass": result["pass"],
                    }
                ),
                flush=True,
            )
            if not result["pass"]:
                raise SystemExit(1)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
