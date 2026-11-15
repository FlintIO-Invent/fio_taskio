"""Index preserved originals and new Step 4 captures; never rewrites Step 3 evidence."""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/step4"
results = json.loads((OUT / "results.json").read_text())
parts = [
    """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Motionmate Services — Step 4 review evidence</title>
<style>body{font:16px/1.5 system-ui;background:#f6f7fb;color:#182235;margin:24px}a{color:#3949db}h1{font-size:28px}h2{margin-top:40px}.comparison{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}.fonts{grid-template-columns:repeat(2,minmax(0,1fr))}figure{margin:0}img{width:100%;height:auto;border:1px solid #71819a}figcaption{margin:8px 0}table{border-collapse:collapse;width:100%;background:white}th,td{padding:10px;text-align:left;border-bottom:1px solid #d8dfea}a:focus-visible{outline:3px solid #3949db;outline-offset:3px}@media(max-width:800px){.comparison{grid-template-columns:1fr}body{margin:16px}}</style>
<h1>Motionmate Services · DaisyUI refinement</h1><p>Actual Chromium captures. Original DaisyUI and Tabler screenshots are preserved Step 3 evidence. Refined screenshots default to Manrope; use the controlled typography comparison below to isolate font effects.</p>
<p><a href="../../dist/?theme=light">Refined light</a> · <a href="../../dist/?theme=dark">Refined dark</a> · <a href="../../dist/?theme=light&amp;font=nunito">Refined Nunito Sans</a> · <a href="original-dist/?theme=light">Frozen original DaisyUI</a></p>"""
]

for width in (1440, 768, 390):
    for theme in ("light", "dark"):
        parts.append(f"<h2>{width}px · {theme}</h2><div class='comparison'>")
        for name, path in (
            (
                "Original DaisyUI · Nunito Sans",
                f"../../../evidence/screenshots/daisyui-populated-{width}-{theme}",
            ),
            ("Refined DaisyUI · Manrope", f"screenshots/daisyui-populated-{width}-{theme}"),
            (
                "Tabler reference · Nunito Sans",
                f"../../../evidence/screenshots/tabler-populated-{width}-{theme}",
            ),
        ):
            parts.append(
                f"<figure><figcaption>{name} · <a href='{path}-full.png'>Full page</a></figcaption><a href='{path}-viewport.png'><img loading='lazy' alt='{name}, {width}px, {theme}' src='{path}-viewport.png'></a></figure>"
            )
        parts.append("</div>")

parts.append(
    "<h2>Controlled typography comparison</h2><p>Identical refined content, dimensions and styles. Only the font differs.</p>"
)
for width in (1440, 768, 390):
    for theme in ("light", "dark"):
        parts.append(f"<h3>{width}px · {theme}</h3><div class='comparison fonts'>")
        for font in ("manrope", "nunito"):
            path = f"details/font-{font}-{width}-{theme}"
            parts.append(
                f"<figure><figcaption>{font.title()} · <a href='{path}-full.png'>Full page</a></figcaption><a href='{path}-viewport.png'><img loading='lazy' alt='{font}, {width}px, {theme}' src='{path}-viewport.png'></a></figure>"
            )
        parts.append("</div>")

parts.append(
    "<h2>All refined states</h2><table><tr><th>State</th><th>Width</th><th>Theme</th><th>Captures</th></tr>"
)
index = [
    "# Step 4 refined DaisyUI screenshots\n",
    "See [gallery](gallery.html) for before/after and controlled typography comparisons.\n",
    "| State | Width | Theme | Viewport | Full page |",
    "| --- | ---: | --- | --- | --- |",
]
for case in sorted(results["scenarios"], key=lambda c: (c["state"], -c["width"], c["theme"])):
    state, width, theme = (case[k] for k in ("state", "width", "theme"))
    prefix = f"screenshots/daisyui-{state}-{width}-{theme}"
    parts.append(
        f"<tr><td>{html.escape(state)}</td><td>{width}</td><td>{theme}</td><td><a href='{prefix}-viewport.png'>Viewport</a> · <a href='{prefix}-full.png'>Full page</a></td></tr>"
    )
    index.append(
        f"| {state} | {width} | {theme} | [Viewport]({prefix}-viewport.png) | [Full]({prefix}-full.png) |"
    )
parts.append("</table></html>")
(OUT / "gallery.html").write_text("\n".join(parts) + "\n")
(OUT / "screenshot-index.md").write_text("\n".join(index) + "\n")
print("Step 4 gallery and 132-case screenshot index ready")
