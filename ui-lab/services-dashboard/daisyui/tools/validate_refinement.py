"""Reproducible standalone Chromium evidence. No Django/database/provider access."""

import asyncio
import gzip
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from serve import make_server

LAB = Path(__file__).resolve().parents[2]
OUT = LAB / "daisyui/evidence/step4"
SHOTS = OUT / "screenshots"
SHOTS.mkdir(exist_ok=True)
STATES = [
    "populated",
    "empty",
    "future",
    "past",
    "appointments-locked",
    "invoices-locked",
    "booking-locked",
    "locked",
    "long",
    "staff",
    "viewer",
    "accountant",
    "admin",
    "read-only",
    "grace",
    "sharing-absent",
    "welcome",
    "guide",
    "loading",
    "error",
    "financial-edge",
    "timezone-boundary",
]
SIZES = [(1440, 900), (768, 1024), (390, 844)]
CHROME = os.environ.get("PWA_CHROMIUM") or None
METRICS = r"""()=>{
 const visible=e=>!!e&&e.checkVisibility({checkVisibilityCSS:true,checkOpacity:true})&&!e.closest('details:not([open])');
 const rect=e=>{if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x,y:r.y+scrollY,width:r.width,height:r.height}};
 const textNodes=[];const walker=document.createTreeWalker(document.querySelector('main'),NodeFilter.SHOW_TEXT);let n;while(n=walker.nextNode()){if(n.textContent.trim()&&visible(n.parentElement))textNodes.push({text:n.textContent.trim().slice(0,80),size:parseFloat(getComputedStyle(n.parentElement).fontSize)})}
 const controls=[...document.querySelectorAll('a,button,input:not([type=hidden]),summary')].filter(visible).map(e=>({label:e.getAttribute('aria-label')||e.textContent.trim(),tag:e.tagName,...rect(e)}));
 const overflow=[...document.querySelectorAll('main *')].filter(e=>visible(e)&&e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent.trim().slice(0,60),...rect(e)}));
 const tokens=[];const all=document.createTreeWalker(document.querySelector('main'),NodeFilter.SHOW_TEXT);let node;while(node=all.nextNode())tokens.push(...node.textContent.trim().split(/\s+/).filter(Boolean));const mainTokens=tokens.sort();
 return{viewport:{width:innerWidth,height:innerHeight,dpr:devicePixelRatio},document:{width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight},appointments:rect(document.querySelector('.appointments-panel')),followup:rect(document.querySelector('.followup-panel')),firstAppointment:rect(document.querySelector('[data-record=appointment]')),firstRequest:rect(document.querySelector('[data-record=request]')),visibleAppointments:[...document.querySelectorAll('[data-record=appointment]')].filter(visible).length,visibleRequests:[...document.querySelectorAll('[data-record=request]')].filter(visible).length,share:rect(document.getElementById('booking-url')),smallText:textNodes.filter(n=>n.size<14),smallTargets:controls.filter(c=>c.width<43.9||c.height<43.9),overflow,mainTokens,routeIntents:[...document.querySelectorAll('main [data-route]')].map(e=>({route:e.dataset.route,id:e.dataset.id||null,query:e.dataset.query||'',href:e.getAttribute('href')})),theme:document.documentElement.dataset.bsTheme,font:getComputedStyle(document.body).fontFamily,fontsReady:document.fonts.check('16px Manrope'),state:window.labState};
}"""
AXE = """async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return{passes:r.passes.length,incomplete:r.incomplete.map(v=>({id:v.id,count:v.nodes.length,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary,checks:n.any}))})),violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary})).slice(0,5)}))};}"""


def check(condition, message, errors):
    if not condition:
        errors.append(message)


async def render_case(browser, origin, framework, state, width, height, theme, sem):
    async with sem:
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
            color_scheme=theme,
            reduced_motion="reduce",
            service_workers="block",
        )
        page = await context.new_page()
        errors = []
        failed = []
        requests = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on(
            "requestfailed", lambda req: failed.append({"url": req.url, "failure": req.failure})
        )
        page.on("request", lambda req: requests.append({"url": req.url, "method": req.method}))
        await page.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.url.startswith(origin + "/") and route.request.method == "GET"
                else route.abort()
            ),
        )
        label = f"{framework}-{state}-{width}-{theme}"
        result = {
            "framework": framework,
            "state": state,
            "width": width,
            "height": height,
            "theme": theme,
            "checks": [],
        }
        try:
            response = await page.goto(
                f"{origin}/{framework}/dist/?state={state}&theme={theme}", wait_until="networkidle"
            )
            await page.wait_for_function("window.labReady===true")
            await page.evaluate("document.fonts.ready")
            await page.screenshot(path=str(SHOTS / f"{label}-viewport.png"))
            await page.screenshot(path=str(SHOTS / f"{label}-full.png"), full_page=True)
            metrics = await page.evaluate(METRICS)
            await page.add_script_tag(path=str(LAB / "tools/node_modules/axe-core/axe.min.js"))
            axe = await page.evaluate(AXE)
            result.update(
                {
                    "screenshots": [
                        f"screenshots/{label}-viewport.png",
                        f"screenshots/{label}-full.png",
                    ],
                    "metrics": metrics,
                    "axe": axe,
                }
            )
            checks = result["checks"]
            check(response.status == 200, "HTTP response was not 200", checks)
            check(metrics["document"]["width"] <= width + 1, "Document overflow", checks)
            check(not metrics["overflow"], "Main content overflow", checks)
            check(not metrics["smallText"], "Working text below 14px", checks)
            check(not metrics["smallTargets"], "Targets below project 44px size", checks)
            check(not axe["violations"], "Axe WCAG-tag violations", checks)
            check(
                metrics["font"].startswith("Manrope") and metrics["fontsReady"],
                "Font missing",
                checks,
            )
            check(
                all(r["method"] == "GET" and f"/{framework}/dist/" in r["url"] for r in requests),
                "Asset/request isolation failure",
                checks,
            )
            if state == "populated":
                check(
                    metrics["visibleAppointments"] == (3 if width < 768 else 5),
                    "Appointment preview count",
                    checks,
                )
                check(
                    metrics["visibleRequests"] == (3 if width < 768 else 5),
                    "Request preview count",
                    checks,
                )
                if width == 1440:
                    check(
                        metrics["appointments"]["y"] <= 240 and metrics["followup"]["y"] <= 240,
                        "V1 headings",
                        checks,
                    )
                    bottoms = await page.locator("[data-record=appointment]").evaluate_all(
                        "(els)=>els.slice(0,3).map(e=>e.getBoundingClientRect().bottom)"
                    )
                    check(max(bottoms) <= 900, "V1 appointment rows", checks)
                    bottoms = await page.locator("[data-record=request]").evaluate_all(
                        "(els)=>els.slice(0,3).map(e=>e.getBoundingClientRect().bottom)"
                    )
                    check(max(bottoms) <= 900, "V1 follow-up rows", checks)
                if width == 768:
                    check(metrics["firstAppointment"]["y"] <= 320, "V2 first appointment", checks)
                    check(
                        metrics["followup"]["y"] <= 820 and metrics["firstRequest"]["y"] <= 1024,
                        "V2 follow-up",
                        checks,
                    )
                if width == 390:
                    check(metrics["firstAppointment"]["y"] <= 300, "V3 first appointment", checks)
                    check(
                        metrics["followup"]["y"] <= 960 and metrics["firstRequest"]["y"] <= 1120,
                        "V3 follow-up",
                        checks,
                    )
                    check(metrics["share"]["width"] >= 300, "V5 booking input width", checks)
            if state == "viewer":
                check(
                    await page.locator("main .settings-links").count() == 0,
                    "Viewer settings actions",
                    checks,
                )
                check(
                    await page.locator("[data-setup-open]").count() == 0,
                    "Viewer setup access",
                    checks,
                )
                check(
                    await page.locator(".financial-panel .invoice-link").count() == 3,
                    "Viewer invoice read access",
                    checks,
                )
            if state in ["appointments-locked", "locked"]:
                check(
                    await page.locator("[data-record=appointment]").count() == 0,
                    "Locked appointment records exposed",
                    checks,
                )
            if state in ["invoices-locked", "locked"]:
                check(
                    await page.locator("main .invoice-link").count() == 0,
                    "Locked invoice records exposed",
                    checks,
                )
            if state in ["booking-locked", "sharing-absent", "locked", "empty"]:
                check(
                    await page.locator("#booking-url").count() == 0,
                    "Share condition changed",
                    checks,
                )
        except Exception as exc:
            result["checks"].append(type(exc).__name__ + ": " + str(exc)[:600])
        result.update({"page_errors": errors, "failed_requests": failed, "requests": requests})
        if errors:
            result["checks"].append("Unexpected JavaScript error")
        if failed:
            result["checks"].append("Failed required request")
        await context.close()
        return result


async def interactions(browser, origin, framework, width, height, theme):
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=1,
        permissions=["clipboard-read", "clipboard-write"],
        reduced_motion="reduce",
    )
    page = await context.new_page()
    page_errors = []
    requests = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.on("request", lambda req: requests.append({"url": req.url, "method": req.method}))
    await page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(origin + "/") and route.request.method == "GET"
            else route.abort()
        ),
    )
    record = {"framework": framework, "width": width, "theme": theme, "passed": [], "failures": []}

    async def require(ok, label):
        if not ok:
            raise AssertionError(label)
        record["passed"].append(label)

    try:
        await page.goto(f"{origin}/{framework}/dist/?theme={theme}", wait_until="networkidle")
        await page.wait_for_function("window.labReady")
        await page.keyboard.press("Tab")
        await require(
            await page.locator(".skip-link").evaluate("(e)=>e===document.activeElement"),
            "skip link is first focus",
        )
        await page.keyboard.press("Enter")
        await require(
            await page.locator("main").evaluate("(e)=>e===document.activeElement"),
            "skip targets main",
        )
        if width < 768:
            details = page.locator("[data-preview-more]").first
            await details.locator("summary").click()
            await require(await details.evaluate("(e)=>e.open"), "mobile disclosure opens")
        await page.locator("[data-theme-toggle]").click()
        await require(
            await page.locator("html").get_attribute("data-bs-theme") != theme, "theme switches"
        )
        if width < 768:
            await require(await details.evaluate("(e)=>e.open"), "theme preserves disclosure")
        await page.locator("[data-theme-toggle]").click()
        if width < 1200:
            await page.locator("[data-menu-open]").click()
            await page.locator("#navigationDrawer").wait_for(state="visible")
            await page.screenshot(path=str(SHOTS / f"{framework}-navigation-{width}-{theme}.png"))
            await page.keyboard.press("Shift+Tab")
            await require(
                await page.locator("#navigationDrawer").evaluate(
                    "(e)=>e.contains(document.activeElement)"
                ),
                "navigation traps keyboard focus",
            )
            await page.keyboard.press("Escape")
            await page.locator("#navigationDrawer").wait_for(state="hidden")
            await require(
                await page.locator("[data-menu-open]").evaluate("(e)=>e===document.activeElement"),
                "navigation returns focus",
            )
            # A navigation handoff must remain a local preview, including from the open drawer.
            await page.locator("[data-menu-open]").click()
            await page.locator("#navigationDrawer").wait_for(state="visible")
            await page.locator("#navigationDrawer [data-route=appointment_list]").first.click()
            await page.locator("#routePreview").wait_for(state="visible")
            await page.locator("[data-close=routePreview]").click()
            await page.locator("#routePreview").wait_for(state="hidden")
            record["passed"].append("drawer navigation previews without network")
        await page.locator("[data-account-toggle]").click()
        await page.locator("#account-menu").wait_for(state="visible")
        await page.keyboard.press("ArrowDown")
        await require(
            await page.locator("#account-menu").evaluate("(e)=>e.contains(document.activeElement)"),
            "account keyboard navigation",
        )
        await page.keyboard.press("Escape")
        await page.locator("#account-menu").wait_for(state="hidden")
        await require(
            await page.locator("[data-account-toggle]").evaluate("(e)=>e===document.activeElement"),
            "account returns focus",
        )
        await page.locator("[data-record=appointment]").first.click()
        await page.locator("#routePreview").wait_for(state="visible")
        await require(
            await page.locator("#routeName").inner_text() == "appointment_detail",
            "appointment route intent",
        )
        await page.locator("[data-close=routePreview]").click()
        await page.locator("#routePreview").wait_for(state="hidden")
        await page.locator(".followup-panel .panel-header [data-route]").click()
        await page.locator("#routePreview").wait_for(state="visible")
        await require(
            await page.locator("#routePath").inner_text() == "/appointments/?state=needs_follow_up",
            "follow-up query retained",
        )
        await page.locator("[data-close=routePreview]").click()
        await page.locator("#routePreview").wait_for(state="hidden")
        await page.locator("[data-copy]").click()
        await page.wait_for_function(
            "document.querySelector('#live-status').textContent==='Link copied'"
        )
        await require(
            await page.evaluate("navigator.clipboard.readText()")
            == "https://motionmate.example.test/book/ui-lab-services/",
            "clipboard contains exact fixture URL",
        )
        await page.locator("[data-setup-open]").click()
        await page.locator("#onboardingWelcomeModal").wait_for(state="visible")
        await page.get_by_role("button", name="Choose journey").first.click()
        await page.locator("#onboardingGuidePanel").wait_for(state="visible")
        await page.keyboard.press("Escape")
        await require(
            await page.locator("#onboardingGuidePanel").is_visible(),
            "guide retains static Escape behavior",
        )
        await page.get_by_role("button", name="Continue later", exact=True).click()
        await page.locator("#onboardingGuidePanel").wait_for(state="hidden")
        await require(
            await page.evaluate(
                "window.labEvents.some(e=>e.type==='onboarding'&&e.fields.onboarding_action==='continue_later'&&e.fields.current_step_key==='complete_business_profile')"
            ),
            "setup hidden-field intent recorded",
        )
        await page.goto(
            f"{origin}/{framework}/dist/?copy=denied&theme={theme}", wait_until="networkidle"
        )
        await page.locator("[data-copy]").click()
        await require(
            "Copy unavailable" in await page.locator("#live-status").inner_text(),
            "clipboard denial feedback",
        )
        await page.screenshot(
            path=str(SHOTS / f"{framework}-copy-denied-{width}-{theme}.png"), full_page=True
        )
        # CSS zoom does not change media-query breakpoints. Emulate desktop browser
        # zoom using half the CSS viewport and doubled DPR, keeping physical dimensions.
        await page.goto(f"{origin}/{framework}/dist/?theme={theme}", wait_until="networkidle")
        if width >= 768:
            zoom = await browser.new_context(
                viewport={"width": width // 2, "height": height // 2},
                device_scale_factor=2,
                color_scheme=theme,
                reduced_motion="reduce",
            )
            zp = await zoom.new_page()
            await zp.goto(f"{origin}/{framework}/dist/?theme={theme}", wait_until="networkidle")
            await zp.evaluate("document.fonts.ready")
            await require(
                await zp.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),
                "200 percent desktop zoom layout emulation",
            )
            await zp.screenshot(
                path=str(SHOTS / f"{framework}-zoom200-{width}-{theme}.png"), full_page=True
            )
            await zoom.close()
        await page.set_viewport_size({"width": 320, "height": 844})
        await require(
            await page.evaluate("document.documentElement.scrollWidth<=321"), "320px reflow"
        )
        await page.screenshot(
            path=str(SHOTS / f"{framework}-reflow320-{theme}.png"), full_page=True
        )
    except Exception as exc:
        record["failures"].append(type(exc).__name__ + ": " + str(exc)[:700])
    record["page_errors"] = page_errors
    record["requests"] = requests
    if page_errors:
        record["failures"].append("Unexpected interaction JavaScript error")
    if any(r["method"] != "GET" or f"/{framework}/dist/" not in r["url"] for r in requests):
        record["failures"].append("Network isolation failure")
    await context.close()
    return record


async def normal_motion(browser, origin, framework, width, height):
    context = await browser.new_context(
        viewport={"width": width, "height": height}, reduced_motion="no-preference"
    )
    page = await context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    await page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(origin + "/") and route.request.method == "GET"
            else route.abort()
        ),
    )
    result = {"framework": framework, "width": width, "passed": [], "failures": []}
    try:
        await page.goto(
            f"{origin}/{framework}/dist/?state=guide&theme=light", wait_until="networkidle"
        )
        await page.get_by_role("button", name="Show workspace details").click()
        await page.wait_for_function(
            "document.activeElement.matches('[data-onboarding-target=\"business-settings\"]')"
        )
        await page.wait_for_timeout(400)
        assert await page.evaluate(
            "document.activeElement.matches('[data-onboarding-target=\"business-settings\"]')"
        ), "Guide transition stole focus from the spotlight target"
        result["passed"].append("spotlight focus survives normal-motion guide closure")
        await page.screenshot(
            path=str(SHOTS / f"{framework}-spotlight-{width}-light.png"), full_page=False
        )
        await page.goto(f"{origin}/{framework}/dist/?theme=light", wait_until="networkidle")
        await page.locator("[data-setup-open]").click()
        await page.get_by_role("button", name="Choose journey").first.click()
        await page.locator("#onboardingGuidePanel").wait_for(state="visible")
        await page.wait_for_timeout(400)
        assert await page.locator("#onboardingGuidePanel").evaluate(
            "e=>e.contains(document.activeElement)"
        ), "Journey handoff lost focus"
        result["passed"].append("welcome-to-guide handoff waits for close completion")
        await page.get_by_role("button", name="Continue later", exact=True).click()
        await page.locator("#onboardingGuidePanel").wait_for(state="hidden")
        if width < 1200:
            await page.locator("[data-menu-open]").click()
            await page.locator("#navigationDrawer [data-route=appointment_list]").first.click()
            await page.locator("#routePreview").wait_for(state="visible")
            await page.wait_for_timeout(400)
            assert await page.locator("#routePreview").evaluate(
                "e=>e.contains(document.activeElement)"
            ), "Drawer-to-preview handoff lost focus"
            await page.locator("[data-close=routePreview]").click()
            await page.locator("#routePreview").wait_for(state="hidden")
            await page.wait_for_function(
                "document.activeElement===document.querySelector('[data-menu-open]')"
            )
            assert await page.locator("[data-menu-open]").evaluate(
                "e=>e===document.activeElement"
            ), "Route preview returned focus to a hidden drawer link"
            result["passed"].append("drawer handoff and return focus with normal motion")
    except Exception as error:
        result["failures"].append(type(error).__name__ + ": " + str(error)[:600])
    result["page_errors"] = errors
    if errors:
        result["failures"].append("Unexpected normal-motion JavaScript error")
    await context.close()
    return result


async def main():
    server = make_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    start = time.monotonic()
    result = {
        "origin": origin,
        "date": "2026-11-15",
        "states": STATES,
        "sizes": SIZES,
        "scenarios": [],
        "interactions": [],
        "notes": [
            "Step 4: adapted from the unchanged Step 3 validator. Same gates; Manrope font assertion replaces Nunito. All payloads synthetic; no Django imported.",
            "Standard matrix uses reduced motion identically; normal-motion handoffs are recorded separately.",
            "Axe WCAG-tag scans supplement manual visual review; not a conformance certification.",
        ],
    }
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=CHROME)
        result["browser"] = browser.version
        sem = asyncio.Semaphore(3)
        tasks = [
            render_case(browser, origin, f, state, w, h, t, sem)
            for f in ["daisyui"]
            for state in STATES
            for w, h in SIZES
            for t in ["light", "dark"]
        ]
        for i, task in enumerate(asyncio.as_completed(tasks), 1):
            case = await task
            result["scenarios"].append(case)
            if case["checks"]:
                print(
                    json.dumps(
                        {
                            "failure": f"{case['framework']} {case['state']} {case['width']} {case['theme']}",
                            "checks": case["checks"],
                        }
                    ),
                    flush=True,
                )
            if i % 12 == 0:
                print(f"Captured {i}/{len(tasks)}", flush=True)
        for f in ["daisyui"]:
            for w, h in SIZES:
                for t in ["light", "dark"]:
                    r = await interactions(browser, origin, f, w, h, t)
                    result["interactions"].append(r)
                    print(
                        json.dumps(
                            {
                                "interaction": f"{f} {w} {t}",
                                "passed": len(r["passed"]),
                                "failures": r["failures"],
                            }
                        ),
                        flush=True,
                    )
        result["normal_motion"] = []
        for framework in ["daisyui"]:
            for width, height in SIZES:
                case = await normal_motion(browser, origin, framework, width, height)
                result["normal_motion"].append(case)
                print(
                    json.dumps(
                        {"normal_motion": f"{framework} {width}", "failures": case["failures"]}
                    ),
                    flush=True,
                )
        await browser.close()
    server.shutdown()
    server.server_close()
    # Compare immutable Step 3 fixture and route evidence; labels intentionally changed.
    previous = json.loads((LAB / "evidence/results.json").read_text())
    originals = {
        (c["framework"], c["state"], c["width"], c["theme"]): c for c in previous["scenarios"]
    }
    result["parity"] = []
    for case in result["scenarios"]:
        for framework in ["daisyui", "tabler"]:
            old = originals[(framework, case["state"], case["width"], case["theme"])]["metrics"]
            new = case["metrics"]
            result["parity"].append(
                {
                    "baseline": framework,
                    "state": case["state"],
                    "width": case["width"],
                    "theme": case["theme"],
                    "fixture_equal": new["state"] == old["state"],
                    "route_equal": new["routeIntents"] == old["routeIntents"],
                    "content_labels_changed": new["mainTokens"] != old["mainTokens"],
                }
            )
    result["assets"] = {}
    for f in ["daisyui"]:
        result["assets"][f] = {
            str(p.relative_to(LAB / f / "dist")): {
                "bytes": p.stat().st_size,
                "gzip_bytes": len(gzip.compress(p.read_bytes(), compresslevel=9, mtime=0)),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in (LAB / f / "dist").rglob("*")
            if p.is_file()
        }
    result["elapsed_seconds"] = round(time.monotonic() - start, 2)
    (OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    failures = sum(bool(c["checks"]) for c in result["scenarios"])
    interaction_failures = sum(bool(c["failures"]) for c in result["interactions"])
    parity_failures = sum(
        not all(c[k] for k in ("fixture_equal", "route_equal")) for c in result["parity"]
    )
    print(
        json.dumps(
            {
                "render_cases": len(result["scenarios"]),
                "render_failures": failures,
                "interaction_cases": len(result["interactions"]),
                "interaction_failures": interaction_failures,
                "parity_pairs": len(result["parity"]),
                "parity_failures": parity_failures,
                "elapsed_seconds": result["elapsed_seconds"],
            }
        ),
        flush=True,
    )
    return (
        failures
        + interaction_failures
        + parity_failures
        + sum(bool(c["failures"]) for c in result["normal_motion"])
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
