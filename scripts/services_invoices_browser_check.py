"""Real invoice review. Runtime financial POSTs remain blocked; writes use test DB only."""

import argparse
import json
import os
import re
import time
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import sync_playwright
from ui_preview.core import REPO, load_session, verify_database, verify_source

SIZES = [(1440, 900), (768, 1024), (390, 844), (320, 844)]
AXE = REPO / "ui-lab/services-dashboard/tools/node_modules/axe-core/axe.min.js"


def health(root, state, side):
    verify_source(state[side]["source"])
    verify_database(root, state, side)
    origin = f"http://127.0.0.1:{state[side]['http_port']}"
    with build_opener(ProxyHandler({})).open(origin + "/_preview/health", timeout=5) as response:
        identity = json.load(response)
    if (identity["session"], identity["side"], identity["database"]) != (
        state["id"],
        side,
        state[side]["database"],
    ):
        raise RuntimeError("Invoice HTTP listener identity differs.")
    return origin, identity


def login(page, origin, state, email="invoices.owner@preview.test"):
    page.goto(origin + "/accounts/logout/", wait_until="networkidle")
    page.goto(origin + "/accounts/login/", wait_until="networkidle")
    page.locator("[name=email]").fill(email)
    page.locator("[name=password]").fill(state["password"])
    with page.expect_navigation(wait_until="networkidle"):
        page.get_by_role("button", name="Sign In", exact=True).click()


def accessibility(page, scope=None):
    page.evaluate(AXE.read_text())
    return page.evaluate(
        """async scope=>{const r=await axe.run(scope||document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}});return {passes:r.passes.length,violations:r.violations,incomplete:r.incomplete};}""",
        scope,
    )


def capture(root, state, side, width_only=None):
    origin, identity = health(root, state, side)
    out = root / side / "evidence" / f"invoices-capture-{time.time_ns()}"
    out.mkdir(parents=True, exist_ok=False)
    sample = identity["fixtures"]["invoices_review"]["contexts"]["populated"]["invoices"]
    cases = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
        context = browser.new_context(reduced_motion="reduce", service_workers="block")
        context.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith(origin + "/") else route.abort()
            ),
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        login(page, origin, state)
        page.goto(origin + f"/billings/{sample['partial']}/", wait_until="networkidle")
        adjustment = next(
            (
                href
                for href in page.locator("a[href]").evaluate_all(
                    '(els)=>els.map(e=>e.getAttribute("href"))'
                )
                if re.match(r"/billings/\d+/payments/\d+/adjust/", href)
            ),
            None,
        )
        paths = [
            ("list", "/billings/"),
            ("detail", f"/billings/{sample['partial']}/"),
            ("create", "/billings/create/"),
            ("edit", f"/billings/{sample['draft']}/edit/"),
            ("payment", f"/billings/{sample['partial']}/payments/record/"),
        ]
        if adjustment:
            paths.append(("adjust", adjustment))
        for width, height in SIZES:
            if width_only and width != width_only:
                continue
            page.set_viewport_size({"width": width, "height": height})
            for theme in ["light", "dark"]:
                page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                for screen, path in paths:
                    response = page.goto(origin + path, wait_until="networkidle")
                    page.evaluate("document.fonts.ready")
                    scoped = page.locator(".mm-services-invoices").count() > 0
                    result = dict(
                        screen=screen,
                        width=width,
                        theme=theme,
                        status=response.status,
                        url=path,
                        document_width=page.evaluate("document.documentElement.scrollWidth"),
                        scoped=scoped,
                        axe=accessibility(page) if response.status == 200 else None,
                        content_axe=accessibility(page, ".mm-services-invoices")
                        if scoped
                        else None,
                    )
                    page.evaluate("window.scrollTo(0,0)")
                    page.screenshot(
                        path=str(out / f"{screen}-{width}-{theme}-full.png"), full_page=True
                    )
                    page.screenshot(path=str(out / f"{screen}-{width}-{theme}-viewport.png"))
                    cases.append(result)
                    (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
        # Actual authenticated ReportLab downloads. No financial/provider POST.
        import pypdfium2 as pdfium
        from pypdf import PdfReader

        for kind in ["draft", "partial", "many-lines", "legacy", "zero-tax"]:
            response = page.request.get(origin + f"/billings/{sample[kind]}/pdf/")
            if response.status != 200:
                raise AssertionError((kind, response.status))
            file = out / f"{kind}.pdf"
            file.write_bytes(response.body())
            reader = PdfReader(file)
            (out / f"{kind}.txt").write_text("\n".join(p.extract_text() for p in reader.pages))
            doc = pdfium.PdfDocument(str(file))
            for n in range(len(doc)):
                doc[n].render(scale=1.3).to_pil().save(out / f"{kind}-page-{n + 1}.png")
            doc.close()
        browser.close()
    result = {
        "cases": cases,
        "source": identity["source_sha256"],
        "side": side,
        "page_errors": errors,
        "pass": all(c["status"] == 200 for c in cases),
    }
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "evidence": str(out),
                "cases": len(cases),
                "page_errors": len(errors),
                "pass": result["pass"],
            }
        )
    )


# Imported by Django's guarded test adapter only. CLI capture never initializes Django.
if os.environ.get("DJANGO_SETTINGS_MODULE") == "taskio.services_test_settings":
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager

    from django.db import connections

    @contextmanager
    def database_worker():
        with ThreadPoolExecutor(max_workers=1) as database:
            try:
                yield database
            finally:
                database.submit(connections.close_all).result()

    from pathlib import Path

    from django.contrib.staticfiles.testing import StaticLiveServerTestCase
    from django.urls import reverse
    from playwright.sync_api import expect

    from apps.billings import tests as billing_fixtures
    from apps.billings.models import Invoice, InvoicePayment
    from apps.crm.models import BusinessService, Client

    class InvoiceBrowserChecks(StaticLiveServerTestCase):
        port = 8768

        def setUp(self):
            billing_fixtures.BillingBusinessScopingTests.setUp(self)
            self.client.force_login(self.user)

        def test_real_invoice_editor_receipt_refund_email_and_guards(self):
            out = (
                Path(os.environ["SERVICES_INVOICES_EVIDENCE"])
                / f"invoices-journeys-{time.time_ns()}"
            )
            out.mkdir(parents=True, exist_ok=False)
            report = {"journeys": [], "page_errors": [], "payloads": []}
            self.addCleanup(
                lambda: (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
            )
            with database_worker() as database, sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
                context = browser.new_context(reduced_motion="reduce", service_workers="block")
                context.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if route.request.url.startswith(self.live_server_url + "/")
                        else route.abort()
                    ),
                )
                context.add_cookies(
                    [
                        {
                            "name": "sessionid",
                            "value": self.client.cookies["sessionid"].value,
                            "url": self.live_server_url,
                        }
                    ]
                )
                page = context.new_page()
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                for width, theme in [(1440, "light"), (390, "dark")]:
                    page.set_viewport_size({"width": width, "height": 900})
                    page.goto(
                        self.live_server_url + reverse("invoice_create"), wait_until="networkidle"
                    )
                    page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                    page.reload(wait_until="networkidle")
                    notes = f"Downloaded notes {width}"
                    page.locator("#id_notes").fill(notes)
                    row = page.locator("#line-items .line-item").first
                    row.locator("[name=description]").fill(f"Custom service {width}")
                    row.locator("[name=quantity]").fill("2")
                    row.locator("[name=unit_price]").fill("25")
                    # Search actual current-workspace Choices, then keep a quick-client draft.
                    page.locator(".choices").click()
                    page.locator(".choices__input--cloned").fill("Alicia")
                    expect(page.locator(".choices__list--dropdown")).to_contain_text("Alicia")
                    page.keyboard.press("Escape")
                    opener = page.get_by_role("button", name="Add client", exact=True)
                    opener.click()
                    modal = page.locator("#quickClientModal")
                    expect(modal).to_be_visible()
                    expect(modal.locator("[name=first_name]")).to_be_focused()
                    page.keyboard.press("Escape")
                    expect(modal).not_to_be_visible()
                    expect(opener).to_be_focused()
                    expect(page.locator("#id_notes")).to_have_value(notes)
                    opener.click()
                    email = f"invoice-browser-{width}@example.test"
                    values = dict(
                        first_name="   ",
                        last_name="Client",
                        company_name="Browser Studio",
                        email=email,
                        phone="+17215550100",
                        street_address="12 Example Street",
                    )
                    for field, value in values.items():
                        modal.locator(f"[name={field}]").fill(value)
                    with page.expect_response(
                        lambda response: "quick-create" in response.url
                    ) as invalid:
                        modal.locator("[type=submit]").click()
                    self.assertEqual(invalid.value.status, 400)
                    expect(page.locator("#quick-client-errors")).to_be_visible()
                    expect(page.locator("#quick-client-errors")).to_contain_text("First name:")
                    expect(modal.locator("[name=first_name]")).to_have_attribute(
                        "aria-invalid", "true"
                    )
                    modal.locator("[name=first_name]").fill("Browser")
                    with page.expect_response(
                        lambda response: "quick-create" in response.url
                    ) as saved:
                        modal.locator("[type=submit]").click()
                    self.assertEqual(saved.value.status, 201)
                    expect(modal).not_to_be_visible()
                    expect(page.locator("#id_notes")).to_have_value(notes)
                    expect(row.locator("[name=description]")).to_have_value(
                        f"Custom service {width}"
                    )
                    row.locator(".manual-service-action-toggle").check()
                    row.locator("[name=new_service_category_name]").fill(
                        f"Browser category {width}"
                    )
                    with page.expect_navigation(wait_until="networkidle"):
                        page.locator("#invoice-editor [type=submit]").click()
                    pk = int(re.search(r"/billings/(\d+)/", page.url).group(1))
                    invoice = database.submit(lambda pk=pk: Invoice.objects.get(pk=pk)).result()
                    self.assertEqual(invoice.status, "DRAFT")
                    self.assertEqual(str(invoice.total), "53.25")
                    self.assertEqual(invoice.notes, notes)
                    self.assertTrue(
                        database.submit(
                            lambda email=email: Client.objects.filter(
                                business=self.business, email=email
                            ).exists()
                        ).result()
                    )
                    page.get_by_role("link", name="Edit Invoice", exact=True).click()
                    page.wait_for_load_state("networkidle")
                    expect(page.locator("#line-items [name=description]")).to_have_value(
                        f"Custom service {width}"
                    )
                    page.get_by_role("button", name="Add line", exact=True).click()
                    new = page.locator("#line-items .line-item").last
                    new.locator("[name=new_description]").fill(f"Added service {width}")
                    new.locator("[name=new_quantity]").fill("1")
                    new.locator("[name=new_unit_price]").fill("10")
                    new.locator(".manual-service-action-toggle").check()
                    new.locator("[name=new_new_service_category_name]").fill(
                        f"Added category {width}"
                    )
                    with page.expect_navigation(wait_until="networkidle"):
                        page.get_by_role("button", name="Save Changes", exact=True).click()
                    self.assertTrue(
                        database.submit(
                            lambda width=width: BusinessService.objects.filter(
                                business=self.business, name=f"Added service {width}"
                            ).exists()
                        ).result()
                    )
                    self.assertEqual(
                        database.submit(
                            lambda pk=pk: str(Invoice.objects.get(pk=pk).total)
                        ).result(),
                        "63.90",
                    )
                    issue = page.get_by_role("button", name="Issue invoice", exact=True)
                    issue.click()
                    confirmation = page.locator("#invoiceConfirmation")
                    expect(confirmation).to_be_visible()
                    expect(confirmation).to_be_focused()
                    page.keyboard.press("Escape")
                    expect(confirmation).not_to_be_visible()
                    expect(issue).to_be_focused()
                    self.assertEqual(
                        database.submit(lambda pk=pk: Invoice.objects.get(pk=pk).status).result(),
                        "DRAFT",
                    )
                    issue.click()
                    with page.expect_navigation(wait_until="networkidle"):
                        confirmation.get_by_role("button", name="Continue", exact=True).click()
                    self.assertEqual(
                        database.submit(lambda pk=pk: Invoice.objects.get(pk=pk).status).result(),
                        "SENT",
                    )
                    page.get_by_role("link", name="Record customer payment", exact=True).click()
                    page.wait_for_load_state("networkidle")
                    page.locator("[name=amount]").fill("-1")
                    page.locator("[name=reference]").fill(f"BROWSER-{width}")
                    with page.expect_navigation(wait_until="networkidle"):
                        page.locator("form [type=submit]").click()
                    expect(page.locator("#id_amount_error")).to_be_visible()
                    error_axe = accessibility(page, ".mm-services-invoices")
                    self.assertEqual(error_axe["violations"], [])
                    page.screenshot(
                        path=str(out / f"payment-error-{width}-{theme}.png"), full_page=True
                    )
                    self.assertEqual(
                        database.submit(
                            lambda pk=pk: InvoicePayment.objects.filter(invoice_id=pk).count()
                        ).result(),
                        0,
                    )
                    page.locator("[name=amount]").fill("10")
                    page.locator("[name=method]").select_option("CASH")
                    with page.expect_navigation(wait_until="networkidle"):
                        page.locator("form [type=submit]").click()
                    self.assertEqual(
                        database.submit(
                            lambda pk=pk: InvoicePayment.objects.filter(invoice_id=pk).count()
                        ).result(),
                        1,
                    )
                    page.get_by_role("link", name="Adjust receipt", exact=True).click()
                    page.wait_for_load_state("networkidle")
                    page.locator("[name=action]").select_option("REFUND")
                    page.locator("[name=amount]").fill("4")
                    page.locator("[name=reference]").fill(f"BROWSER-REFUND-{width}")
                    page.locator("[name=reason_reference]").fill(f"AUDIT-{width}")
                    with page.expect_navigation(wait_until="networkidle"):
                        page.locator("form [type=submit]").click()
                    self.assertEqual(
                        database.submit(
                            lambda pk=pk: InvoicePayment.objects.filter(invoice_id=pk).count()
                        ).result(),
                        2,
                    )
                    page.get_by_role("button", name="Email Invoice", exact=True).click()
                    with page.expect_navigation(wait_until="networkidle"):
                        page.locator("#invoiceConfirmation [data-confirm-submit]").click()
                    self.assertEqual(
                        database.submit(
                            lambda pk=pk: Invoice.objects.get(pk=pk).email_send_count
                        ).result(),
                        1,
                    )
                    page.get_by_role("button", name="Cancel Invoice", exact=True).click()
                    with page.expect_navigation(wait_until="networkidle"):
                        page.locator("#invoiceConfirmation [data-confirm-submit]").click()
                    # Unreturned active receipts keep the original issuance safeguard.
                    self.assertEqual(
                        database.submit(lambda pk=pk: Invoice.objects.get(pk=pk).status).result(),
                        "SENT",
                    )
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width + 1
                    )
                    page.screenshot(path=str(out / f"journey-{width}-{theme}.png"), full_page=True)
                    report["journeys"].append(
                        dict(width=width, theme=theme, invoice=pk, passed=True)
                    )
                self.assertEqual(report["page_errors"], [])
                browser.close()
            (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")


def supplement(root, state, side, context_forms=False):
    """Read-only scenario/role/reflow checks; no financial runtime writes."""

    origin, identity = health(root, state, side)
    contexts = identity["fixtures"]["invoices_review"]["contexts"]
    out = root / side / "evidence" / f"invoices-supplement-{time.time_ns()}"
    out.mkdir(parents=True, exist_ok=False)
    cases, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
        context = browser.new_context(reduced_motion="reduce", service_workers="block")
        context.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith(origin + "/") else route.abort()
            ),
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        jobs = []
        main = contexts["populated"]["invoices"]
        for key in [
            "draft",
            "paid",
            "cancelled",
            "zero-tax",
            "zero-value",
            "legacy",
            "missing-email",
            "many-lines",
        ]:
            jobs.append(("populated", "owner", key, f"/billings/{main[key]}/"))
        for scenario in ["empty", "long", "quota", "locked"]:
            jobs.append((scenario, "owner", "list", "/billings/"))
            jobs.append((scenario, "owner", "create", "/billings/create/"))
            if scenario == "long":
                for key, pk in contexts[scenario]["invoices"].items():
                    jobs.append((scenario, "owner", key, f"/billings/{pk}/"))
        for role in ["admin", "staff", "accountant", "viewer"]:
            jobs.extend(
                [
                    ("populated", role, "list", "/billings/"),
                    ("populated", role, "detail", f"/billings/{main['partial']}/"),
                    ("populated", role, "create", "/billings/create/"),
                    ("populated", role, "payment", f"/billings/{main['partial']}/payments/record/"),
                ]
            )
        log = contexts["logistics"]["invoices"]
        for role in ["owner", "admin", "staff", "accountant", "viewer"]:
            jobs.extend(
                [
                    ("logistics", role, "list", "/billings/"),
                    ("logistics", role, "detail", f"/billings/{log['issued']}/"),
                    ("logistics", role, "payment", f"/billings/{log['issued']}/payments/record/"),
                ]
            )
        jobs.append(
            (
                "populated",
                "owner",
                "from-client",
                f"/billings/from-client/{contexts['populated']['client_id']}/",
            )
        )
        jobs.append(
            (
                "appointment",
                "owner",
                "from-appointment",
                f"/billings/from-appointment/{identity['fixtures']['appointments_review']['appointments'][0]['id']}/",
            )
        )
        if context_forms:
            jobs = [job for job in jobs if job[2] in ["from-client", "from-appointment"]]
        current = None
        for scenario, role, screen, path in jobs:
            account = (
                f"invoices.{role}@preview.test"
                if scenario == "populated"
                else f"invoices.{scenario}.{role}@preview.test"
            )
            if scenario == "appointment":
                account = "bookings.owner@preview.test"
            if account != current:
                login(page, origin, state, account)
                current = account
            for width, theme in [(1440, "dark"), (390, "light")]:
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
                response = page.goto(origin + path, wait_until="networkidle")
                scoped = page.locator(".mm-services-invoices").count() > 0
                axe = accessibility(page, ".mm-services-invoices") if scoped else None
                case = dict(
                    scenario=scenario,
                    role=role,
                    screen=screen,
                    path=path,
                    status=response.status,
                    final_url=page.url.removeprefix(origin),
                    width=width,
                    theme=theme,
                    scoped=scoped,
                    document_width=page.evaluate("document.documentElement.scrollWidth"),
                    content_axe=axe,
                    actions=page.locator(".content :is(a,button)").all_text_contents(),
                )
                if scenario == "logistics" and scoped:
                    raise AssertionError("Services assets reached Logistics")
                case["screenshot"] = f"{scenario}-{role}-{screen}-{width}-{theme}.png"
                page.screenshot(path=str(out / case["screenshot"]), full_page=True)
                cases.append(case)
                (out / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
        # Scoped RTL behavior uses the existing Phoenix shell; no shared theme mutation.
        login(page, origin, state)
        for width in [1440, 390]:
            page.set_viewport_size({"width": width, "height": 900})
            page.goto(origin + "/billings/create/", wait_until="networkidle")
            page.locator("html").evaluate("e=>e.dir='rtl'")
            page.screenshot(path=str(out / f"rtl-editor-{width}.png"), full_page=True)
            cases.append(
                dict(
                    screen="rtl-editor",
                    width=width,
                    direction="rtl",
                    document_width=page.evaluate("document.documentElement.scrollWidth"),
                )
            )
        # Guard proof: human review cannot post financial changes (same existing middleware).
        page.goto(origin + f"/billings/{main['draft']}/", wait_until="networkidle")
        token = page.locator("[name=csrfmiddlewaretoken]").first.input_value()
        response = context.request.post(
            origin + f"/billings/{main['draft']}/change-status/",
            form={"csrfmiddlewaretoken": token, "status": "SENT"},
        )
        guard = dict(status=response.status, blocked=response.status == 409)
        if not guard["blocked"]:
            raise AssertionError("Runtime financial guard failed")
        browser.close()
    report = dict(
        side=side,
        source=identity["source_sha256"],
        cases=cases,
        page_errors=errors,
        financial_guard=guard,
    )
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            dict(evidence=str(out), cases=len(cases), page_errors=errors, financial_guard=guard)
        )
    )


def print_review(root, state, side):
    """Preserve the native Print action; validate customer-safe actual Chromium print output."""
    from io import BytesIO

    from pypdf import PdfReader

    origin, identity = health(root, state, side)
    out = root / side / "evidence" / f"invoices-print-{time.time_ns()}"
    out.mkdir(parents=True, exist_ok=False)
    sample = identity["fixtures"]["invoices_review"]["contexts"]["populated"]["invoices"]
    cases, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("PWA_CHROMIUM"))
        context = browser.new_context(service_workers="block", reduced_motion="reduce")
        context.route(
            "**/*",
            lambda route: (
                route.continue_() if route.request.url.startswith(origin + "/") else route.abort()
            ),
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        login(page, origin, state)
        for width, theme in [(1440, "light"), (390, "dark")]:
            page.set_viewport_size({"width": width, "height": 900})
            page.evaluate("t=>localStorage.setItem('phoenixTheme',t)", theme)
            for kind in ["draft", "partial", "cancelled", "legacy", "zero-tax", "many-lines"]:
                page.emulate_media(media="screen")
                page.goto(origin + f"/billings/{sample[kind]}/", wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                button = page.get_by_role("button", name="Print", exact=True)
                if button.count() != 1:
                    raise AssertionError("Existing Print action missing")
                page.evaluate(
                    "() => {window.__invoicePrintCalls=0; window.print=()=>window.__invoicePrintCalls++;}"
                )
                button.click()
                if page.evaluate("window.__invoicePrintCalls") != 1:
                    raise AssertionError("Print no longer invokes native window.print")
                screen_axe = accessibility(page, ".mm-services-invoices")
                if screen_axe["violations"]:
                    raise AssertionError(screen_axe["violations"])
                page.emulate_media(media="print")
                print_axe = accessibility(page, ".mm-services-invoices")
                if print_axe["violations"]:
                    raise AssertionError(print_axe["violations"])
                visible = page.locator("body").inner_text()
                for forbidden in [
                    "Draft",
                    "Partially paid",
                    "Customer payments",
                    "Balance due",
                    "Record customer payment",
                    "Actions",
                    "Open client profile",
                ]:
                    if forbidden in visible:
                        raise AssertionError((kind, forbidden))
                for required in ["Subtotal", "Total Amount", "Notes", "INV-POPULATED"]:
                    if required not in visible:
                        raise AssertionError((kind, required))
                if kind == "legacy" and "Manually marked paid" not in visible:
                    raise AssertionError("Review note lost on print")
                if kind == "cancelled" and "Cancelled" not in visible:
                    raise AssertionError("Cancellation note lost on print")
                if kind == "zero-tax" and "Tax (" in visible:
                    raise AssertionError("Inapplicable tax printed")
                data = page.pdf(format="Letter", print_background=True, prefer_css_page_size=True)
                stem = f"{kind}-{width}-{theme}"
                (out / (stem + ".pdf")).write_bytes(data)
                text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(data)).pages)
                if "Draft" in text or "Balance due" in text:
                    raise AssertionError("Staff labels reached print PDF")
                page.screenshot(path=str(out / (stem + ".png")), full_page=True)
                cases.append(
                    dict(kind=kind, width=width, theme=theme, pass_=True, screen_axe_violations=0)
                )
        browser.close()
    result = dict(
        source=identity["source_sha256"], cases=cases, page_errors=errors, pass_=not errors
    )
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    if errors:
        raise AssertionError(errors)
    print(json.dumps({"evidence": str(out), "cases": len(cases), "pass": not errors}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--side", choices=["before", "after"], required=True)
    parser.add_argument("--width", type=int, choices=[1440, 768, 390, 320])
    parser.add_argument("--supplement", action="store_true")
    parser.add_argument("--context-forms", action="store_true")
    parser.add_argument("--print-review", action="store_true")
    args = parser.parse_args()
    root, state = load_session(args.session)
    if state["route"] != "/billings/":
        raise RuntimeError("Invoice route required.")
    if args.print_review:
        print_review(root, state, args.side)
    elif args.supplement:
        supplement(root, state, args.side, args.context_forms)
    else:
        capture(root, state, args.side, args.width)


if __name__ == "__main__":
    main()
