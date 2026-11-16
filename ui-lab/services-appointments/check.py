"""Task-based checks for the isolated Appointments preview; no Django imports."""

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from capture import LAB, SIZES, axe_result, server_module
from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent / "evidence"


async def run_case(browser, origin, width, height, theme):
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme=theme,
        reduced_motion="no-preference",
        service_workers="block",
    )
    await context.add_init_script("localStorage.setItem('phoenixTheme','untouched-sentinel')")
    page = await context.new_page()
    checks, errors, requests, failures, audits = [], [], [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("requestfailed", lambda request: failures.append(request.url))
    page.on(
        "request",
        lambda request: requests.append(
            {"url": request.url.removeprefix(origin), "method": request.method}
        ),
    )
    await page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(origin + "/") and route.request.method == "GET"
            else route.abort()
        ),
    )

    def check(value, name):
        checks.append({"name": name, "pass": bool(value)})
        if not value:
            raise AssertionError(name)

    async def open_preview(scenario="populated", **query):
        await page.goto(
            origin
            + "/services-appointments/dist/?"
            + urlencode({"scenario": scenario, "theme": theme, **query}),
            wait_until="networkidle",
        )
        await page.wait_for_function("window.labReady===true")
        await page.evaluate("document.fonts.ready")

    async def ids():
        return await page.locator("main [data-entry-id]").evaluate_all(
            '(rows)=>rows.map(r=>r.dataset.entryKind+":"+r.dataset.entryId)'
        )

    async def reset():
        await page.locator("form [data-local-list]").click()

    async def submit():
        await page.locator("button[type=submit]").click()

    async def audit(name):
        result = await axe_result(page)
        audits.append({"state": name, **result})
        check(not result["violations"], f"{name}: no axe violations")

    async def screenshot(name):
        if width == 390 and theme == "dark":
            await page.screenshot(
                path=str(OUT / "screenshots" / f"{name}-390-dark.png"), animations="disabled"
            )

    try:
        await open_preview()
        check(
            await ids()
            == [
                "request:701",
                "request:702",
                "request:703",
                "appointment:801",
                "appointment:802",
                "appointment:803",
                "appointment:804",
                "appointment:805",
            ],
            "all supplied rows, kinds and order",
        )
        # A user's unapplied filters must survive theme switching.
        await page.locator("#id_q").fill("Unsubmitted draft")
        await page.locator(".advanced-filters summary").click()
        await page.locator("#id_source").select_option("online")
        await page.locator("[data-theme-toggle]").click()
        check(
            await page.locator("#id_q").input_value() == "Unsubmitted draft"
            and await page.locator("#id_source").input_value() == "online",
            "theme preserves filter draft",
        )
        check(
            await page.locator(".advanced-filters").get_attribute("open") is not None,
            "theme preserves disclosure",
        )
        await page.locator("[data-theme-toggle]").click()
        check(
            await page.evaluate("localStorage.getItem('phoenixTheme')") == "untouched-sentinel",
            "production preference untouched",
        )
        check(
            await page.evaluate(
                "Object.keys(localStorage).every(key=>['phoenixTheme','mm-services-lab-theme'].includes(key))"
            ),
            "only lab preference written",
        )
        await reset()
        await page.locator("#id_q").fill("Jamie")
        await page.locator("#id_q").press("Enter")
        check(
            await ids() == ["request:701", "appointment:801"],
            "Enter applies scoped synthetic search",
        )
        check("q=Jamie" in page.url, "search query retained")
        await page.locator(".workspace-tabs a").nth(1).click()
        check(
            await ids() == ["request:701", "request:702", "request:703"],
            "follow-up retains request identity",
        )
        check("state=needs_follow_up" in page.url, "follow-up uses existing state parameter")
        if await page.locator(".advanced-filters").get_attribute("open") is None:
            await page.locator(".advanced-filters summary").click()
        await page.locator("#id_source").select_option("online")
        await page.locator("#id_classification").select_option("LEAD")
        await submit()
        check(await ids() == ["request:701"], "combined source/classification/follow-up filters")
        await audit("expanded filters")
        await screenshot("filters")
        before = len(requests)
        await page.get_by_role("link", name="View Jamie Rivera", exact=True).click()
        check(
            await page.locator("#routePreview").evaluate("(el)=>el.open"),
            "detail opens route review",
        )
        check(
            await page.locator("#route-name").inner_text() == "staff_lead_detail"
            and await page.locator("#route-path").inner_text() == "/crm/staff/leads/701/",
            "request detail route and identifier preserved",
        )
        await audit("route dialog")
        await screenshot("route")
        await page.keyboard.press("Escape")
        check(
            await page.get_by_role("link", name="View Jamie Rivera", exact=True).evaluate(
                "(el)=>el===document.activeElement"
            ),
            "dialog return focus",
        )
        check(len(requests) == before, "route preview sends no network request")
        check(
            await page.locator("#id_classification").input_value() == "LEAD",
            "route preview preserves filters",
        )
        await reset()
        if await page.locator(".advanced-filters").get_attribute("open") is None:
            await page.locator(".advanced-filters summary").click()
        await page.locator("#id_staff").select_option("91")
        await submit()
        check(
            await ids() == ["appointment:801", "appointment:802"],
            "staff filter excludes free-text request preference",
        )
        await reset()
        await page.locator("#id_service").select_option("42")
        await submit()
        check(
            await ids() == ["request:703", "appointment:802", "appointment:803", "appointment:805"],
            "service filter preserves both record kinds",
        )
        await reset()
        await page.locator("#id_source").select_option("unknown")
        await submit()
        check(
            await ids() == ["appointment:803", "appointment:805"], "unspecified sources preserved"
        )
        await reset()
        await page.locator("#id_classification").select_option("unknown")
        await submit()
        check(
            await ids() == ["request:703"] and await page.locator("main .client-link").count() == 0,
            "unknown classification does not invent client link",
        )
        await reset()
        await page.locator("#id_state").select_option("no_show")
        await submit()
        check(await ids() == ["appointment:804"], "No Show state retained")
        await reset()
        await page.get_by_role("link", name="New Appointment", exact=True).click()
        check(
            await page.locator("#route-name").inner_text() == "appointment_create"
            and await page.locator("#route-path").inner_text() == "/appointments/create/",
            "creation stays on established route",
        )
        await page.keyboard.press("Escape")
        await page.get_by_role("link", name="Create Request", exact=True).click()
        check(
            await page.locator("#route-name").inner_text() == "staff_lead_create",
            "request creation stays distinct",
        )
        await page.keyboard.press("Escape")
        await page.get_by_role("link", name="Request history", exact=True).click()
        check(
            await page.locator("#route-path").inner_text() == "/crm/staff/leads/?status_group=all",
            "historical request query retained",
        )
        await page.keyboard.press("Escape")
        if width < 1200:
            trigger = page.locator("[data-open]")
            await trigger.click()
            check(await page.locator("#navigationDrawer").evaluate("(el)=>el.open"), "drawer opens")
            for _ in range(12):
                await page.keyboard.press("Tab")
                check(
                    await page.evaluate(
                        "document.getElementById('navigationDrawer').contains(document.activeElement)"
                    ),
                    "drawer contains keyboard focus",
                )
            await audit("navigation drawer")
            await screenshot("navigation")
            await page.keyboard.press("Escape")
            check(
                await trigger.evaluate("(el)=>el===document.activeElement"),
                "drawer Escape returns focus",
            )
            await trigger.click()
            await page.locator("#navigationDrawer [data-route=staff_client_list]").click()
            # Native close events are queued; the handoff opens the next dialog
            # from that event, after focus has returned to the visible trigger.
            await page.locator("#routePreview").wait_for(state="visible")
            check(
                await page.locator("#routePreview").evaluate("(el)=>el.open"),
                "drawer hands off to route review",
            )
            await page.keyboard.press("Escape")
            check(
                await trigger.evaluate("(el)=>el===document.activeElement"),
                "drawer handoff returns focus to visible trigger",
            )
        account = page.locator("[data-account-toggle]")
        await account.click()
        check(await account.get_attribute("aria-expanded") == "true", "account opens")
        await audit("account popup")
        await page.keyboard.press("Escape")
        check(
            await account.get_attribute("aria-expanded") == "false"
            and await account.evaluate("(el)=>el===document.activeElement"),
            "account Escape returns focus",
        )

        # Verify supplied permission projections without executing authorization.
        for scenario, writes, appointments, requests_count in [
            ("admin", True, 5, 3),
            ("staff", True, 5, 3),
            ("accountant", False, 5, 3),
            ("viewer", False, 5, 3),
            ("read-only", False, 5, 3),
            ("request-only", True, 0, 3),
            ("appointments-only", True, 5, 0),
        ]:
            await open_preview(scenario)
            check(
                await page.locator("main [data-entry-kind=appointment]").count() == appointments
                and await page.locator("main [data-entry-kind=request]").count() == requests_count,
                f"{scenario}: supplied row scope",
            )
            check(
                await page.locator("main [data-route=appointment_create]").count()
                == int(writes and appointments > 0),
                f"{scenario}: appointment creation visibility",
            )
            check(
                await page.locator("main [data-route=staff_lead_create]").count()
                == int(writes and requests_count > 0),
                f"{scenario}: request creation visibility",
            )
            check(
                await page.locator(
                    "main [data-route=appointment_update],main [data-route=staff_lead_update]"
                ).count()
                == (appointments + requests_count if writes else 0),
                f"{scenario}: edit visibility",
            )
            check(
                await page.get_by_role("link", name="Request history", exact=True).count()
                == int(requests_count > 0),
                f"{scenario}: request history visibility",
            )
        await open_preview("locked")
        check(
            await page.locator(
                'main form,main [data-entry-id],main [data-route$="_create"]'
            ).count()
            == 0,
            "unavailable does not expose records or writes",
        )
        check(
            "0 records" not in await page.locator("main").inner_text(),
            "unavailable differs from zero",
        )
        await open_preview("invalid")
        check(
            await page.locator("#id_source").get_attribute("aria-invalid") == "true"
            and not await ids(),
            "invalid filter produces associated error and no rows",
        )
        await page.locator("#id_source").select_option("online")
        await submit()
        check(
            len(await ids()) == 4 and await page.locator("[aria-invalid=true]").count() == 0,
            "valid resubmission clears error",
        )
        await open_preview(status="scheduled")
        check(
            await ids() == ["appointment:801", "appointment:805"],
            "historical status bookmark accepted",
        )
        await open_preview(status="scheduled", state="cancelled")
        check(await ids() == ["appointment:803"], "state takes precedence over historical status")
        await open_preview(
            "pagination",
            q="Synthetic",
            source="online",
            state="scheduled",
            classification="ACTIVE",
            staff="91",
            service="41",
        )
        check(len(await ids()) == 50, "existing fifty-row page size")
        next_link = page.get_by_role("link", name="Next", exact=True)
        href = await next_link.get_attribute("href")
        check(
            all(
                f"{key}={value}" in href
                for key, value in [
                    ("q", "Synthetic"),
                    ("source", "online"),
                    ("state", "scheduled"),
                    ("classification", "ACTIVE"),
                    ("staff", "91"),
                    ("service", "41"),
                    ("page", "2"),
                ]
            ),
            "pagination preserves all filters",
        )
        await next_link.click()
        check(
            await ids() == ["appointment:950", "appointment:951"],
            "second page has remaining supplied rows",
        )
        await page.get_by_role("link", name="Previous", exact=True).click()
        check(len(await ids()) == 50, "previous page restores first fifty")
        await open_preview("error")
        await page.get_by_role("button", name="Retry preview", exact=True).click()
        check(
            await page.locator(".mm-notice.error").count() == 0 and len(await ids()) == 8,
            "local error recovery retains records",
        )
        await open_preview(q="<img src=x onerror=alert(1)>")
        check(
            await page.locator("#id_q").input_value() == "<img src=x onerror=alert(1)>"
            and await page.locator("main img").count() == 0,
            "search text escaped without markup injection",
        )
        await open_preview(q="x" * 161)
        check(
            await page.locator("#id_q").get_attribute("aria-invalid") == "true" and not await ids(),
            "overlong bookmarked query returns error without rows",
        )
        await open_preview("long", q="accessibility review")
        check(len(await ids()) == 8, "search covers supplied long-content labels")
        await open_preview()
        await page.keyboard.press("Tab")
        for _ in range(18):
            await page.keyboard.press("Tab")
            result = await page.evaluate(
                """()=>{const e=document.activeElement,r=e.getBoundingClientRect(),s=getComputedStyle(e);return {tag:e.tagName,outline:s.outlineStyle,width:s.outlineWidth,top:r.top,bottom:r.bottom,chrome:!!e.closest('.topbar')};}"""
            )
            check(
                result["outline"] != "none" and float(result["width"].replace("px", "")) >= 2,
                "keyboard focus visible",
            )
            check(
                result["top"] >= (0 if result["chrome"] else 63) and result["bottom"] <= height + 1,
                "focus not hidden by sticky header or viewport",
            )
        await screenshot("focus")
        check(not errors and not failures, "no browser errors or failed requests")
        check(
            all(r["url"].startswith("/") and r["method"] == "GET" for r in requests),
            "all requests remain local GETs",
        )
    except Exception as error:
        checks.append({"name": str(error), "pass": False})
    await context.close()
    return {
        "width": width,
        "theme": theme,
        "motion": "no-preference",
        "checks": checks,
        "axe": audits,
        "browserErrors": errors,
        "failedRequests": failures,
        "requests": requests,
        "pass": all(c["pass"] for c in checks),
    }


async def supplemental(browser, origin):
    results = []
    for theme in ("light", "dark"):
        for width, dpr, label in [(320, 1, "reflow-320"), (720, 2, "zoom-emulation-720")]:
            context = await browser.new_context(
                viewport={"width": width, "height": 900},
                device_scale_factor=dpr,
                color_scheme=theme,
                reduced_motion="reduce",
            )
            page = await context.new_page()
            await page.goto(
                f"{origin}/services-appointments/dist/?theme={theme}&scenario=long",
                wait_until="networkidle",
            )
            await page.wait_for_function("window.labReady===true")
            await page.evaluate("document.fonts.ready")
            result = await page.evaluate("""()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth,
              overflowing:[...document.querySelectorAll('main *')].filter(e=>e.checkVisibility()&&e.getBoundingClientRect().right>innerWidth+1).map(e=>e.className)})""")
            await page.screenshot(
                path=str(OUT / "screenshots" / f"{label}-{theme}.png"),
                full_page=True,
                animations="disabled",
            )
            results.append(
                {
                    "name": label,
                    "theme": theme,
                    "dpr": dpr,
                    **result,
                    "pass": result["documentWidth"] <= width + 1 and not result["overflowing"],
                }
            )
            await context.close()
    return results


async def main():
    server = server_module.make_server(root=LAB)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        async with async_playwright() as playwright:
            executable = os.environ.get("PWA_CHROMIUM")
            browser = await playwright.chromium.launch(
                **({"executable_path": executable} if executable else {}), headless=True
            )
            cases = []
            for width, height in SIZES:
                for theme in ("light", "dark"):
                    result = await run_case(browser, origin, width, height, theme)
                    cases.append(result)
                    print(
                        f"{width} {theme}: {sum(c['pass'] for c in result['checks'])}/{len(result['checks'])} checks",
                        flush=True,
                    )
                    if not result["pass"]:
                        print([c for c in result["checks"] if not c["pass"]], flush=True)
            extra = await supplemental(browser, origin)
            output = {
                "browser": browser.version,
                "cases": cases,
                "reflow": extra,
                "checks": sum(len(c["checks"]) for c in cases),
                "passedChecks": sum(sum(x["pass"] for x in c["checks"]) for c in cases),
                "pass": all(c["pass"] for c in cases + extra),
            }
            (OUT / "interactions.json").write_text(json.dumps(output, indent=2) + "\n")
            await browser.close()
            print(
                json.dumps({key: output[key] for key in ["checks", "passedChecks", "pass"]}),
                flush=True,
            )
            if not output["pass"]:
                raise SystemExit(1)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
