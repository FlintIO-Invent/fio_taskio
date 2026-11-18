"""Expanded surfaces and keyboard review beyond the default rendering matrix."""

import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright
from validate import METRICS, SIZES, audit, goto, setup

ROOT = Path(__file__).resolve().parent


async def main():
    out = ROOT / "evidence/supplement-01"
    out.mkdir(parents=True, exist_ok=False)
    (out / "screenshots").mkdir()
    results = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM") or None)
        for width, height in SIZES:
            for theme in ["light", "dark"]:
                c, page, errors, requests, bad = await setup(
                    b, width, height, theme, motion="no-preference"
                )
                r = {"width": width, "theme": theme, "checks": {}}
                try:
                    await goto(page, "edit", theme=theme)
                    await page.locator("[data-client-form] details").evaluate_all(
                        "(els)=>els.forEach(e=>e.open=true)"
                    )
                    axes = await audit(page)
                    metrics = await page.evaluate(METRICS)
                    r["expanded_form_axe"] = axes
                    r["checks"]["expanded_form_axe"] = not axes["violations"]
                    r["checks"]["expanded_form_reflow"] = metrics["documentWidth"] <= width
                    r["checks"]["expanded_form_targets"] = not metrics["smallTargets"]
                    r["checks"]["all_fields_labeled"] = await page.locator(
                        "[data-client-form] [name]:not([type=hidden])"
                    ).evaluate_all("(els)=>els.every(e=>e.labels?.length)")
                    r["checks"]["all_32_visible"] = await page.locator(
                        "[data-client-form] [name]:not([type=hidden])"
                    ).evaluate_all("(els)=>els.length===32&&els.every(e=>e.checkVisibility())")
                    await page.screenshot(
                        path=str(out / "screenshots" / f"all-fields-{width}-{theme}.png"),
                        full_page=True,
                    )
                    await goto(page, "profile", "partial", theme)
                    await page.locator("#client-details summary").click()
                    r["profile_partial_axe"] = await audit(page)
                    r["checks"]["partial_profile"] = (
                        not r["profile_partial_axe"]["violations"]
                        and await page.locator("h1").inner_text() == "Client #101"
                    )
                    await goto(page, "draft", theme=theme)
                    await page.locator("[data-action=quick]").click()
                    r["dialog_axe"] = await audit(page)
                    r["checks"]["dialog_axe"] = not r["dialog_axe"]["violations"]
                    await page.locator("[data-quick-form] [type=submit]").focus()
                    await page.keyboard.press("Tab")
                    r["checks"]["forward_focus_wrap"] = await page.locator(
                        '[aria-label="Close new client"]'
                    ).evaluate("(e)=>e===document.activeElement")
                    await page.keyboard.press("Shift+Tab")
                    r["checks"]["backward_focus_wrap"] = await page.locator(
                        "[data-quick-form] [type=submit]"
                    ).evaluate("(e)=>e===document.activeElement")
                    r["checks"]["visible_focus_ring"] = await page.evaluate(
                        "getComputedStyle(document.activeElement).outlineStyle==='solid'&&parseFloat(getComputedStyle(document.activeElement).outlineWidth)>=2"
                    )
                    await page.locator('[name="new_client-first_name"]').fill("Preserve this")
                    await page.keyboard.press("Escape")
                    r["checks"]["escape_focus_return"] = await page.locator(
                        "[data-action=quick]"
                    ).evaluate("(e)=>e===document.activeElement")
                    if width < 1200:
                        await page.locator("[data-open=navigationDrawer]").click()
                        await page.locator("#navigationDrawer [data-screen=list]").click()
                        r["checks"]["drawer_navigation_restores_scroll"] = await page.evaluate(
                            "document.documentElement.style.overflow===''&&document.querySelectorAll('dialog[open]').length===0"
                        )
                    await page.keyboard.press("Tab")
                    r["checks"]["normal_motion_no_decoration"] = await page.evaluate(
                        "[...document.querySelectorAll('main *')].every(e=>getComputedStyle(e).animationName==='none')"
                    )
                    await goto(page, "preview", "import-blocked", theme)
                    r["checks"]["blocked_import_no_confirm"] = (
                        await page.locator("[data-import-confirm]").count() == 0
                    )
                    await goto(page, "create", "quota", theme)
                    r["checks"]["quota_blocks_creation"] = (
                        await page.locator("[data-client-form]").count() == 0
                    )
                    await goto(page, "draft", "quota", theme)
                    await page.locator("[data-action=quick]").click()
                    for k, v in {
                        "first_name": "Test",
                        "last_name": "Limit",
                        "company_name": "Test Limit",
                        "email": "limit@example.test",
                        "phone": "555",
                        "street_address": "Test Street",
                    }.items():
                        await page.locator(f'[name="new_client-{k}"]').fill(v)
                    await page.locator("[data-quick-form] [type=submit]").click()
                    r["checks"]["quick_quota_preserves_draft"] = (
                        await page.locator("#quickDialog").evaluate("(e)=>e.open")
                        and "capacity reached"
                        in await page.locator("[data-quick-errors]").inner_text()
                        and await page.locator("#parent-title").input_value()
                        == "Weekly studio maintenance"
                    )
                    await page.screenshot(
                        path=str(out / "screenshots" / f"quick-quota-{width}-{theme}.png"),
                        full_page=False,
                    )
                except Exception as error:
                    r["exception"] = str(error)
                r.update(errors=errors, bad_requests=bad, requests=requests)
                r["pass"] = (
                    not r.get("exception") and all(r["checks"].values()) and not errors and not bad
                )
                results.append(r)
                await c.close()
        await b.close()
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cases": len(results),
                "pass": sum(r["pass"] for r in results),
                "assertions": sum(len(r["checks"]) for r in results),
                "failures": [
                    {
                        "width": r["width"],
                        "theme": r["theme"],
                        "checks": {k: v for k, v in r["checks"].items() if not v},
                        "exception": r.get("exception"),
                        "axe": [
                            v["id"]
                            for key in ["expanded_form_axe", "profile_partial_axe", "dialog_axe"]
                            for v in r.get(key, {}).get("violations", [])
                        ],
                    }
                    for r in results
                    if not r["pass"]
                ],
            },
            indent=2,
        )
    )
    return all(r["pass"] for r in results)


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
