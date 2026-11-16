"""Index the actual captures, not generated illustrations."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
j = json.loads((root / "evidence/results.json").read_text())
md = [
    "# Actual Chromium screenshot index",
    "",
    "All standard captures use DPR 1. Each cell links the initial viewport and complete page. Supplementary zoom captures use the documented layout emulation.",
    "",
]
for f in ["tabler", "daisyui"]:
    md += [
        f"## {f.title()}",
        "",
        "| State | 1440 light | 1440 dark | 768 light | 768 dark | 390 light | 390 dark |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for state in j["states"]:
        cells = [state]
        for w in [1440, 768, 390]:
            for t in ["light", "dark"]:
                stem = f"{f}-{state}-{w}-{t}"
                cells.append(
                    f"[Viewport](screenshots/{stem}-viewport.png) · [Full](screenshots/{stem}-full.png)"
                )
        md.append("| " + " | ".join(cells) + " |")
    md.append("")
md += ["## Interaction and reflow captures", ""]
for p in sorted((root / "evidence/screenshots").glob("*.png")):
    if not p.stem.endswith(("-viewport", "-full")):
        md.append(f"- [{p.stem}](screenshots/{p.name})")
(root / "evidence/screenshot-index.md").write_text("\n".join(md) + "\n")
html = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Motionmate prototype screenshot gallery</title><style>body{font:16px/1.5 system-ui;background:#f6f7fb;color:#182235;margin:0;padding:24px}h1{font-size:28px}label{margin-right:16px;display:inline-block}select{font:inherit;min-height:44px;padding:8px;border:1px solid #71819a;border-radius:8px}a{color:#3949db;display:inline-block;padding:10px 0;min-height:44px;margin-right:20px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}article{min-width:0}img{display:block;max-width:100%;height:auto;border:1px solid #d8dfea;background:white}@media(max-width:768px){.pair{grid-template-columns:1fr}}:focus-visible{outline:2px solid #3949db;outline-offset:3px}</style><main><a href="../">← Lab review</a><h1>Actual Chromium captures</h1><p>Identical state, viewport, theme and synthetic data. No framework selected.</p><label>State <select id="state">"""
html += "".join(f'<option value="{s}">{s.replace("-", " ")}</option>' for s in j["states"])
html += """</select></label><label>Width <select id="width"><option>1440</option><option>768</option><option>390</option></select></label><label>Theme <select id="theme"><option>light</option><option>dark</option></select></label><div class="pair"><article data-f="tabler"><h2>A · Tabler + Bootstrap</h2><a data-kind="viewport">Viewport PNG</a><a data-kind="full">Full PNG</a><img alt="Tabler screenshot"></article><article data-f="daisyui"><h2>B · Tailwind + DaisyUI</h2><a data-kind="viewport">Viewport PNG</a><a data-kind="full">Full PNG</a><img alt="DaisyUI screenshot"></article></div><a href="screenshot-index.md">Complete screenshot index</a><a href="results.json">Raw measurements</a></main><script>function update(){const state=document.querySelector('#state').value,width=document.querySelector('#width').value,theme=document.querySelector('#theme').value;document.querySelectorAll('[data-f]').forEach(a=>{const stem='screenshots/'+a.dataset.f+'-'+state+'-'+width+'-'+theme;a.querySelector('img').src=stem+'-viewport.png';a.querySelector('img').alt=a.dataset.f+' '+state+' '+width+'px '+theme;a.querySelectorAll('[data-kind]').forEach(link=>link.href=stem+'-'+link.dataset.kind+'.png');});}document.querySelectorAll('select').forEach(s=>s.addEventListener('change',update));update();</script></html>"""
(root / "evidence/gallery.html").write_text(html + "\n")
p = root / "index.html"
launcher = p.read_text()
if '<a href="evidence/gallery.html">' not in launcher:
    p.write_text(
        launcher.replace(
            '<a href="evidence/screenshot-index.md">Screenshot index</a>',
            '<a href="evidence/gallery.html">Screenshot gallery</a><a href="evidence/screenshot-index.md">Screenshot index</a>',
        )
    )
