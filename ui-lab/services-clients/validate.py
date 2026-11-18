"""Task-owned synthetic browser review. Local GETs only; never imports Django."""

import argparse
import ast
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
BASE = "http://127.0.0.1:8766"
ENTRY = BASE + "/services-clients/dist/"
AXE = (ROOT.parent / "services-dashboard/tools/node_modules/axe-core/axe.min.js").read_text()
SIZES = [(1440, 900), (768, 1024), (390, 844), (320, 844)]
METRICS = r"""() => {
 const visible=e=>e.checkVisibility({checkVisibilityCSS:true,checkOpacity:true})&&!e.closest('dialog:not([open])');
 const controls=[...document.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,summary')].filter(visible).map(e=>{
  const hit=e.type==='checkbox'?(e.closest('label')||e):e;const r=hit.getBoundingClientRect();return {label:e.getAttribute('aria-label')||e.name||e.textContent.trim().slice(0,60),width:r.width,height:r.height};
 });
 const smallText=[];const walker=document.createTreeWalker(document.querySelector('main'),NodeFilter.SHOW_TEXT);let n;
 while(n=walker.nextNode())if(n.textContent.trim()&&visible(n.parentElement)&&parseFloat(getComputedStyle(n.parentElement).fontSize)<14)smallText.push(n.textContent.trim());
 const css=getComputedStyle(document.documentElement);
 return {documentWidth:document.documentElement.scrollWidth,width:innerWidth,smallTargets:controls.filter(c=>c.width<43.9||c.height<43.9),smallText,
  font:getComputedStyle(document.body).fontFamily,manrope:document.fonts.check('16px Manrope'),theme:document.documentElement.dataset.bsTheme,
  tokens:Object.fromEntries(['surface','text','secondary','primary','on-primary','primary-hover','control','error','error-bg'].map(k=>[k,css.getPropertyValue('--mm-'+k).trim()])),
  h1:document.querySelectorAll('h1').length,rows:document.querySelectorAll('main [data-client-id]').length,
  fields:[...document.querySelectorAll('[data-client-form] [name]:not([type=hidden])')].map(e=>e.name),
  visibleNames:[...document.querySelectorAll('main a,main button')].filter(visible).map(e=>e.textContent.trim()),
  hasInvoice:!!document.querySelector('#client-invoices'),hasAppointment:!!document.querySelector('#client-appointments'),
  renderedClientText:document.querySelector('main').textContent.includes('Alice Thompson')};
}"""


async def audit(page):
    await page.evaluate(AXE)
    return await page.evaluate(
        """async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {passes:r.passes.length,violations:r.violations,incomplete:r.incomplete};}"""
    )


def ratio(a, b):
    def lum(h):
        h = h.strip().lstrip("#")
        if len(h) == 3:
            h = "".join(x * 2 for x in h)
        v = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        v = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]

    x, y = sorted([lum(a), lum(b)])
    return (y + 0.05) / (x + 0.05)


async def setup(browser, width, height, theme, motion="reduce"):
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme=theme,
        reduced_motion=motion,
        service_workers="block",
    )
    page = await context.new_page()
    errors = []
    requests = []
    bad = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("request", lambda r: requests.append({"url": r.url, "method": r.method}))
    page.on(
        "response",
        lambda r: bad.append({"url": r.url, "status": r.status}) if r.status >= 400 else None,
    )
    page.on("requestfailed", lambda r: bad.append({"url": r.url, "failure": r.failure}))
    await page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(BASE + "/") and route.request.method == "GET"
            else route.abort()
        ),
    )
    return context, page, errors, requests, bad


async def goto(page, screen="list", scenario="populated", theme="light", **query):
    await page.goto(
        ENTRY + "?" + urlencode(dict(screen=screen, scenario=scenario, theme=theme, **query)),
        wait_until="networkidle",
    )
    await page.wait_for_function("window.labReady===true")
    await page.evaluate("document.fonts.ready")


async def matrix_case(browser, sem, out, screen, scenario, width, height, theme):
    async with sem:
        c, page, errors, requests, bad = await setup(browser, width, height, theme)
        result = {
            "screen": screen,
            "scenario": scenario,
            "width": width,
            "theme": theme,
            "checks": {},
        }
        label = f"{screen}-{scenario}-{width}-{theme}"
        try:
            await goto(page, screen, scenario, theme)
            metrics = await page.evaluate(METRICS)
            axe = await audit(page)
            result.update(metrics=metrics, axe=axe)
            checks = result["checks"]
            checks.update(
                reflow=metrics["documentWidth"] <= width,
                targets=not metrics["smallTargets"],
                text=not metrics["smallText"],
                one_h1=metrics["h1"] == 1,
                manrope=metrics["manrope"],
                theme=metrics["theme"] == theme,
                axe=not axe["violations"],
            )
            tokens = metrics["tokens"]
            pairs = [
                ("text", "surface", 4.5),
                ("secondary", "surface", 4.5),
                ("primary", "surface", 4.5),
                ("on-primary", "primary", 4.5),
                ("on-primary", "primary-hover", 4.5),
                ("control", "surface", 3),
                ("error", "error-bg", 4.5),
            ]
            result["contrast"] = [
                {"pair": [a, b], "ratio": round(ratio(tokens[a], tokens[b]), 3), "minimum": n}
                for a, b, n in pairs
            ]
            checks["semantic_contrast"] = all(
                r["ratio"] >= r["minimum"] for r in result["contrast"]
            )
            if screen in ["create", "edit"] and scenario not in [
                "quota",
                "read-only",
                "viewer",
                "locked",
            ]:
                tree = ast.parse((REPO / "src/apps/crm/forms.py").read_text())
                form = next(
                    n
                    for n in tree.body
                    if isinstance(n, ast.ClassDef) and n.name == "PrivateClientForm"
                )
                meta = next(
                    n for n in form.body if isinstance(n, ast.ClassDef) and n.name == "Meta"
                )
                fields = next(
                    ast.literal_eval(n.value)
                    for n in meta.body
                    if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "fields" for t in n.targets)
                )
                checks["real_form_inventory"] = (
                    set(fields) == set(metrics["fields"]) and len(metrics["fields"]) == 32
                )
            if scenario == "locked":
                checks["no_client_data"] = (
                    not metrics["renderedClientText"] and metrics["rows"] == 0
                )
            if screen == "profile":
                if scenario == "no-invoices":
                    checks["invoice_gate"] = not metrics["hasInvoice"]
                if scenario == "no-appointments":
                    checks["appointment_gate"] = not metrics["hasAppointment"]
                if scenario == "accountant":
                    checks["accountant_schedule"] = (
                        await page.locator('main [data-route="appointment_create"]').count() == 0
                    )
                if scenario == "viewer":
                    checks["viewer_billing_read"] = (
                        metrics["hasInvoice"]
                        and await page.locator('main [data-screen="edit"]').count() == 0
                    )
                if scenario in ["staff", "accountant", "viewer", "read-only"]:
                    checks["archive_guard"] = (
                        await page.locator('main [data-action="archive"]').count() == 0
                    )
            if scenario in ["viewer", "read-only"] and screen == "list":
                checks["write_controls"] = (
                    await page.locator(
                        'main [data-screen="create"],main [data-screen="edit"],main [data-screen="upload"]'
                    ).count()
                    == 0
                )
            if scenario == "import-blocked" and screen == "preview":
                checks["blocked_import"] = await page.locator("[data-import-confirm]").count() == 0
            if scenario == "invoice-review":
                checks["review_no_inference"] = (
                    await page.get_by_text("Unverified — review required", exact=True).count() == 6
                )
            for suffix, full in [("viewport", False), ("full", True)]:
                await page.screenshot(
                    path=str(out / "screenshots" / f"{label}-{suffix}.png"),
                    full_page=full,
                    animations="disabled",
                )
        except Exception as e:
            result["exception"] = str(e)
        result.update(errors=errors, bad_requests=bad, requests=requests)
        result["checks"]["browser_clean"] = not errors and not bad
        result["checks"]["local_gets_only"] = all(
            r["method"] == "GET" and r["url"].startswith(BASE + "/") for r in requests
        )
        result["pass"] = not result.get("exception") and all(result["checks"].values())
        await c.close()
        return result


async def journey(browser, out, width, height, theme):
    c, page, errors, requests, bad = await setup(browser, width, height, theme)
    r = {"width": width, "theme": theme, "checks": []}

    async def check(name, test):
        if not test:
            raise AssertionError(name)
        r["checks"].append(name)

    async def click(selector):
        await page.locator(selector).click()

    try:
        await goto(page, theme=theme)
        await page.locator("[name=q]").fill("Harbour Dental")
        await click("[data-filter] [type=submit]")
        await check("company search", await page.locator("[data-client-id]").count() == 1)
        await click("[data-action=reset]")
        await page.locator("[name=district]").select_option("COLE_BAY")
        await page.locator("[name=is_active]").select_option("false")
        await click("[data-filter] [type=submit]")
        await check(
            "combined district/activity filters",
            await page.locator('[data-client-id="106"]').count() == 1,
        )
        await goto(page, theme=theme, is_active="0")
        await check("historical false alias", await page.locator("[data-client-id]").count() == 1)
        await goto(page, theme=theme, is_active="1")
        await check(
            "historical true alias", await page.locator('[data-client-id="106"]').count() == 0
        )
        await click("[data-action=reset]")
        await click("[data-action=next]")
        await check("ten-row pagination", await page.locator("[data-client-id]").count() == 3)
        await click("[data-action=all]")
        await check("view all", await page.locator("[data-client-id]").count() == 13)
        await page.locator('[data-select="101"]').check()
        await check(
            "record selection retained", await page.locator('[data-select="101"]').is_checked()
        )
        await page.locator("[data-sort-select]").select_option("company")
        await check(
            "sorting retains selection", await page.locator('[data-select="101"]').is_checked()
        )
        await click("[data-action=direction]")
        await click("[data-action=clear-selection]")
        await check("selection clear", not await page.locator('[data-select="101"]').is_checked())
        await page.locator('main .record-name[data-id="101"]').click()
        await check("profile navigation", await page.locator("h1").inner_text() == "Alice Thompson")
        await page.locator("#client-details summary").click()
        await check(
            "business and contact disclosure",
            await page.locator("#client-details").evaluate("(e)=>e.open"),
        )
        await page.locator('[data-invoice-page="2"]').click()
        await check(
            "invoice six-row pagination",
            await page.locator(".invoice").count() == 6 and "invoice_page=2" in page.url,
        )
        await page.locator("main [data-jump=notes]").click()
        await check(
            "edit note destination", await page.locator("#section-notes").evaluate("(e)=>e.open")
        )
        await page.locator("[name=notes]").fill("Keep this note while checking another section.")
        await page.locator("[name=first_name]").fill("Alicia")
        await page.locator("[name=email]").fill("invalid")
        await click("[data-client-form] [type=submit]")
        await check(
            "validation summary receives focus",
            await page.locator("[data-error-summary]").evaluate("(e)=>e===document.activeElement"),
        )
        await check(
            "draft survives errors",
            await page.locator("[name=notes]").input_value()
            == "Keep this note while checking another section.",
        )
        await page.locator("[name=email]").fill("alicia@example.test")
        await click("[data-theme-toggle]")
        await check(
            "theme preserves edit draft",
            await page.locator("[name=first_name]").input_value() == "Alicia",
        )
        await click("[data-client-form] [type=submit]")
        await check(
            "edit returns to profile", await page.locator("h1").inner_text() == "Alicia Thompson"
        )
        await goto(page, "create", theme=theme)
        await click("[data-client-form] [type=submit]")
        await check(
            "required fields explained", await page.locator("[aria-invalid=true]").count() == 6
        )
        for key, val in {
            "first_name": "Zoe",
            "last_name": "Review",
            "company_name": "Zoe Review",
            "email": "zoe@example.test",
            "phone": "+1 721 555 0199",
            "street_address": "21 Test Street",
        }.items():
            await page.locator(f"[name={key}]").fill(val)
        await page.locator("[name=client_type]").select_option("INDIVIDUAL")
        await check(
            "Individual retains company requirement",
            await page.locator("[name=company_name]").get_attribute("required") is not None,
        )
        await page.locator("[name=country]").select_option("Netherlands")
        await check(
            "country-sensitive address",
            await page.get_by_label("City (optional)", exact=True).count() == 1
            and await page.locator("[name=district]").get_attribute("type") == "text",
        )
        await page.locator("[name=district]").fill("Amsterdam")
        await page.locator("[name=country]").select_option("Sint Maarten")
        await check(
            "address draft survives country change",
            await page.locator("[name=district]").input_value() == "Amsterdam",
        )
        await click("[data-client-form] [type=submit]")
        await check(
            "create returns to directory",
            await page.locator("h1").inner_text() == "Clients"
            and "created successfully" in await page.locator("main").inner_text(),
        )
        await page.locator('main .record-name[data-id="101"]').click()
        await click("[data-action=archive]")
        await check(
            "named archive dialog", await page.locator("#archiveDialog").evaluate("(e)=>e.open")
        )
        await page.screenshot(
            path=str(out / "screenshots" / f"archive-{width}-{theme}.png"), full_page=False
        )
        await page.keyboard.press("Escape")
        await check(
            "archive escape returns focus",
            await page.locator("[data-action=archive]").evaluate("(e)=>e===document.activeElement"),
        )
        await click("[data-action=archive]")
        await click("[data-action=confirm-archive]")
        await check(
            "archive returns directory and preserves message",
            "Existing invoices and appointments were kept"
            in await page.locator("main").inner_text(),
        )
        await page.locator("main [data-screen=upload]").click()
        await page.locator("[name=csv_file]").set_input_files(
            {
                "name": "review.csv",
                "mimeType": "text/csv",
                "buffer": b"first_name,email\nNoah,noah@example.test\n",
            }
        )
        await click("[data-import-form] [type=submit]")
        await check(
            "CSV upload to supplied preview",
            await page.locator("h1").inner_text() == "Review client import",
        )
        await click("[data-import-confirm] [type=submit]")
        await check(
            "CSV explicit confirmation result",
            await page.locator("h1").inner_text() == "Import result",
        )
        await page.go_back()
        await click("[data-import-confirm] [type=submit]")
        await click("main .btn[data-screen=list]")
        if await page.locator("[data-action=all]").inner_text() == "View all":
            await click("[data-action=all]")
        await check(
            "CSV repeat confirmation is idempotent",
            await page.locator('[data-client-id="501"]').count() == 1,
        )
        await goto(page, "draft", theme=theme)
        await page.locator("#parent-title").fill("Unsaved appointment title")
        await page.locator("#parent-notes").fill("Unsaved appointment note")
        await click("[data-action=quick]")
        await click("[data-quick-form] [type=submit]")
        await check(
            "inline errors retain parent draft",
            await page.locator("#parent-title").input_value() == "Unsaved appointment title",
        )
        for key, val in {
            "first_name": "Riley",
            "last_name": "Draft",
            "company_name": "Riley Draft",
            "email": "riley@example.test",
            "phone": "+1 721 555 0100",
            "street_address": "12 Test Street",
        }.items():
            await page.locator(f'[name="new_client-{key}"]').fill(val)
        await page.keyboard.press("Tab")
        await check(
            "dialog keyboard containment",
            await page.locator("#quickDialog").evaluate("(e)=>e.contains(document.activeElement)"),
        )
        await click("[data-quick-form] [type=submit]")
        await check(
            "inline client selected",
            await page.locator("#parent-client").input_value() == "Riley Draft",
        )
        await check(
            "parent draft retained",
            await page.locator("#parent-title").input_value() == "Unsaved appointment title"
            and await page.locator("#parent-notes").input_value() == "Unsaved appointment note",
        )
        await check(
            "inline returns focus",
            await page.locator("[data-action=quick]").evaluate("(e)=>e===document.activeElement"),
        )
        if width < 1200:
            await click("[data-open=navigationDrawer]")
            await page.keyboard.press("Shift+Tab")
            await check(
                "navigation keyboard contained",
                await page.locator("#navigationDrawer").evaluate(
                    "(e)=>e.contains(document.activeElement)"
                ),
            )
            await page.keyboard.press("Escape")
            await check(
                "navigation focus return",
                await page.locator("[data-open=navigationDrawer]").evaluate(
                    "(e)=>e===document.activeElement"
                ),
            )
        await goto(page, theme=theme)
        await click("[data-action=export]")
        await check(
            "inert export disclosed without download",
            await page.locator("#route-path").inner_text()
            == "The existing Export control has no implemented action. No export is added by this design.",
        )
        await page.keyboard.press("Escape")
        await goto(page, "profile", theme=theme)
        await click("main [data-route=appointment_create]")
        await check(
            "appointment handoff preserves client query",
            "client_id=101" in await page.locator("#route-path").inner_text(),
        )
        await page.keyboard.press("Escape")
        await click("main [data-route=invoice_create_from_client]")
        await check(
            "invoice handoff actual route",
            await page.locator("#route-path").inner_text() == "/billings/from-client/101/",
        )
        await page.keyboard.press("Escape")
        await page.keyboard.press("Tab")
        await page.screenshot(
            path=str(out / "screenshots" / f"focus-{width}-{theme}.png"), full_page=False
        )
        r["axe_after_interaction"] = await audit(page)
        await check("axe after interactions", not r["axe_after_interaction"]["violations"])
        await check(
            "reduced motion respected",
            await page.evaluate(
                "getComputedStyle(document.querySelector('.btn')).transitionDuration==='0s'"
            ),
        )
    except Exception as e:
        r["exception"] = str(e)
    r.update(errors=errors, bad_requests=bad, requests=requests)
    r["pass"] = not r.get("exception") and not errors and not bad
    await c.close()
    return r


async def main(out):
    out.mkdir(parents=True, exist_ok=False)
    (out / "screenshots").mkdir()
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM") or None)
        specs = [
            (screen, "populated")
            for screen in [
                "list",
                "profile",
                "create",
                "edit",
                "upload",
                "preview",
                "result",
                "draft",
            ]
        ]
        specs += [
            ("list", s)
            for s in [
                "long",
                "partial",
                "empty",
                "viewer",
                "read-only",
                "locked",
                "loading",
                "error",
            ]
        ]
        specs += [
            ("profile", s)
            for s in [
                "long",
                "admin",
                "staff",
                "accountant",
                "viewer",
                "read-only",
                "no-invoices",
                "no-appointments",
                "invoice-review",
                "locked",
            ]
        ]
        specs += [("create", s) for s in ["invalid", "quota", "read-only"]] + [
            ("edit", "invalid"),
            ("preview", "import-blocked"),
            ("preview", "quota"),
        ]
        sem = asyncio.Semaphore(4)
        cases = await asyncio.gather(
            *(
                matrix_case(b, sem, out, screen, scenario, w, h, t)
                for screen, scenario in specs
                for w, h in SIZES
                for t in ["light", "dark"]
            )
        )
        (out / "matrix.json").write_text(
            json.dumps({"browser": b.version, "cases": cases}, indent=2) + "\n"
        )
        journeys = []
        for w, h in SIZES:
            for t in ["light", "dark"]:
                journeys.append(await journey(b, out, w, h, t))
        (out / "interactions.json").write_text(json.dumps(journeys, indent=2) + "\n")
        await b.close()
    summary = {
        "matrix_cases": len(cases),
        "matrix_passed": sum(c["pass"] for c in cases),
        "journeys": len(journeys),
        "journeys_passed": sum(c["pass"] for c in journeys),
        "interaction_assertions": sum(len(c["checks"]) for c in journeys),
        "matrix_failures": [
            {
                "screen": c["screen"],
                "scenario": c["scenario"],
                "width": c["width"],
                "theme": c["theme"],
                "failed": [k for k, v in c["checks"].items() if not v],
                "exception": c.get("exception"),
                "targets": c.get("metrics", {}).get("smallTargets"),
                "violations": [
                    (v["id"], [n["target"] for n in v["nodes"]])
                    for v in c.get("axe", {}).get("violations", [])
                ],
            }
            for c in cases
            if not c["pass"]
        ],
        "journey_failures": [
            {
                "width": c["width"],
                "theme": c["theme"],
                "exception": c.get("exception"),
                "errors": c["errors"],
                "bad_requests": c["bad_requests"],
            }
            for c in journeys
            if not c["pass"]
        ],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({**summary, "matrix_failures": summary["matrix_failures"][:8]}, indent=2))
    return not summary["matrix_failures"] and not summary["journey_failures"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(main(ROOT / args.out)) else 1)
