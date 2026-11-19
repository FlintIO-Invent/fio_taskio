# Services Invoices — design v1

Gate A design reference for the complete Services invoicing journey. Synthetic
data and local in-page simulation only. No Django imports, database writes,
provider calls or production modifications. Existing Phoenix remains in place.

Build with the installed pinned lab tools, without modifying the frozen registry:

```sh
node ui-lab/services-invoices/build.mjs
```

The existing read-only lab server serves:
http://127.0.0.1:8766/services-invoices/dist/ . If it is absent, the existing server
script supports `--root ui-lab --port 8766`; do not stop another listener.

Screens: `list`, `create`, `edit`, `detail`, `payment`, `adjust`, `document`, `email`.
Use `?screen=document&scenario=draft&theme=dark` to review a clean customer copy
while the internal workspace still identifies the Draft. Review controls sit
outside the product frame. Scenario/filter query parameters are separate.

The document screen has browser Print / save design PDF. The validation gallery
also links retained generated PDFs, including long multipage examples. These are
Chromium design references; they do not prove actual ReportLab integration.

Sources import approved shared lab components/tokens read-only. A task-owned
builder reuses Tailwind 4.3.5, DaisyUI 5.8.0, esbuild 0.28.2 and Manrope 5.3.0
from the existing pinned toolchain. No installs or shared builds are performed.

Validation writes only new owned evidence paths and blocks non-GET, application
and external network requests. Do not reuse an existing output folder. See the
task audit/brief/state under
`docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/`.

Run the retained synthetic checks with an installed Chromium; each output must be new:

```sh
PWA_CHROMIUM=/path/to/existing/chrome .venv/bin/python -B ui-lab/services-invoices/validate.py --suite matrix --out evidence/NEW_MATRIX
PWA_CHROMIUM=/path/to/existing/chrome .venv/bin/python -B ui-lab/services-invoices/validate.py --suite journeys --out evidence/NEW_JOURNEYS
PWA_CHROMIUM=/path/to/existing/chrome .venv/bin/python -B ui-lab/services-invoices/validate.py --suite pdf --out evidence/NEW_PDFS
PWA_CHROMIUM=/path/to/existing/chrome .venv/bin/python -B ui-lab/services-invoices/supplement.py --out evidence/NEW_SUPPLEMENT
```

Approval freezes v1 source and evidence. Later runs must remain separate and must
not overwrite the v1 gallery or approved artifacts. The review server is kept
available; no cleanup or release is implied.
