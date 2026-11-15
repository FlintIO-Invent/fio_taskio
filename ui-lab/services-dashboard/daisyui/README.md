# DaisyUI Services refinement — Step 4

The approved distribution remains frozen. Use the
[current setup runbook](../../../docs/design/motionmate-ui-lab/REPRODUCIBILITY.md)
for Python/Chromium/npm setup and real Django reviews. Full historical galleries
and reports are in the [local archive](../../../docs/design/motionmate-ui-lab/PRESERVATION.md).
Historical validators need their original evidence/Tabler output and source
epoch; their saved scope hashes are not current application regression checks.

This is the existing standalone prototype, refined for review. It uses synthetic
fixtures and intercepts navigation and setup submissions locally. It never
connects to Django or an application database.

From the repository root:

```sh
npm ci --prefix ui-lab/services-dashboard/daisyui --ignore-scripts --no-audit --no-fund
npm run build --prefix ui-lab/services-dashboard/daisyui
.venv/bin/python ui-lab/services-dashboard/tools/serve.py --port 8765
```

Review URLs:

- Default: `http://127.0.0.1:8765/daisyui/dist/?theme=light`
- Dark: `http://127.0.0.1:8765/daisyui/dist/?theme=dark`
- Same refined interface, Nunito Sans: append `&font=nunito`.
- Manrope explicitly: append `&font=manrope`.
- Existing states: append `&state=long`, `empty`, `locked`, `viewer`, `welcome`,
  `guide`, or any state from the unchanged shared fixture manifest.
- Review gallery: `http://127.0.0.1:8765/daisyui/evidence/step4/gallery.html`.
- Frozen original DaisyUI build:
  `http://127.0.0.1:8765/daisyui/evidence/step4/original-dist/?theme=light`.

Manrope was subsequently approved as the default in the Motionmate design system. Both fonts
are local assets; the URL override has no persistent preference. The theme uses
the existing lab-only storage key. No production preference key is touched.
The new exact dependency is `@fontsource-variable/manrope@5.3.0` (OFL-1.1),
with its Latin variable WOFF2 and license copied by this prototype's build.
All framework and build-tool pins remain unchanged. Nunito, logo, icons,
fixtures, route contracts and shared controllers remain unchanged.

Validation (requires the already installed lab tools and Python environment):

```sh
.venv/bin/python ui-lab/services-dashboard/daisyui/tools/validate_refinement.py
.venv/bin/python ui-lab/services-dashboard/daisyui/tools/validate_details.py
.venv/bin/python ui-lab/services-dashboard/daisyui/tools/validate_contrast_states.py
.venv/bin/python ui-lab/services-dashboard/daisyui/tools/verify_contracts.py
.venv/bin/python ui-lab/services-dashboard/daisyui/tools/make_gallery.py
.venv/bin/python ui-lab/services-dashboard/daisyui/tools/verify_scope.py
```

These scripts start their own GET-only loopback server. Evidence is written
only into `daisyui/evidence/step4/`. The first adapts the original validation
gates for the refined prototype and approved font candidate, and compares
fixtures/routes against the saved Step 3 results. The second captures identical
content in both fonts, checks every record field at desktop/mobile widths,
reviews the previously incomplete contrast cases from both unchanged baselines,
and samples component states and keyboard focus.
The additional scripts review every final contrast indeterminate and pressed/
focus state, compare all route/form/hook contracts, index the screenshots, and
verify protected files, evidence dimensions and deterministic build output.

The original Step 3 tools and evidence remain intact. Do not run their full
capture command when preserving the original comparison screenshots: that
command intentionally refreshes the original evidence directory. This
refinement has separate validation commands and output paths.

The report is `docs/design/motionmate-ui-lab/04-daisyui-refinement.md`.
Production integration, other Services pages, Logistics, databases, migrations,
commits, pushes and deployment remain outside this lab phase.
