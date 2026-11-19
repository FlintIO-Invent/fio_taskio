"""Publish only new Gate A review artifacts after successful synthetic checks."""

import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
TASK = REPO / "docs/design/motionmate-ui-lab/workflows/services-invoices-20261118"
SUITES = ["matrix-03", "journeys-04", "supplement-01", "final-delta", "pdf-05"]


def main():
    results = {
        name: json.loads((ROOT / "evidence" / name / "results.json").read_text()) for name in SUITES
    }
    assert all(result["pass"] for result in results.values())
    gallery = ROOT / "evidence/v1"
    gallery.mkdir(exist_ok=False)
    css = """body{margin:0;background:#f6f7fb;color:#182235;font:16px/1.6 system-ui,sans-serif}header,main{max-width:1280px;margin:auto;padding:24px}h1{font-size:32px;margin:0}a{color:#3949db;overflow-wrap:anywhere}nav{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}nav a,.open{padding:10px 16px;border:1px solid #71819a;border-radius:8px;min-height:24px;text-decoration:none;background:#fff}a:focus-visible{outline:3px solid #3949db;outline-offset:3px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}article{border:1px solid #d8dfea;border-radius:12px;background:#fff;padding:20px;min-width:0}img{width:100%;height:auto;display:block;border:1px solid #d8dfea;margin:16px 0}h2{font-size:24px;margin-top:40px}.note{padding:16px;border-inline-start:3px solid #3949db;background:#eef1fa}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #d8dfea;text-align:left}@media(max-width:767px){.grid{grid-template-columns:1fr}header,main{padding:16px}}"""
    (gallery / "gallery.css").write_text(css)
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Services Invoices v1 review</title><link rel="stylesheet" href="gallery.css"></head><body><header><h1>Services Invoices · design v1</h1><p>Gate A review · Fixed synthetic invoice date 18 November 2026</p><p class="note">Interactive design reference only. Application code, invoice records, calculations, permissions, PDFs and Logistics remain unchanged. These generated PDF examples use Chromium, not the actual ReportLab renderer.</p><nav><a href="../../dist/">Open interactive prototype</a><a href="#screens">Screen designs</a><a href="#documents">Customer PDFs</a><a href="#checks">Validation</a></nav></header><main>'
    ]
    parts.append('<h2 id="screens">Connected workspace screens</h2><div class="grid">')
    for screen in ["list", "create", "edit", "detail", "payment", "adjust", "document", "email"]:
        folder = "final-delta" if screen in ["edit", "detail", "document"] else "matrix-03"
        parts.append(
            f'<article><h3>{screen.title()}</h3><p><a class="open" href="../../dist/?screen={screen}&amp;theme=light">Try this screen</a></p>'
        )
        for width, theme in [(1440, "light"), (390, "dark")]:
            source = f"../{folder}/{screen}-populated-{width}-{theme}-viewport.png"
            parts.append(
                f'<a href="{source}"><img loading="lazy" src="{source}" alt="{html.escape(screen)} at {width}px in {theme} mode"></a>'
            )
        parts.append("</article>")
    parts.append(
        '</div><h2 id="documents">Clean customer documents</h2><p>Subtotal, applicable Tax, Total Amount and Notes; no internal Draft labels or routine payment/balance summaries. Meaningful cancellation, review and refund notices remain.</p><div class="grid">'
    )
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
        row = next(
            row
            for row in results["pdf-05"]["cases"]
            if row["scenario"] == scenario and row["theme"] == "light"
        )
        pdf = f"../pdf-05/invoice-{scenario}-light.pdf"
        image = f"../pdf-05/invoice-{scenario}-light-page-1.png"
        parts.append(
            f'<article><h3>{scenario.replace("-", " ").title()} · {row["pages"]} page(s)</h3><p><a class="open" href="{pdf}">Open design PDF</a> · <a href="../../dist/?screen=document&amp;scenario={scenario}">Interactive document</a></p><a href="{pdf}"><img loading="lazy" src="{image}" alt="Customer invoice PDF: {scenario}"></a></article>'
        )
    parts.append(
        '</div><h2 id="checks">Validation evidence</h2><table><thead><tr><th>Check</th><th>Result</th><th>Raw evidence</th></tr></thead><tbody>'
    )
    for name, result in results.items():
        parts.append(
            f'<tr><th scope="row">{name}</th><td>{len(result["cases"])} cases passed</td><td><a href="../{name}/results.json">Results JSON</a></td></tr>'
        )
    parts.append(
        '</tbody></table><p>Checks include four widths, both themes, roles and access states, focus and dialog behavior, drafts, service/category choices, separate lifecycle and receipt status, RTL, zero-tax/empty-notes documents and multipage PDFs. First failures and the interrupted static-server run are retained in separate evidence directories.</p><p class="note">No actual Django/backend/provider or ordinary-database check ran. Browser and PDF references do not establish production authorization, actual ReportLab parity, email delivery or complete WCAG conformance. Safari, Firefox, screen readers and native zoom remain unverified. Email-PDF Notes inclusion remains explicitly scoped for the later integration proposal.</p></main></body></html>'
    )
    (gallery / "gallery.html").write_text("".join(parts))
    index = {
        name: {
            "result": str((ROOT / "evidence" / name / "results.json").relative_to(REPO)),
            "cases": len(result["cases"]),
            "pass": result["pass"],
            "source_sha256": result.get("source_sha256"),
            "sha256": hashlib.sha256(
                (ROOT / "evidence" / name / "results.json").read_bytes()
            ).hexdigest(),
        }
        for name, result in results.items()
    }
    index["journey_assertions"] = sum(len(row["checks"]) for row in results["journeys-04"]["cases"])
    index["supplement_assertions"] = sum(
        len(row["checks"])
        for row in results["supplement-01"]["cases"]
        if isinstance(row["checks"], list)
    )
    index["browser"] = results["matrix-03"]["browser"]
    index["final_refinements"] = (
        "Final delta checks edit/detail/customer document after narrow Qty heading and synthetic draft-entry consistency refinements. Other full matrix screens are unchanged. Final PDF set regenerated from current assets."
    )
    (TASK / "browser-evidence-index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(
        json.dumps(
            {
                "gallery": str(gallery / "gallery.html"),
                "checks": {name: len(result["cases"]) for name, result in results.items()},
                "journey_assertions": index["journey_assertions"],
            }
        )
    )


if __name__ == "__main__":
    main()
