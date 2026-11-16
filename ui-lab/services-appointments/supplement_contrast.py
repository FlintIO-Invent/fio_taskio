"""Computed-style supplement for the retained axe dialog contrast incompletes."""

import asyncio
import importlib.util
import json
import re
import threading
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "step3", Path(__file__).with_name("validate_step3.py")
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def luminance(color):
    rgb = [float(v) / 255 for v in re.findall(r"[\d.]+", color)[:3]]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * weight for v, weight in zip(linear, [0.2126, 0.7152, 0.0722], strict=True))


async def main():
    server = base.server_module.make_server(root=base.LAB)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    results = []
    try:
        async with base.async_playwright() as pw:
            browser = await pw.chromium.launch(
                **({"executable_path": base.BROWSER} if base.BROWSER else {}), headless=True
            )
            for width, theme in [(1440, "light"), (390, "dark")]:
                context, page, _issues = await base.prepare(browser, origin, width, theme)
                await base.open_page(page, origin, f"view=detail&theme={theme}")
                await page.get_by_role("button", name="Cancel Appointment", exact=True).click()
                values = await page.evaluate(
                    """() => [...document.querySelectorAll('#statusDialog .dialog-body p')].map(e=>({text:e.textContent,foreground:getComputedStyle(e).color,background:getComputedStyle(e.closest('dialog')).backgroundColor,opacity:getComputedStyle(e).opacity,dialogOpacity:getComputedStyle(e.closest('dialog')).opacity}))"""
                )
                for value in values:
                    a, b = luminance(value["foreground"]), luminance(value["background"])
                    value["contrast"] = round((max(a, b) + 0.05) / (min(a, b) + 0.05), 2)
                    value["meets_4_5"] = (
                        value["contrast"] >= 4.5
                        and value["opacity"] == value["dialogOpacity"] == "1"
                    )
                results.append({"width": width, "theme": theme, "paragraphs": values})
                await context.close()
            await browser.close()
        output = {
            "method": "Computed text colors against opaque native-dialog background. Supplemental evidence only; original axe incompletes remain unchanged.",
            "cases": results,
            "pass": all(p["meets_4_5"] for r in results for p in r["paragraphs"]),
        }
        (base.OUT / "contrast-supplement.json").write_text(json.dumps(output, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "pass": output["pass"],
                    "contrast_ratios": [p["contrast"] for r in results for p in r["paragraphs"]],
                }
            )
        )
        if not output["pass"]:
            raise SystemExit(1)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
