"""Gate A synthetic browser/PDF checks. Never imports Django or opens a database."""

import argparse
import hashlib
import json
import os
from itertools import product
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent
LAB = ROOT.parent
ORIGIN = "http://127.0.0.1:8766"
BASE = ORIGIN + "/services-invoices/dist/"
AXE = LAB / "services-dashboard/tools/node_modules/axe-core/axe.min.js"
SIZES = [(1440, 900), (768, 1024), (390, 844), (320, 844)]
SCREENS = ["list", "detail", "create", "edit", "payment", "adjust", "document", "email"]
METRICS = """() => {
 const root=document.querySelector('main'),visible=e=>e.checkVisibility({checkVisibilityCSS:true,checkOpacity:true});
 const targets=[...document.querySelectorAll('a,button,input:not([type=hidden]),select,textarea,summary')].filter(visible).map(e=>{
  const hit=e.type==='checkbox'?e.closest('label')||e:e,r=hit.getBoundingClientRect();
  return {name:e.getAttribute('aria-label')||e.name||e.textContent.trim().slice(0,70),width:r.width,height:r.height};
 });
 return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,smallTargets:targets.filter(t=>t.width<43.9||t.height<43.9),
  theme:document.documentElement.dataset.bsTheme,font:getComputedStyle(root).fontFamily,
  h1:document.querySelectorAll('h1').length,unlabeled:[...root.querySelectorAll('input:not([type=hidden]),select,textarea')].filter(e=>!e.labels.length&&!e.getAttribute('aria-label')).map(e=>e.name)};
}"""


def visit(page, screen="list", scenario="populated", theme="light"):
    response = page.goto(
        BASE + "?" + urlencode(dict(screen=screen, scenario=scenario, theme=theme))
    )
    assert response.status == 200
    page.wait_for_function("window.labReady===true")
    page.evaluate("document.fonts.ready")
    page.evaluate("window.scrollTo(0,0)")


def axe(page):
    page.evaluate(AXE.read_text())
    return page.evaluate(
        """async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {passes:r.passes.length,violations:r.violations,incomplete:r.incomplete};}"""
    )


def context(browser, width, height):
    ctx = browser.new_context(
        viewport={"width": width, "height": height},
        reduced_motion="reduce",
        service_workers="block",
    )
    blocked = []

    def guard(route):
        request = route.request
        if (
            request.method == "GET"
            and request.url.startswith(ORIGIN + "/")
            and not request.url.startswith(ORIGIN + "/billings/")
        ):
            route.continue_()
        else:
            blocked.append({"url": request.url, "method": request.method})
            route.abort()

    ctx.route("**/*", guard)
    page = ctx.new_page()
    errors, console = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console", lambda message: console.append(message.text) if message.type == "error" else None
    )
    return ctx, page, errors, console, blocked


def cases():
    result = set(product(SCREENS, ["populated"], SIZES, ["light", "dark"]))
    groups = {
        "list": ["empty", "long", "loading", "error", "locked", "quota", "read-only"],
        "detail": [
            "draft",
            "paid",
            "cancelled",
            "zero-tax",
            "zero-value",
            "review",
            "legacy-unverified",
            "refund",
            "currency-retained",
            "missing-email",
            "appointment",
        ],
        "create": ["invalid", "appointment", "client-locked", "quota", "viewer", "read-only"],
        "edit": ["invalid", "paid", "viewer"],
        "payment": ["payment-error", "legacy-unverified", "currency-retained", "staff", "viewer"],
        "adjust": ["staff", "viewer", "accountant"],
        "document": [
            "draft",
            "partial",
            "paid",
            "cancelled",
            "zero-tax",
            "zero-value",
            "review",
            "refund",
            "currency-retained",
            "long",
            "many-lines",
            "no-notes",
        ],
        "email": ["draft", "cancelled", "review"],
    }
    for screen, scenarios in groups.items():
        result.update(product([screen], scenarios, [SIZES[0], SIZES[-1]], ["light", "dark"]))
    for role in ["owner", "admin", "staff", "accountant", "viewer"]:
        result.add(("detail", role, SIZES[0], "light"))
        result.add(("detail", role, SIZES[2], "dark"))
    return sorted(result)


def matrix(browser, out, only=None, compact=False):
    results = []
    selected = [
        c for c in cases() if (not only or c[0] in only) and (not compact or c[1] == "populated")
    ]
    for n, (screen, scenario, (width, height), theme) in enumerate(selected):
        ctx, page, errors, console, blocked = context(browser, width, height)
        row = dict(screen=screen, scenario=scenario, width=width, theme=theme)
        try:
            visit(page, screen, scenario, theme)
            metrics, accessibility = page.evaluate(METRICS), axe(page)
            row.update(metrics=metrics, axe=accessibility)
            checks = dict(
                reflow=metrics["documentWidth"] <= width,
                targets=not metrics["smallTargets"],
                labels=not metrics["unlabeled"],
                heading=metrics["h1"] == 1,
                font="Manrope" in metrics["font"],
                theme=metrics["theme"] == theme,
                axe=not accessibility["violations"],
            )
            if screen == "document":
                paper = page.locator("#customer-invoice")
                text = paper.inner_text()
                checks.update(
                    no_draft="Draft" not in text,
                    one_total=text.count("Total Amount") == 1,
                    notes=("Notes" in text) == (scenario != "no-notes"),
                    no_routine_summary=all(
                        t not in text
                        for t in [
                            "Net payments received",
                            "Original invoice total",
                            "Payment status:",
                        ]
                    ),
                    white_paper=paper.evaluate("e=>getComputedStyle(e).backgroundColor")
                    == "rgb(255, 255, 255)",
                )
                if scenario == "zero-tax":
                    checks["no_zero_tax_row"] = "Tax (" not in text
            if screen == "detail" and scenario in [
                "owner",
                "admin",
                "staff",
                "accountant",
                "viewer",
            ]:
                checks["role_write"] = page.get_by_role(
                    "link", name="Record customer payment", exact=True
                ).count() == int(scenario != "viewer")
                checks["role_adjust"] = page.get_by_role(
                    "link", name="Adjust receipt", exact=True
                ).count() == int(scenario in ["owner", "admin", "accountant"])
            if screen == "email":
                text = page.locator(".customer-email").inner_text()
                checks["no_internal_customer_labels"] = all(
                    t not in text for t in ["Draft", "Net payments received", "Payment status:"]
                )
            row["checks"] = checks
            page.screenshot(
                path=str(out / f"{screen}-{scenario}-{width}-{theme}-full.png"),
                full_page=True,
                animations="disabled",
            )
            if scenario == "populated":
                page.screenshot(
                    path=str(out / f"{screen}-{scenario}-{width}-{theme}-viewport.png"),
                    animations="disabled",
                )
            if screen == "edit" and scenario == "populated":
                page.get_by_role("link", name="Cancel", exact=True).click()
                checks["draft_fixture_has_no_receipts"] = (
                    "No customer receipts recorded." in page.locator("#payments").inner_text()
                )
            row["pass"] = all(checks.values()) and not errors and not console and not blocked
        except Exception as error:
            row.update(exception=str(error), **{"pass": False})
        row.update(page_errors=errors, console_errors=console, blocked_requests=blocked)
        results.append(row)
        ctx.close()
        (out / "cases.json").write_text(json.dumps(results, indent=2) + "\n")
        if n % 20 == 0:
            print(
                f"Matrix {n + 1}/{len(selected)}; failures {sum(not r['pass'] for r in results)}",
                flush=True,
            )
    return {"cases": results, "pass": all(r["pass"] for r in results)}


def journeys(browser, out):
    results = []
    for (width, height), theme in product(SIZES, ["light", "dark"]):
        ctx, page, errors, console, blocked = context(browser, width, height)
        row = {"width": width, "theme": theme, "checks": []}

        def check(name, value=True, row=row):
            assert value, name
            row["checks"].append(name)

        try:
            visit(page, theme=theme)
            page.locator("[name=lifecycle]").select_option("DRAFT")
            page.get_by_role("button", name="Apply filters", exact=True).click()
            expect(page.locator("[data-invoice-id]")).to_have_count(1)
            check("lifecycle filter")
            page.get_by_role("button", name="Reset", exact=True).click()
            page.locator("[name=status]").select_option("PAID")
            page.get_by_role("button", name="Apply filters", exact=True).click()
            expect(page.locator("[data-invoice-id]")).to_have_count(2)
            check("receipt-backed Paid excludes zero-value and review")
            page.get_by_role("button", name="Reset", exact=True).click()
            page.get_by_role("button", name="View review invoices").click()
            expect(page.locator("[data-invoice-id]")).to_have_count(1)
            check("review filter")
            page.get_by_role("button", name="Reset", exact=True).click()
            page.get_by_role("link", name="Create invoice", exact=True).click()
            page.locator("[data-editor] button[type=submit]").click()
            expect(page.locator("[data-errors]")).to_be_focused()
            page.locator("[data-errors] a").first.click()
            expect(page.locator("#id_client_id")).to_be_focused()
            check("linked validation and focus")
            page.locator("#line_0_description").fill("Retained studio work")
            page.locator("#line_0_price").fill("150")
            page.locator("#id_notes").fill("Keep this complete invoice draft.")
            original_theme = page.locator("html").get_attribute("data-bs-theme")
            page.locator("[data-theme-toggle]").click()
            expect(page.locator("#id_notes")).to_have_value("Keep this complete invoice draft.")
            check("theme preserves draft")
            page.locator("[data-theme-toggle]").click()
            check(
                "theme restored",
                page.locator("html").get_attribute("data-bs-theme") == original_theme,
            )
            quick = page.get_by_role("button", name="Add a new client", exact=True)
            quick.click()
            modal = page.locator("#quickClientModal")
            modal.get_by_role("button", name="Cancel", exact=True).click()
            expect(quick).to_be_focused()
            expect(page.locator("#id_notes")).to_have_value("Keep this complete invoice draft.")
            check("quick client cancel and return focus")
            quick.click()
            modal.locator("[type=submit]").click()
            expect(modal.locator("[data-errors]")).to_be_focused()
            check("quick client validation")
            for name, value in dict(
                first_name="Taylor",
                last_name="Reed",
                company_name="New Studio",
                email="taylor@example.test",
                phone="+17215550199",
                street_address="12 Harbour Street",
            ).items():
                modal.locator(f"[name={name}]").fill(value)
            modal.locator("[type=submit]").click()
            expect(modal).not_to_be_visible()
            expect(page.locator("#id_client_id")).to_have_value("199")
            expect(page.locator("#line_0_description")).to_have_value("Retained studio work")
            expect(page.locator("#id_notes")).to_have_value("Keep this complete invoice draft.")
            check("inline client success preserves invoice draft")
            page.get_by_role("button", name="Add item", exact=True).click()
            page.locator("#line_1_service").select_option("31")
            expect(page.locator("#line_1_description")).to_have_value("Studio maintenance visit")
            expect(page.locator("#line_1_price")).to_have_value("125")
            check("saved service snapshot")
            page.get_by_role("button", name="Remove line item 2", exact=True).click()
            expect(page.locator("[data-line]")).to_have_count(1)
            check("add and remove line")
            page.locator(".save-service summary").click()
            page.locator("[data-save-service]").check()
            page.locator("#line_0_category").select_option("21")
            page.locator("#line_0_new_category").fill("New category")
            page.locator("[data-editor] [type=submit]").click()
            expect(page.locator("[data-errors]")).to_contain_text("not both")
            check("manual service category conflict preserves draft")
            page.locator("#line_0_new_category").fill("")
            page.locator("[data-editor] [type=submit]").click()
            expect(page.locator("h1")).to_contain_text("INV-2026-0050")
            expect(page.locator(".badges")).to_contain_text("Draft")
            check("creation saves internal Draft")
            page.get_by_role("link", name="Edit invoice", exact=True).click()
            expect(page.locator("#id_notes")).to_have_value("Keep this complete invoice draft.")
            page.locator("#id_notes").fill("Customer notes retained after edit.")
            page.locator("[data-editor] [type=submit]").click()
            expect(page.locator(".internal-notes")).to_contain_text(
                "Customer notes retained after edit."
            )
            check("edit round trip retains notes")
            page.get_by_role("link", name="Download PDF", exact=True).click()
            expect(page.locator("#customer-invoice")).not_to_contain_text("Draft")
            check("draft customer copy has no Draft label")
            page.get_by_role("link", name="Back to invoice", exact=True).click()
            expect(page.locator(".badges")).to_contain_text("Draft")
            check("customer view does not issue")
            page.get_by_role("button", name="Issue invoice", exact=True).click()
            dialog = page.locator("#confirmDialog")
            expect(dialog.get_by_role("button", name="Cancel", exact=True)).to_be_focused()
            modal_axe = axe(page)
            check("issue modal accessibility", not modal_axe["violations"])
            page.keyboard.press("Escape")
            expect(dialog).not_to_be_visible()
            expect(page.get_by_role("button", name="Issue invoice", exact=True)).to_be_focused()
            check("issue Escape and focus return")
            page.get_by_role("button", name="Issue invoice", exact=True).click()
            dialog.get_by_role("button", name="Issue invoice", exact=True).click()
            expect(page.locator(".badges")).to_contain_text("Issued")
            check("explicit issuance distinct from receipt")
            page.get_by_role("link", name="Record customer payment", exact=True).click()
            expect(page.locator("#id_currency")).to_be_disabled()
            check("existing payment page and disabled saved currency")
            page.locator("#id_amount").fill("50")
            page.locator("[data-payment] [type=submit]").click()
            expect(page.locator("[data-errors]")).to_contain_text("reference")
            check("receipt required reference")
            page.locator("#id_reference").fill("BANK-REVIEW-001")
            page.locator("[data-payment] [type=submit]").click()
            expect(page.locator(".badges")).to_contain_text("Partially paid")
            check("receipt changes payment presentation, keeps Issued")
            page.get_by_role("button", name="Cancel invoice", exact=True).click()
            dialog.get_by_role("button", name="Cancel invoice", exact=True).click()
            expect(page.locator(".badges")).to_contain_text("Issued")
            expect(page.get_by_role("status")).to_contain_text("Reverse/refund")
            check("active receipts protect cancellation")
            page.get_by_role("link", name="Adjust receipt", exact=True).click()
            page.locator("#id_action").select_option("REFUND")
            page.locator("#id_reference").fill("REFUND-REVIEW-001")
            page.locator("#id_reason_reference").fill("CASE-REVIEW-001")
            page.locator("[data-payment] [type=submit]").click()
            expect(page.get_by_role("status")).to_contain_text("No refund was sent")
            check("completed-refund recording is a simulation, no money movement")
            page.get_by_role("button", name="Email invoice", exact=True).click()
            dialog.get_by_role("button", name="Email invoice", exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("No message was sent")
            check("email submission distinct from delivery")
            page.get_by_role("link", name="Download PDF", exact=True).click()
            paper = page.locator("#customer-invoice").inner_text()
            check(
                "clean customer amounts and notes",
                all(t in paper for t in ["Subtotal", "Tax (6%)", "Total Amount", "Notes"])
                and all(
                    t not in paper for t in ["Draft", "Net payments received", "Payment status:"]
                ),
            )
            page.get_by_role("link", name="Back to invoice", exact=True).click()
            page.get_by_role("link", name="Open client profile", exact=True).click()
            expect(page.locator("#routePreview")).to_be_visible()
            page.keyboard.press("Escape")
            check("out of scope route intent is intercepted")
            if width < 1200:
                page.get_by_role("button", name="Open navigation", exact=True).click()
                expect(page.locator("#navigationDrawer")).to_be_visible()
                page.keyboard.press("Escape")
                expect(
                    page.get_by_role("button", name="Open navigation", exact=True)
                ).to_be_focused()
                check("mobile navigation Escape and focus")
            page.screenshot(path=str(out / f"journey-{width}-{theme}.png"), full_page=True)
            row["pass"] = not errors and not console and not blocked
        except Exception as error:
            row.update(exception=str(error), **{"pass": False})
            page.screenshot(path=str(out / f"failure-{width}-{theme}.png"), full_page=True)
        row.update(page_errors=errors, console_errors=console, blocked_requests=blocked)
        results.append(row)
        ctx.close()
        (out / "cases.json").write_text(json.dumps(results, indent=2) + "\n")
        print(f"Journey {width} {theme}: {row['pass']}, {len(row['checks'])} checks", flush=True)
    return {"cases": results, "pass": all(r["pass"] for r in results)}


def pdfs(browser, out):
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    results = []
    for scenario in [
        "populated",
        "draft",
        "zero-tax",
        "zero-value",
        "cancelled",
        "review",
        "refund",
        "long",
        "many-lines",
        "no-notes",
    ]:
        texts = []
        for theme in ["light", "dark"]:
            ctx, page, errors, console, blocked = context(browser, 1440, 900)
            visit(page, "document", scenario, theme)
            path = out / f"invoice-{scenario}-{theme}.pdf"
            page.pdf(
                path=str(path),
                print_background=True,
                prefer_css_page_size=True,
                display_header_footer=True,
                header_template="<span></span>",
                footer_template='<div style="font-family:Arial,sans-serif;font-size:8px;color:#526079;width:100%;margin:0 64px;display:flex;justify-content:space-between"><span>Invoice INV-2026-0042</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>',
            )
            reader = PdfReader(path)
            text = "\n".join(p.extract_text() for p in reader.pages)
            texts.append(text)
            checks = dict(
                no_draft="Draft" not in text,
                subtotal="Subtotal" in text,
                one_total=text.count("Total Amount") == 1,
                notes=text.count("Notes") == (0 if scenario == "no-notes" else 1),
                no_payment_summary=all(
                    t not in text
                    for t in ["Net payments received", "Original invoice total", "Payment status:"]
                ),
                letter=all(
                    abs(float(p.mediabox.width) - 612) < 1
                    and abs(float(p.mediabox.height) - 792) < 1
                    for p in reader.pages
                ),
                no_app_frame="Design v1" not in text and "UI preview" not in text,
                per_page_reference=all(
                    "INV-2026-0042" in p.extract_text() and "Page" in p.extract_text()
                    for p in reader.pages
                ),
            )
            if scenario == "zero-tax":
                checks["no_zero_tax_row"] = "Tax (" not in text
            if scenario == "many-lines":
                checks["multi_page"] = len(reader.pages) > 1
                checks["all_48_items"] = all(f"item {n:02d}" in text for n in range(1, 49))
                checks["repeated_headers"] = all(
                    "Description" in page.extract_text()
                    for page in reader.pages
                    if "Scheduled maintenance item" in page.extract_text()
                )
                checks["correct_total"] = "1272.00" in text
            if scenario == "cancelled":
                checks["cancelled_notice"] = "Cancelled" in text
            if scenario == "review":
                checks["review_notice"] = "Accounting review required" in text
            doc = pdfium.PdfDocument(str(path))
            for n in range(len(doc)):
                bitmap = doc[n].render(scale=1.5)
                bitmap.to_pil().save(out / f"invoice-{scenario}-{theme}-page-{n + 1}.png")
            doc.close()
            row = dict(
                scenario=scenario,
                theme=theme,
                pages=len(reader.pages),
                checks=checks,
                page_errors=errors,
                console_errors=console,
                blocked_requests=blocked,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            row["pass"] = all(checks.values()) and not errors and not console and not blocked
            results.append(row)
            ctx.close()
        results[-1]["theme_text_identical"] = texts[0] == texts[1]
        results[-1]["pass"] &= texts[0] == texts[1]
        (out / "cases.json").write_text(json.dumps(results, indent=2) + "\n")
    return {
        "cases": results,
        "pass": all(r["pass"] for r in results),
        "renderer": "Chromium design reference; not production ReportLab",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--suite", choices=["matrix", "journeys", "pdf"], required=True)
    parser.add_argument("--only", nargs="*", choices=SCREENS)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()
    assert out.is_relative_to(ROOT / "evidence")
    out.mkdir(parents=True, exist_ok=False)
    source_map = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ["src", "dist"]
        for p in sorted((ROOT / folder).rglob("*"))
        if p.is_file()
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=os.environ.get("PWA_CHROMIUM"))
        if args.suite == "matrix":
            result = matrix(browser, out, args.only, args.compact)
        elif args.suite == "journeys":
            result = journeys(browser, out)
        else:
            result = pdfs(browser, out)
        result["browser"] = browser.version
        browser.close()
    assert all(
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
        for name, expected in source_map.items()
    ), "Prototype changed during validation."
    result["source_sha256"] = hashlib.sha256(
        json.dumps(source_map, sort_keys=True).encode()
    ).hexdigest()
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(evidence=str(out), cases=len(result["cases"]), passed=result["pass"])))
    if not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
