# Services Clients v1 — validation boundary

This is synthetic browser and source evidence for Gate A. No Django server,
ordinary database, test database, migration, provider, mail or financial writer
was accessed. Actual Django BEFORE/AFTER and backend regression checks remain
separately authorized work after Gates A and B.

Commands executed from the repository root:

```sh
node ui-lab/tools/build.mjs services-clients
.venv/bin/python -B ui-lab/services-dashboard/tools/serve.py --root ui-lab --port 8766
PWA_CHROMIUM=/home/mzero/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome \
  .venv/bin/python -B ui-lab/services-clients/validate.py --out evidence/run-02
PWA_CHROMIUM=/home/mzero/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome \
  .venv/bin/python -B ui-lab/services-clients/supplement.py
PWA_CHROMIUM=/home/mzero/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome \
  .venv/bin/python -B ui-lab/services-clients/final_delta.py
```

- Full matrix: 256/256 passing at 1440/768/390/320px in light/dark.
- Connected journeys: 8/8 passing, 316 interaction assertions. Search, activity
  aliases, locality, sorting, pagination, selection, profile, notes editing,
  form errors/drafts, create/edit returns, archive, import confirmation/retry,
  inline draft preservation, focus, theme and real-route handoffs.
- Supplement: 8/8 passing, 126 assertions. All 32 real form field names extracted
  from PrivateClientForm AST; all visible/labeled with every section expanded;
  normal motion, dialog containment/wrap, focus ring/return, quota-denied inline
  creation, partial profile and mobile drawer scroll restoration.
- Final additive empty-history fixture: see final-delta/results.json and the
  prototype report for final-build parity evidence.
- Full-page axe WCAG A/AA tagged checks, target/reflow/type/theme/font checks,
  semantic text/control/focus/hover contrast. No axe violations or incompletes in
  the full matrix, journey end states or supplemental expanded/dialog states.
- Browser requests restricted to the local static server and GET only. No
  browser errors, failed requests or external calls in passing final checks.
- Protected source: 12,619 files unchanged; prior registry entries unchanged.
  Production, Logistics, dashboard and Appointments outputs were preserved.
- Focused Ruff and diff checks pass; deterministic task-only rebuild passes.
  Offline workflow state consistency is checked separately. The repository-wide
  check_ui_workflow.py reports a pre-existing Step 7 source-manifest mismatch
  for src/apps/crm/tests.py. That file matches HEAD and the intake baseline;
  this task did not change it. The old preservation manifest was not rewritten.

## Retained failures and limitations

Repository checker finding: historical approved hash c4fc60270a62cb107c707bcb5af55d2fc1a453d957093ca19c9673d47280301f differs from current/HEAD/intake hash 2f87d446cbc25ef9c14f4c21546965abb6753470d2acdfb8752feb0751fd1523 for src/apps/crm/tests.py. This remains an unrelated repository consistency issue.


The first default Playwright browser lookup failed because Chromium shell 1243
is absent. No installation was run; existing executable 1223 was selected,
reporting Chromium 148.0.7778.96. An initial inline axe script injection was
blocked by CSP; the established Playwright evaluation mechanism works without
weakening the product CSP. Initial lint formatting was corrected.

run-01 retains 146 failed matrix cases and eight incomplete journeys: the
validator mishandled shorthand hex colors, clipped mobile table-header sort
controls were focusable, and a test selector matched two directory links.
The parser and selector were fixed; sorting and select-all moved to a visible,
44px toolbar while semantic column headers remain. Mobile section links now
form a readable two-column group. Raw run-01 files were not overwritten.

Synthetic role/module/quota/financial projections do not establish server
security, tenant isolation, settlement or provider correctness. CSV files are
not parsed here: supplied immutable preview fixtures demonstrate the reviewed
steps. Appointment/request/invoice destinations are explicit local handoffs.
No ordinary-runtime stability claim is made. Firefox, Safari, assistive
technology, RTL and native zoom were not exercised. Chromium reflow at 320px
is not a substitute for native zoom or full WCAG conformance.
