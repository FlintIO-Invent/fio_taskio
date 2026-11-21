"""Synthetic permission, form-contract, modal and RTL review; no Django access."""

import argparse
import hashlib
import json
import os
from itertools import product

from playwright.sync_api import expect, sync_playwright
from validate import ROOT, SIZES, axe, context, visit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()
    assert out.is_relative_to(ROOT / "evidence")
    out.mkdir(parents=True, exist_ok=False)
    source = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / "dist").rglob("*")
        if p.is_file()
    }
    cases = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get("PWA_CHROMIUM"))
        for (width, height), theme in product(SIZES, ["light", "dark"]):
            ctx, page, errors, console, blocked = context(browser, width, height)
            row = dict(width=width, theme=theme, checks=[])

            def check(label, value=True, row=row):
                assert value, label
                row["checks"].append(label)

            try:
                for screen in [
                    "list",
                    "create",
                    "edit",
                    "detail",
                    "payment",
                    "adjust",
                    "document",
                    "email",
                ]:
                    visit(page, screen, "locked", theme)
                    check(
                        "locked " + screen + " hides invoice data",
                        all(
                            t not in page.locator("main").inner_text()
                            for t in ["Alice", "Seabreeze", "318.00", "INV-2026"]
                        ),
                    )
                visit(page, "create", "appointment", theme)
                expect(page.locator("[name=client_id]")).to_have_value("101")
                expect(page.locator("#id_notes")).to_have_value(
                    "Created from appointment #801.\nAppointment title: Studio maintenance\nLocation: Seabreeze Studio"
                )
                check(
                    "appointment provenance and fixed client",
                    page.get_by_role("button", name="Add a new client", exact=True).count() == 0,
                )
                visit(page, "edit", "populated", theme)
                check("saved line IDs retained", page.locator("[name=line_id]").count() == 2)
                page.get_by_role("button", name="Add item", exact=True).click()
                expect(page.locator("[name=new_description]")).to_have_count(1)
                expect(page.locator("[name=new_service_id]")).to_have_count(1)
                expect(page.locator("[name=new_save_as_service]")).to_have_count(1)
                check("new edit lines preserve new prefixes")
                visit(page, "payment", "currency-retained", theme)
                expect(page.locator("#id_currency")).to_have_value("EUR")
                expect(page.locator("#id_currency")).to_be_disabled()
                check(
                    "saved currency and retry key",
                    page.locator("[name=idempotency_key]").input_value() != "",
                )
                visit(page, "payment", "legacy-unverified", theme)
                expect(page.locator("#id_amount")).to_have_value("")
                check("legacy review has no invented receipt amount")
                for role in ["staff", "accountant"]:
                    visit(page, "payment", role, theme)
                    check(
                        role + " verified-online option",
                        page.locator("#id_method option[value=VERIFIED_ONLINE]").count()
                        == int(role == "accountant"),
                    )
                visit(page, "adjust", "populated", theme)
                expect(page.locator("#id_amount")).to_have_value("100")
                check("adjustment defaults to remaining receipt, not invoice balance")
                visit(page, "list", "populated", theme)
                page.get_by_role("button", name="Delete INV-2026-0043", exact=True).click()
                dialog = page.locator("#confirmDialog")
                page.keyboard.press("Escape")
                expect(
                    page.get_by_role("button", name="Delete INV-2026-0043", exact=True)
                ).to_be_focused()
                check(
                    "delete cancellation retains draft",
                    page.locator("[data-invoice-id]").count() == 8,
                )
                page.get_by_role("button", name="Delete INV-2026-0043", exact=True).click()
                dialog.get_by_role("button", name="Delete draft", exact=True).click()
                check(
                    "confirmed draft deletion affects only simulated row",
                    page.locator("[data-invoice-id]").count() == 7,
                )
                visit(page, "create", "populated", theme)
                page.get_by_role("button", name="Add a new client", exact=True).click()
                quick = page.locator("#quickClientModal")
                quick.locator("[type=submit]").click()
                check(
                    "inline field error associations",
                    quick.locator("input[aria-invalid=true]").count() == 6,
                )
                expect(quick.locator("[data-errors]")).to_be_focused()
                a = axe(page)
                check("quick client error modal axe", not a["violations"])
                page.screenshot(path=str(out / f"quick-error-{width}-{theme}.png"), full_page=True)
                page.keyboard.press("Escape")
                expect(
                    page.get_by_role("button", name="Add a new client", exact=True)
                ).to_be_focused()
                row["pass"] = not errors and not console and not blocked
            except Exception as error:
                row.update(exception=str(error), **{"pass": False})
                page.screenshot(path=str(out / f"failure-{width}-{theme}.png"), full_page=True)
            row.update(page_errors=errors, console_errors=console, blocked_requests=blocked)
            cases.append(row)
            ctx.close()
            (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
        for screen, (width, height), theme in product(
            ["list", "create", "document"], [SIZES[0], SIZES[2]], ["light", "dark"]
        ):
            ctx, page, errors, console, blocked = context(browser, width, height)
            visit(page, screen, "populated", theme)
            page.evaluate("document.documentElement.dir='rtl'")
            a = axe(page)
            checks = {
                "reflow": page.evaluate("document.documentElement.scrollWidth") <= width,
                "axe": not a["violations"],
            }
            if screen == "document":
                checks["english_document_keeps_ltr"] = (
                    page.locator("#customer-invoice").get_attribute("dir") == "ltr"
                )
            page.screenshot(path=str(out / f"rtl-{screen}-{width}-{theme}.png"), full_page=True)
            cases.append(
                dict(
                    screen=screen,
                    width=width,
                    theme=theme,
                    rtl=True,
                    checks=checks,
                    axe=a,
                    **{"pass": all(checks.values()) and not errors and not console and not blocked},
                )
            )
            ctx.close()
        browser.close()
    assert all(
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
        for name, expected in source.items()
    )
    result = {
        "cases": cases,
        "pass": all(c["pass"] for c in cases),
        "source_sha256": hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest(),
    }
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"cases": len(cases), "pass": result["pass"], "evidence": str(out)}))
    if not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
