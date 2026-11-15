"""Supplement historical reviews with every final incomplete node and control states."""

import asyncio
import json
import threading

from playwright.async_api import async_playwright
from validate_details import AXE, CHROME, OUT, PAINT, SHOTS, contrast, make_server, paint, rgb


def parent_background(data):
    return next(rgb(c["background"])[0] for c in data["chain"][1:] if rgb(c["background"])[1] == 1)


async def main():
    result = {"incomplete": [], "controls": [], "labels": [], "reflow": [], "failures": []}
    matrix = json.loads((OUT / "results.json").read_text())
    server = make_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, headless=True)
        context = await browser.new_context(reduced_motion="reduce", service_workers="block")
        page = await context.new_page()
        await page.route(
            "**/*",
            lambda route: (
                route.continue_()
                if route.request.method == "GET" and route.request.url.startswith(origin + "/")
                else route.abort()
            ),
        )
        for case in matrix["scenarios"]:
            if not case["axe"]["incomplete"]:
                continue
            width, height, theme, state = (case[k] for k in ("width", "height", "theme", "state"))
            await page.set_viewport_size({"width": width, "height": height})
            await page.goto(
                f"{origin}/daisyui/dist/?theme={theme}&state={state}", wait_until="networkidle"
            )
            await page.add_script_tag(path=str(AXE))
            axe = await page.evaluate(
                "async()=>{let r=await axe.run(document,{runOnly:['color-contrast']});return {violations:r.violations,incomplete:r.incomplete}}"
            )
            nodes = []
            for rule in axe["incomplete"]:
                for index, node in enumerate(rule["nodes"]):
                    reviewed = await paint(
                        page.locator(node["target"][0]),
                        f"final-contrast-{state}-{width}-{theme}-{index}",
                    )
                    reviewed.update(target=node["target"], reason=node["any"])
                    nodes.append(reviewed)
                    if (
                        not reviewed["background_pixel_matches"]
                        or not reviewed["opaque"]
                        or reviewed["authored_contrast"] < 4.5
                    ):
                        result["failures"].append(f"Final contrast {state} {width} {theme} {index}")
            result["incomplete"].append(
                {"state": state, "width": width, "theme": theme, "axe": axe, "reviewed": nodes}
            )
            if axe["violations"]:
                result["failures"].append(f"Final axe contrast {state} {width} {theme}")

        for theme in ("light", "dark"):
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.goto(f"{origin}/daisyui/dist/?theme={theme}", wait_until="networkidle")
            for name, selector in (
                ("primary", ".section-primary"),
                ("secondary", ".followup-panel .mm-secondary"),
            ):
                loc = page.locator(selector)
                for state in ("default", "hover", "pressed", "keyboard-focus"):
                    await loc.scroll_into_view_if_needed()
                    await page.mouse.move(1, 1)
                    if state in ("hover", "pressed"):
                        await loc.hover()
                    if state == "pressed":
                        await page.mouse.down()
                    if state == "keyboard-focus":
                        await loc.focus()
                        await page.keyboard.press("Tab")
                        await page.keyboard.press("Shift+Tab")
                    data = await loc.evaluate(PAINT)
                    bg = next(
                        rgb(c["background"])[0]
                        for c in data["chain"]
                        if rgb(c["background"])[1] == 1
                    )
                    fg, _ = rgb(data["color"])
                    ring = rgb(data["outlineColor"])[0]
                    border = rgb(data["border"])[0]
                    parent = parent_background(data)
                    data.update(
                        component=name,
                        state=state,
                        theme=theme,
                        text_ratio=contrast(fg, bg),
                        boundary_ratio=contrast(bg, parent)
                        if name == "primary"
                        else min(contrast(border, bg), contrast(border, parent)),
                        focus_ratio=contrast(ring, parent) if state == "keyboard-focus" else None,
                    )
                    result["controls"].append(data)
                    if (
                        data["text_ratio"] < 4.5
                        or data["boundary_ratio"] < 3
                        or (data["focus_ratio"] is not None and data["focus_ratio"] < 3)
                    ):
                        result["failures"].append(f"Control contrast {theme} {name} {state}")
                    if state == "keyboard-focus":
                        await page.screenshot(path=str(SHOTS / f"focus-{theme}-{name}.png"))
                    if state == "pressed":
                        await page.mouse.move(1, 1)
                        await page.mouse.up()
            # The full accessible name also titles the route preview. Short visible
            # labels must not duplicate the dialog title through textContent.
            for selector, expected in (
                (".section-primary", "Open Appointments"),
                (".followup-panel .mm-secondary", "View bookings"),
                (".financial-panel .panel-header a", "View invoices"),
            ):
                loc = page.locator(selector)
                await loc.click()
                actual = await page.locator("#routeTitle").inner_text()
                result["labels"].append(
                    {
                        "theme": theme,
                        "expected": expected,
                        "actual": actual,
                        "accessible_name": await loc.get_attribute("aria-label"),
                    }
                )
                if actual != expected or await loc.get_attribute("aria-label") != expected:
                    result["failures"].append(f"Action label {theme} {expected}")
                await page.locator("[data-close=routePreview]").click()
            await page.set_viewport_size({"width": 320, "height": 844})
            await page.goto(f"{origin}/daisyui/dist/?theme={theme}", wait_until="networkidle")
            sizes = await page.evaluate(
                """()=>({width:document.documentElement.scrollWidth,targets:[...document.querySelectorAll('a,button,input:not([type=hidden]),summary')].filter(e=>e.checkVisibility({checkVisibilityCSS:true})&&!e.closest('details:not([open])')).map(e=>({name:e.getAttribute('aria-label')||e.textContent.trim(),width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})).filter(e=>e.width<43.9||e.height<43.9)})"""
            )
            result["reflow"].append({"theme": theme, **sizes})
            if sizes["width"] > 321 or sizes["targets"]:
                result["failures"].append(f"320px target/reflow {theme}")
        await browser.close()
    server.shutdown()
    server.server_close()
    (OUT / "contrast-states.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "final_incomplete_renders_reviewed": len(result["incomplete"]),
                "nodes": sum(len(c["reviewed"]) for c in result["incomplete"]),
                "control_samples": len(result["controls"]),
                "labels": len(result["labels"]),
                "reflow": len(result["reflow"]),
                "failures": result["failures"],
            }
        ),
        flush=True,
    )
    return len(result["failures"])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
