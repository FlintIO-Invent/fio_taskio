"""Reusable static-preview Chromium matrix. No Django, database or provider access."""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import threading
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image, ImageChops
from playwright.async_api import async_playwright

LAB = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "lab_server", LAB / "services-dashboard/tools/serve.py"
)
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)
SIZES = [(1440, 900), (768, 1024), (390, 844)]
AXE = (LAB / "services-dashboard/tools/node_modules/axe-core/axe.min.js").read_text()
METRICS = """() => {
  const visible = el => el.checkVisibility({checkVisibilityCSS:true,checkOpacity:true}) && !el.closest('dialog:not([open])');
  const controls = [...document.querySelectorAll('a,button,input:not([type=hidden]),select,summary')].filter(visible).map(el => {
    const r=el.getBoundingClientRect();return {label:el.getAttribute('aria-label')||el.textContent.trim()||el.id,width:r.width,height:r.height};
  });
  const smallText=[]; const walker=document.createTreeWalker(document.querySelector('main'),NodeFilter.SHOW_TEXT);
  let node; while(node=walker.nextNode()) if(node.textContent.trim()&&visible(node.parentElement)) {
    const size=parseFloat(getComputedStyle(node.parentElement).fontSize);
    if(size<14)smallText.push({text:node.textContent.trim().slice(0,80),size});
  }
  const css=getComputedStyle(document.documentElement);
  const tokens=Object.fromEntries(['canvas','surface','raised','text','secondary','primary','on-primary','primary-hover','divider','control','success','success-bg','warning','warning-bg','error','error-bg','frame','current','header','violet','cyan'].map(key=>[key,css.getPropertyValue('--mm-'+key).trim()||css.getPropertyValue('--mm-services-'+key).trim()]));
  return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,documentHeight:document.documentElement.scrollHeight,
    font:getComputedStyle(document.body).fontFamily,manropeLoaded:document.fonts.check('16px Manrope'),theme:document.documentElement.dataset.bsTheme,
    smallText,smallTargets:controls.filter(c=>c.width<43.9||c.height<43.9),tokens,
    recordIds:[...document.querySelectorAll('main [data-entry-id]')].map(el=>el.dataset.entryKind+':'+el.dataset.entryId),
    routeIntents:[...document.querySelectorAll('main [data-route]')].map(el=>({name:el.dataset.route,path:el.getAttribute('href')}))};
}"""


async def axe_result(page):
    await page.evaluate(AXE)
    return await page.evaluate("""async() => {
      const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});
      return {passes:r.passes.length,violations:r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})),
        incomplete:r.incomplete.map(v=>({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))};
    }""")


async def case(browser, origin, entry, state, width, height, theme, out, semaphore):
    async with semaphore:
        context = await browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
            color_scheme=theme,
            reduced_motion="reduce",
            service_workers="block",
        )
        page = await context.new_page()
        errors, failed, requests, bad_responses = [], [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: failed.append({"url": request.url, "error": request.failure}),
        )
        page.on(
            "request",
            lambda request: requests.append(
                {"url": request.url.removeprefix(origin), "method": request.method}
            ),
        )
        page.on(
            "response",
            lambda response: (
                bad_responses.append({"url": response.url, "status": response.status})
                if response.status >= 400
                else None
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
        label = f"{entry['id']}-{state}-{width}-{theme}"
        result = {
            "screen": entry["id"],
            "state": state,
            "width": width,
            "height": height,
            "theme": theme,
            "checks": [],
        }
        try:
            query = urlencode({entry["scenarioParam"]: state, "theme": theme})
            await page.goto(f"{origin}/{entry['path']}?{query}", wait_until="networkidle")
            await page.wait_for_function("window.labReady===true")
            await page.evaluate("document.fonts.ready")
            metrics = await page.evaluate(METRICS)
            result["metrics"] = metrics
            result["axe"] = await axe_result(page)
            for full in (False, True):
                filename = f"{label}-{'full' if full else 'viewport'}.png"
                await page.screenshot(
                    path=str(out / "screenshots" / filename), full_page=full, animations="disabled"
                )
            checks = {
                "no document overflow": metrics["documentWidth"] <= width + 1,
                "working text at least 14px": not metrics["smallText"],
                "44px controls": not metrics["smallTargets"],
                "Manrope loaded": metrics["manropeLoaded"] and "Manrope" in metrics["font"],
                "correct theme": metrics["theme"] == theme,
                "no axe WCAG-tag violations": not result["axe"]["violations"],
                "no browser errors": not errors,
                "no failed requests": not failed and not bad_responses,
                "only local GETs": all(
                    r["url"].startswith("/") and r["method"] == "GET" for r in requests
                ),
                "isolated assets": all(
                    not any(
                        word in r["url"]
                        for word in ["/src/", "phoenix", "public_site", "logistics", "tabler"]
                    )
                    for r in requests
                ),
            }
            result["checks"] = [{"name": name, "pass": passed} for name, passed in checks.items()]
        except Exception as error:
            result["exception"] = str(error)
        result.update(
            browserErrors=errors,
            failedRequests=failed,
            badResponses=bad_responses,
            requests=requests,
        )
        result["pass"] = not result.get("exception") and all(c["pass"] for c in result["checks"])
        await context.close()
        print(f"{'PASS' if result['pass'] else 'FAIL'} {label}", flush=True)
        return result


def gallery(out, entry, cases):
    from html import escape

    sections = []
    reference = next(
        p
        for p in json.loads((LAB / "previews.json").read_text())
        if p["id"] == "services-dashboard"
    )
    for width, height in SIZES:
        for theme in ("light", "dark"):
            prefix = f"{entry['id']}-populated-{width}-{theme}"
            baseline = f"services-dashboard-populated-{width}-{theme}"
            sections.append(
                f'<section><h2>{width} × {height} · {theme}</h2><div class="comparison"><figure><a href="screenshots/{baseline}-full.png"><img src="screenshots/{baseline}-viewport.png" alt="Approved Step 4 dashboard, {width}px {theme}" loading="lazy"></a><figcaption>Approved Step 4 reference · fresh Chromium capture</figcaption></figure><figure><a href="screenshots/{prefix}-full.png"><img src="screenshots/{prefix}-viewport.png" alt="Appointments demonstration, {width}px {theme}" loading="lazy"></a><figcaption>Step 5 Appointments · same tokens, independent composition</figcaption></figure></div></section>'
            )
    links = "".join(
        f'<li>{escape(c["state"])} · {c["width"]}px · {c["theme"]}: <a href="screenshots/{entry["id"]}-{c["state"]}-{c["width"]}-{c["theme"]}-viewport.png">Viewport</a> · <a href="screenshots/{entry["id"]}-{c["state"]}-{c["width"]}-{c["theme"]}-full.png">Full page</a></li>'
        for c in cases
        if c["screen"] == entry["id"]
    )
    markup = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Step 5 · Motionmate preview evidence</title><link rel="stylesheet" href="../../review.css"><main class="review"><h1>Motionmate · Step 5 review</h1><p>Actual Chromium screenshots. Synthetic data, fixed clock 14 November 2026, DPR 1, reduced motion. Click an image for its full page. These compare design consistency across screens, not a before/after implementation.</p><p><a href="../../index.html">Preview launcher</a> · <a href="../dist/">Interactive Appointments</a> · <a href="../../{reference["gallery"]}">Unchanged Step 4 gallery</a> · <a href="results.json">Raw validation</a> · <a href="interactions.json">Interaction checks</a> · <a href="scope-check.json">Preservation evidence</a></p>{"".join(sections)}<h2>All captured states</h2><ul>{links}</ul><h2>Interaction evidence</h2><p><a href="screenshots/navigation-390-dark.png">Navigation drawer</a> · <a href="screenshots/route-390-dark.png">Route handoff</a> · <a href="screenshots/filters-390-dark.png">Filters</a> · <a href="screenshots/focus-390-dark.png">Keyboard focus</a> · <a href="screenshots/reflow-320-light.png">320px reflow</a> · <a href="screenshots/zoom-emulation-720-dark.png">200% reflow emulation</a></p><p>Automated checks do not establish full WCAG conformance or real application authorization. Review limitations in the Step 5 report.</p></main></html>"""
    (out / "gallery.html").write_text(markup)


async def main(args):
    entries = json.loads((LAB / "previews.json").read_text())
    entry = next(p for p in entries if p["id"] == args.screen)
    if entry["id"] == "services-dashboard":
        raise SystemExit(
            "Step 4 is frozen; capture it only as a reference in a new screen evidence directory."
        )
    out = LAB / entry["id"] / "evidence"
    (out / "screenshots").mkdir(parents=True, exist_ok=True)
    server = server_module.make_server(root=LAB)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        async with async_playwright() as playwright:
            executable = os.environ.get("PWA_CHROMIUM")
            browser = await playwright.chromium.launch(
                **({"executable_path": executable} if executable else {}), headless=True
            )
            semaphore = asyncio.Semaphore(3)
            states = args.states.split(",") if args.states else entry["states"]
            if not set(states).issubset(entry["states"]):
                raise ValueError("Unknown state")
            tasks = [
                case(browser, origin, entry, state, w, h, theme, out, semaphore)
                for state in states
                for w, h in SIZES
                for theme in ("light", "dark")
            ]
            reference = next(p for p in entries if p["id"] == "services-dashboard")
            tasks += [
                case(browser, origin, reference, "populated", w, h, theme, out, semaphore)
                for w, h in SIZES
                for theme in ("light", "dark")
            ]
            cases = await asyncio.gather(*tasks)
            reference_pixels = []
            for w, _h in SIZES:
                for theme in ("light", "dark"):
                    approved = (
                        LAB
                        / "services-dashboard/daisyui/evidence/step4/screenshots"
                        / f"daisyui-populated-{w}-{theme}-viewport.png"
                    )
                    fresh = (
                        out
                        / "screenshots"
                        / f"services-dashboard-populated-{w}-{theme}-viewport.png"
                    )
                    with Image.open(approved) as a, Image.open(fresh) as b:
                        identical = (
                            a.size == b.size
                            and ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox()
                            is None
                        )
                    reference_pixels.append(
                        {
                            "width": w,
                            "theme": theme,
                            "approved": str(approved.relative_to(LAB)),
                            "fresh": str(fresh.relative_to(LAB)),
                            "identicalPixels": identical,
                        }
                    )
            (out / "reference-comparison.json").write_text(
                json.dumps(reference_pixels, indent=2) + "\n"
            )
            asset_matches = []
            for name in ("motionmate-logo.svg", "manrope-latin-wght-normal.woff2"):
                a = LAB / "services-dashboard/daisyui/dist/assets" / name
                b = LAB / entry["id"] / "dist/assets" / name
                asset_matches.append(
                    {
                        "name": name,
                        "referenceSha256": hashlib.sha256(a.read_bytes()).hexdigest(),
                        "previewSha256": hashlib.sha256(b.read_bytes()).hexdigest(),
                        "identical": a.read_bytes() == b.read_bytes(),
                    }
                )
            comparisons = []
            for w, _h in SIZES:
                for theme in ("light", "dark"):
                    matches = [
                        c
                        for c in cases
                        if c["state"] == "populated" and c["width"] == w and c["theme"] == theme
                    ]
                    if len(matches) == 2:
                        comparisons.append(
                            {
                                "width": w,
                                "theme": theme,
                                "semanticTokensMatch": matches[0]["metrics"]["tokens"]
                                == matches[1]["metrics"]["tokens"],
                            }
                        )
            payload = {
                "browser": browser.version,
                "axe": "4.11.1",
                "clock": "2026-11-14T09:00:00Z",
                "dpr": 1,
                "motion": "reduce",
                "summary": {
                    "cases": len(cases),
                    "passed": sum(c["pass"] for c in cases),
                    "violations": sum(len(c.get("axe", {}).get("violations", [])) for c in cases),
                    "incompleteCases": sum(bool(c.get("axe", {}).get("incomplete")) for c in cases),
                },
                "comparisons": comparisons,
                "assets": asset_matches,
                "referencePixels": reference_pixels,
                "cases": cases,
            }
            (out / "results.json").write_text(json.dumps(payload, indent=2) + "\n")
            gallery(out, entry, cases)
            await browser.close()
            print(json.dumps(payload["summary"]), flush=True)
            if (
                not all(c["pass"] for c in cases)
                or not all(c["semanticTokensMatch"] for c in comparisons)
                or not all(c["identical"] for c in asset_matches)
                or not all(c["identicalPixels"] for c in reference_pixels)
            ):
                raise SystemExit(1)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", required=True)
    parser.add_argument("--states", help="Optional comma-separated subset for scoped rechecks")
    asyncio.run(main(parser.parse_args()))
