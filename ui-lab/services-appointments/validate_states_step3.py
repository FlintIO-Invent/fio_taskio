"""Supplemental keyboard, dialog and wizard evidence using the existing static server."""

import asyncio
import importlib.util
import json
import threading
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "step3", Path(__file__).with_name("validate_step3.py")
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


async def run_case(browser, origin, width, theme):
    context, page, issues = await base.prepare(browser, origin, width, theme)
    states = []
    checks = []

    async def snapshot(label):
        result = {
            "label": label,
            "width": width,
            "theme": theme,
            "axe": await base.audit(page),
            "metrics": await base.metrics(page),
        }
        await base.capture(page, f"{label}-{width}-{theme}")
        result["pass"] = (
            not result["axe"]["violations"]
            and result["metrics"]["documentWidth"] <= width + 1
            and not result["metrics"]["smallTargets"]
        )
        states.append(result)

    def check(ok, name):
        checks.append({"name": name, "pass": bool(ok)})
        if not ok:
            raise AssertionError(name)

    async def fill(form, values):
        for key, value in values.items():
            await form.locator(f'[name="{key}"]').fill(value)

    try:
        await base.open_page(page, origin, f"view=form&theme={theme}")
        await page.locator("[data-open=draftClientModal]").click()
        await page.locator("#draftClientModal [type=submit]").click()
        await snapshot("inline-client-error")
        check(
            await page.locator("#draftClientModal").evaluate(
                "(e)=>e.contains(document.activeElement)"
            ),
            "Client error focus is contained",
        )
        await page.keyboard.press("Escape")
        await base.open_page(page, origin, f"view=detail&theme={theme}")
        await page.get_by_role("button", name="Cancel Appointment", exact=True).focus()
        await page.keyboard.press("Enter")
        await snapshot("terminal-dialog")
        await page.keyboard.press("Shift+Tab")
        check(
            await page.locator("#statusDialog").evaluate("(e)=>e.contains(document.activeElement)"),
            "status dialog keyboard focus remains inside",
        )
        await page.keyboard.press("Escape")
        check(
            await page.evaluate("document.activeElement.textContent") == "Cancel Appointment",
            "status dialog Escape returns to trigger",
        )
        await base.open_page(page, origin, f"view=public&theme={theme}")
        await page.locator("[data-public-form] [type=submit]").focus()
        await page.keyboard.press("Enter")
        await page.locator("#id_staff_member").select_option("91")
        await page.locator("[data-book-date]").first.focus()
        await page.keyboard.press("Enter")
        await page.locator("[data-book-time]").first.focus()
        await page.keyboard.press("Space")
        check(
            await page.locator("[data-book-time]").first.get_attribute("aria-pressed") == "true",
            "keyboard selects slot",
        )
        await snapshot("availability-selected")
        await page.locator("[data-public-form] [type=submit]").click()
        await fill(
            page.locator("[data-public-form]"),
            {
                "company_name": "Harbour Example Ltd.",
                "first_name": "Jamie",
                "last_name": "Rivera",
                "email": "jamie@example.test",
                "phone": "+1 555 010 0101",
            },
        )
        await page.locator("[data-public-form] [type=submit]").click()
        await fill(page.locator("[data-public-form]"), {"street_address": "12 Synthetic Street"})
        await page.locator("#id_consent").check()
        await snapshot("public-review")
        await page.locator("[data-public-form] [type=submit]").click()
        await page.wait_for_function('() => window.labView==="outcome"')
        await snapshot("public-success")
        for scenario in ["conflict", "uncertain"]:
            await base.open_page(page, origin, f"view=public&scenario={scenario}&theme={theme}")
            await page.locator("[data-public-form] [type=submit]").click()
            await page.locator("#id_staff_member").select_option("91")
            await page.locator("[data-book-date]").first.click()
            await page.locator("[data-book-time]").first.click()
            await page.locator("[data-public-form] [type=submit]").click()
            await fill(
                page.locator("[data-public-form]"),
                {
                    "company_name": "Harbour Example Ltd.",
                    "first_name": "Jamie",
                    "last_name": "Rivera",
                    "email": "jamie@example.test",
                    "phone": "+1 555 010 0101",
                },
            )
            await page.locator("[data-public-form] [type=submit]").click()
            await page.locator("#id_street_address").fill("12 Synthetic Street")
            await page.locator("#id_consent").check()
            await page.locator("[data-public-form] [type=submit]").click()
            check(
                await page.locator(".error-summary").count() == 1,
                f"{scenario} presents recoverable error",
            )
            await snapshot(scenario + "-error")
        check(
            not issues["errors"] and not issues["failures"],
            "supplemental tasks have no browser/request failures",
        )
    except Exception as error:
        checks.append({"name": str(error), "pass": False})
    await context.close()
    result = {
        "width": width,
        "theme": theme,
        "states": states,
        "checks": checks,
        **issues,
        "pass": all(x["pass"] for x in states + checks),
    }
    print(f"States {width}/{theme}: {len(states)} states, pass={result['pass']}", flush=True)
    return result


async def main():
    server = base.server_module.make_server(root=base.LAB)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        async with base.async_playwright() as pw:
            browser = await pw.chromium.launch(
                **({"executable_path": base.BROWSER} if base.BROWSER else {}), headless=True
            )
            cases = []
            for width, theme in [(1440, "light"), (390, "dark")]:
                cases.append(await run_case(browser, origin, width, theme))
            output = {"cases": cases, "pass": all(x["pass"] for x in cases)}
            (base.OUT / "states.json").write_text(json.dumps(output, indent=2) + "\n")
            await browser.close()
            if not output["pass"]:
                raise SystemExit(1)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
