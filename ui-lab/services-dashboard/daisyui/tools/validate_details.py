"""Step 4 typography, record fidelity and rendered contrast evidence. GET-only lab server."""

import asyncio
import io
import json
import re
import sys
import threading
from collections import Counter
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

LAB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(LAB / "tools"))
from serve import make_server  # noqa: E402
from validate import CHROME, METRICS, SIZES, STATES  # noqa: E402

OUT = LAB / "daisyui/evidence/step4"
SHOTS = OUT / "details"
SHOTS.mkdir(exist_ok=True)
AXE = LAB / "tools/node_modules/axe-core/axe.min.js"

# The background is resolved from browser-computed ancestors, then checked against
# the dominant *rendered* background in a Chromium element screenshot. Glyph
# antialiasing is deliberately not used as the authored foreground color.
PAINT = r"""e=>{
 const s=getComputedStyle(e), chain=[];let n=e;
 while(n){let c=getComputedStyle(n);chain.push({tag:n.tagName,background:c.backgroundColor,image:c.backgroundImage,opacity:c.opacity});n=n.parentElement}
 const r=e.getBoundingClientRect();return {text:e.textContent.trim(),color:s.color,fontSize:s.fontSize,fontWeight:s.fontWeight,outline:s.outline,outlineColor:s.outlineColor,border:s.borderColor,shadow:s.textShadow,chain,rect:r.toJSON(),visible:e.checkVisibility({checkVisibilityCSS:true})};
}"""
FIDELITY = r"""()=>{
 const norm=s=>String(s).replace(/\s+/g,' ').trim();const d=window.labState,failures=[];
 const check=(selector,rows,fields)=>{let els=[...document.querySelectorAll(selector)];if(els.length!==rows.length)failures.push(selector+' count');rows.forEach((r,i)=>fields.forEach(k=>{if(r[k]&&!norm(els[i]?.textContent||'').includes(norm(r[k])))failures.push(selector+' '+i+' '+k)}));};
 check('[data-record=appointment]',d.appointmentsEnabled?d.appointmentRows:[],['customer','company','service','title','time','date','status']);
 check('[data-record=request]',d.requests,['customer','company','service','preferred','status']);
 check('.invoice-table tbody tr',d.invoicesEnabled?d.invoices:[],['number','customer','company','lifecycle','payment','amount','currency','note']);
 return {failures,fixture:d,routeIntents:[...document.querySelectorAll('main [data-route]')].map(e=>({route:e.dataset.route,id:e.dataset.id||null,query:e.dataset.query||'',href:e.getAttribute('href')}))};
}"""


def rgb(value):
    values = [float(n) for n in re.findall(r"[\d.]+", value)]
    return values[:3], values[3] if len(values) > 3 else 1


def luminance(values):
    c = [v / 255 for v in values]
    return sum(
        w * (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
        for w, v in zip((0.2126, 0.7152, 0.0722), c, strict=True)
    )


def contrast(a, b):
    lo, hi = sorted((luminance(a), luminance(b)))
    return (hi + 0.05) / (lo + 0.05)


async def paint(locator, label):
    await locator.scroll_into_view_if_needed()
    data = await locator.evaluate(PAINT)
    foreground, alpha = rgb(data["color"])
    background = next(
        (rgb(c["background"])[0] for c in data["chain"] if rgb(c["background"])[1] == 1), None
    )
    png = await locator.screenshot(animations="disabled")
    path = SHOTS / f"{label}.png"
    path.write_bytes(png)
    dominant, count = Counter(
        Image.open(io.BytesIO(png)).convert("RGB").get_flattened_data()
    ).most_common(1)[0]
    ratio = contrast(foreground, background) if background else None
    data.update(
        {
            "foreground": foreground,
            "background": background,
            "dominant_pixel": dominant,
            "background_pixel_matches": bool(
                background
                and max(abs(a - b) for a, b in zip(dominant, background, strict=True)) <= 1
            ),
            "authored_contrast": round(ratio, 3) if ratio else None,
            "opaque": alpha == 1 and all(float(c["opacity"]) == 1 for c in data["chain"]),
            "screenshot": str(path.relative_to(OUT)),
            "dominant_count": count,
        }
    )
    return data


async def main():
    server = make_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    result = {
        "fonts": [],
        "fidelity": [],
        "historical_contrast": [],
        "component_contrast": [],
        "keyboard": [],
        "failures": [],
        "requests": [],
        "page_errors": [],
    }
    original = json.loads((LAB / "evidence/results.json").read_text())
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, headless=True)
        result["browser"] = browser.version
        context = await browser.new_context(reduced_motion="reduce", service_workers="block")
        page = await context.new_page()
        page.on("pageerror", lambda error: result["page_errors"].append(str(error)))
        page.on(
            "request",
            lambda request: result["requests"].append(
                {"url": request.url, "method": request.method}
            ),
        )
        await page.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.method == "GET" and route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )

        # Identical refined markup/content with only the locally served font changed.
        for width, height in SIZES:
            for theme in ("light", "dark"):
                pair = []
                for font in ("manrope", "nunito"):
                    await page.set_viewport_size({"width": width, "height": height})
                    await page.goto(
                        f"{origin}/daisyui/dist/?theme={theme}&font={font}",
                        wait_until="networkidle",
                    )
                    await page.evaluate("document.fonts.ready")
                    m = await page.evaluate(METRICS)
                    faces = await page.evaluate(
                        "[...document.fonts].map(f=>({family:f.family,status:f.status}))"
                    )
                    for kind in ("viewport", "full"):
                        await page.screenshot(
                            path=str(SHOTS / f"font-{font}-{width}-{theme}-{kind}.png"),
                            full_page=kind == "full",
                        )
                    pair.append(m)
                    result["fonts"].append(
                        {
                            "font": font,
                            "width": width,
                            "theme": theme,
                            "metrics": m,
                            "font_faces": faces,
                        }
                    )
                    if (
                        m["smallTargets"]
                        or m["smallText"]
                        or m["overflow"]
                        or m["document"]["width"] > width
                    ):
                        result["failures"].append(f"Font geometry {font} {width} {theme}")
                if (
                    pair[0]["mainTokens"] != pair[1]["mainTokens"]
                    or pair[0]["state"] != pair[1]["state"]
                    or pair[0]["routeIntents"] != pair[1]["routeIntents"]
                ):
                    result["failures"].append(f"Typography content parity {width} {theme}")

        # Every record field, including company/title/date/status, stays in the DOM
        # in both responsive compositions, independently of fixture-object parity.
        for state in STATES:
            for width, height in (SIZES[0], SIZES[2]):
                await page.set_viewport_size({"width": width, "height": height})
                await page.goto(
                    f"{origin}/daisyui/dist/?state={state}&theme=light", wait_until="networkidle"
                )
                f = await page.evaluate(FIDELITY)
                result["fidelity"].append({"state": state, "width": width, **f})
                result["failures"].extend(
                    f"Record field {state} {width}: {v}" for v in f["failures"]
                )

        # Revisit every incomplete Step 3 render, without changing either baseline.
        historical = [c for c in original["scenarios"] if c["axe"]["incomplete"]]
        for case in historical:
            framework, state, width, theme = (
                case[k] for k in ("framework", "state", "width", "theme")
            )
            height = dict(SIZES)[width]
            await page.set_viewport_size({"width": width, "height": height})
            variants = ["original", "refined"] if framework == "daisyui" else ["original"]
            for variant in variants:
                path = (
                    "daisyui/evidence/step4/original-dist"
                    if framework == "daisyui" and variant == "original"
                    else f"{framework}/dist"
                )
                await page.goto(
                    f"{origin}/{path}/?state={state}&theme={theme}", wait_until="networkidle"
                )
                await page.evaluate("document.fonts.ready")
                await page.add_script_tag(path=str(AXE))
                axe = await page.evaluate(
                    "async()=>{const r=await axe.run(document,{runOnly:['color-contrast']});return {violations:r.violations,incomplete:r.incomplete}}"
                )
                reviewed = []
                for rule in axe["incomplete"]:
                    for index, node in enumerate(rule["nodes"]):
                        target = node["target"][0]
                        label = f"contrast-{framework}-{variant}-{state}-{width}-{theme}-{index}"
                        observed = await paint(page.locator(target), label)
                        observed["target"] = target
                        observed["axe_reason"] = node["any"]
                        reviewed.append(observed)
                        if (
                            not observed["opaque"]
                            or not observed["background_pixel_matches"]
                            or observed["authored_contrast"] < 4.5
                        ):
                            result["failures"].append(f"Unresolved contrast {label}")
                result["historical_contrast"].append(
                    {
                        "framework": framework,
                        "state": state,
                        "width": width,
                        "theme": theme,
                        "variant": variant,
                        "axe": axe,
                        "reviewed": reviewed,
                    }
                )
                if axe["violations"]:
                    result["failures"].append(
                        f"Contrast violations {framework} {variant} {state} {width} {theme}"
                    )

        # Actual default/hover/focus/disabled component colors in each theme.
        for theme in ("light", "dark"):
            await page.set_viewport_size({"width": 1440, "height": 900})
            await page.goto(f"{origin}/daisyui/dist/?theme={theme}", wait_until="networkidle")
            samples = [
                ("primary", ".section-primary"),
                ("secondary", ".followup-panel .mm-secondary"),
                ("active-nav", ".sidebar .is-current"),
                ("brand-services", ".vertical-label"),
                ("time", ".timeline-time time"),
                ("status", ".timeline-time .mm-badge"),
                ("online", ".request-bottom .attention"),
                ("finance", ".finance-summary dt"),
            ]
            for name, selector in samples:
                loc = page.locator(selector).first
                for interaction in (
                    ("default", "hover", "focus")
                    if name in ("primary", "secondary", "active-nav")
                    else ("default",)
                ):
                    await page.mouse.move(1, 1)
                    if interaction == "hover":
                        await loc.hover()
                    if interaction == "focus":
                        await loc.focus()
                        await page.keyboard.press("Tab")
                        await page.keyboard.press("Shift+Tab")
                    observed = await paint(loc, f"component-{theme}-{name}-{interaction}")
                    observed.update({"theme": theme, "component": name, "interaction": interaction})
                    result["component_contrast"].append(observed)
                    if observed["authored_contrast"] < 4.5:
                        result["failures"].append(
                            f"Component contrast {theme} {name} {interaction}"
                        )
            # Hold the existing clipboard promise: the real busy/disabled simulation.
            await page.evaluate(
                "()=>{navigator.clipboard.writeText=()=>new Promise(resolve=>window.releaseCopy=resolve)}"
            )
            await page.locator("[data-copy]").click()
            observed = await paint(page.locator("[data-copy]"), f"component-{theme}-copy-busy")
            result["component_contrast"].append(
                {"theme": theme, "component": "copy-busy", **observed}
            )
            if (
                observed["authored_contrast"] < 4.5
                or not await page.locator("[data-copy]").is_disabled()
            ):
                result["failures"].append(f"Copy busy contrast/state {theme}")
            await page.evaluate("window.releaseCopy()")

        for width, height in SIZES:
            for theme in ("light", "dark"):
                await page.set_viewport_size({"width": width, "height": height})
                await page.goto(f"{origin}/daisyui/dist/?theme={theme}", wait_until="networkidle")
                focuses = []
                for _ in range(28):
                    await page.keyboard.press("Tab")
                    f = await page.evaluate(
                        """()=>{let e=document.activeElement,s=getComputedStyle(e),r=e.getBoundingClientRect();return {tag:e.tagName,label:e.getAttribute('aria-label')||e.textContent.trim().slice(0,60),top:r.top,bottom:r.bottom,height:r.height,outline:s.outlineWidth,outlineColor:s.outlineColor,offset:s.outlineOffset,header:!!e.closest('header.topbar'),skip:e.matches('.skip-link')}}"""
                    )
                    focuses.append(f)
                    if (
                        f["tag"] not in ("BODY", "MAIN")
                        and not f["header"]
                        and not f["skip"]
                        and f["top"] < 63
                        and f["height"] < height - 64
                    ):
                        result["failures"].append(f"Focus obscured {width} {theme} {f['label']}")
                    if (
                        f["tag"] not in ("BODY", "MAIN")
                        and float(f["outline"].replace("px", "")) < 2
                    ):
                        result["failures"].append(f"Focus outline {width} {theme} {f['label']}")
                result["keyboard"].append({"width": width, "theme": theme, "focuses": focuses})
        await context.close()
        await browser.close()
    server.shutdown()
    server.server_close()
    if result["page_errors"] or any(r["method"] != "GET" for r in result["requests"]):
        result["failures"].append("Page/network isolation")
    (OUT / "details.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "fonts": len(result["fonts"]),
                "fidelity": len(result["fidelity"]),
                "historical_contrast_renders": len(result["historical_contrast"]),
                "contrast_nodes": sum(len(c["reviewed"]) for c in result["historical_contrast"]),
                "component_samples": len(result["component_contrast"]),
                "keyboard_cases": len(result["keyboard"]),
                "failures": result["failures"],
            }
        ),
        flush=True,
    )
    return len(result["failures"])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
