"""Summarize local evidence and verify the protected tree without Django or network."""

import hashlib
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "ui-lab/services-appointments"
OUT = PACKAGE / "evidence/step3"
before = json.loads((OUT / "protected-before.json").read_text())
changed = [
    name
    for name, digest in before.items()
    if not (ROOT / name).is_file()
    or hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest
]
source_hashes = {
    str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
    for base in ["src", "dist"]
    for p in (PACKAGE / base).rglob("*")
    if p.is_file()
}
validation = json.loads((OUT / "validation.json").read_text())
states = json.loads((OUT / "states.json").read_text())
summary = {
    "browser": validation["browser"],
    "render_cases": len(validation["cases"]),
    "render_cases_passed": sum(c["pass"] for c in validation["cases"]),
    "task_checks": sum(len(c["checks"]) for c in validation["tasks"]),
    "task_checks_passed": sum(sum(x["pass"] for x in c["checks"]) for c in validation["tasks"]),
    "supplemental_states": sum(len(c["states"]) for c in states["cases"]),
    "supplemental_states_passed": sum(sum(x["pass"] for x in c["states"]) for c in states["cases"]),
    "supplemental_checks": sum(len(c["checks"]) for c in states["cases"]),
    "axe_violations": sum(len(c["axe"]["violations"]) for c in validation["cases"])
    + sum(len(s["axe"]["violations"]) for c in states["cases"] for s in c["states"]),
    "axe_incomplete_cases": sum(bool(c["axe"]["incomplete"]) for c in validation["cases"])
    + sum(bool(s["axe"]["incomplete"]) for c in states["cases"] for s in c["states"]),
    "protected_files": len(before),
    "changed_protected_files": changed,
    "source_hashes": source_hashes,
    "pass": validation["pass"] and states["pass"] and not changed,
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
figures = []
for image in sorted((OUT / "screenshots").glob("*-viewport.png")):
    label = image.name.removesuffix("-viewport.png")
    full = label + "-full.png"
    figures.append(
        f'<figure><a href="screenshots/{escape(full)}"><img loading="lazy" src="screenshots/{escape(image.name)}" alt="{escape(label)}"></a><figcaption>{escape(label)} · <a href="screenshots/{escape(full)}">full page</a></figcaption></figure>'
    )
html = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Appointments & Bookings prototype review</title><style>body{font:16px/1.5 system-ui;margin:0;background:#f6f7fb;color:#182235}main{max-width:1500px;margin:auto;padding:24px}a{color:#3949db}h1{font-size:28px}nav{display:flex;flex-wrap:wrap;gap:12px}nav a{padding:12px;border:1px solid #71819a;border-radius:8px;background:white}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px}figure{margin:0;padding:12px;background:white;border:1px solid #d8dfea;border-radius:12px;min-width:0}img{width:100%;height:280px;object-fit:contain;object-position:top;background:#eef1fa}figcaption{overflow-wrap:anywhere;padding-top:12px}a:focus-visible{outline:3px solid #3949db;outline-offset:3px}</style></head><body><main><h1>Services Appointments & Bookings</h1><p>Interactive prototype · synthetic records only. No Django, database, email, invoice or provider operations.</p><nav>"""
for view, label in [
    ("workspace", "Workspace"),
    ("detail", "Appointment details"),
    ("form", "Create/edit"),
    ("public", "Public booking"),
    ("request", "Request follow-up"),
]:
    html += f'<a href="../../dist/?view={view}&amp;theme=light">{label}</a>'
html += (
    f"</nav><p>{summary['render_cases_passed']}/{summary['render_cases']} render cases · {summary['task_checks_passed']}/{summary['task_checks']} task checks · {summary['supplemental_states_passed']}/{summary['supplemental_states']} supplemental states. {summary['axe_violations']} axe violations; {summary['axe_incomplete_cases']} incomplete cases retained in raw evidence.</p><p>D2 confirmations, D4 request handoff, D5 wizard/fallback and D6 outcome context remain proposals. Chromium evidence is not full accessibility certification or application/provider verification.</p><section>"
    + "".join(figures)
    + "</section></main></body></html>"
)
(OUT / "gallery.html").write_text(html)
print(
    json.dumps({key: value for key, value in summary.items() if key != "source_hashes"}, indent=2)
)
if not summary["pass"]:
    raise SystemExit(1)
