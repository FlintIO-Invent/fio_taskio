# Services Clients · design v1

Isolated Gate A design reference. No Django route, production assets, provider
or database access. Synthetic client data and in-page state only; reload resets
simulated edits. Phoenix 1.23.0 remains the production foundation.

Build with the existing pinned tools (no installation required in this checkout):

```sh
node ui-lab/tools/build.mjs services-clients
.venv/bin/python -B ui-lab/services-dashboard/tools/serve.py --root ui-lab --port 8766
```

Open http://127.0.0.1:8766/services-clients/dist/ . Review screen/scenario controls
sit outside the application frame. Screens: list, profile, create, edit, upload,
preview, result, draft. URL example: `?screen=profile&scenario=viewer&theme=dark`.
All functional handoffs expose the existing named route without sending requests.
CSV upload demonstrates supplied preview data; selected files are not parsed.

Sources import the approved lab tokens/shell and local Manrope. The frozen Step 4
and Appointments outputs are not rebuilt. New sources, built assets and evidence
are hashed for design approval. See the task reports in
`docs/design/motionmate-ui-lab/workflows/services-clients-20261117/`.

Validator: use an existing compatible Chromium via `PWA_CHROMIUM`; no downloads.
Every output path must be new to retain initial failures and prior evidence.

```sh
PWA_CHROMIUM=/path/to/existing/chrome .venv/bin/python -B \
  ui-lab/services-clients/validate.py --out evidence/NEW_RUN
```

Validation writes screenshots and JSON only in this task's evidence tree and
restricts all browser requests to GETs on the local static server. It imports no
Django settings and creates no database. Automated Chromium/axe evidence is not
full WCAG conformance, real server authorization or provider verification.
