# Catalogue validation results

All checks below use the verified owned session
`/tmp/motionmate-preview-session-1g0dntl_` or its AFTER-cluster runner-owned
`test_services_rollout`, never an ordinary application database.

- **47 Django contract/regression tests passed** (initial run). Its later browser
  batch failed because Playwright's default build was absent; preserved backend-1.log.
- **8 Catalogue Django tests passed** in the final focused run, including actual
  bound fields/errors, native create/edit/archive, inline-category conflict, tax
  retention, tenant isolation, CSRF, role checks, verified grace-expiry read-only
  policy and original Logistics rendered output. These overlap the initial suite;
  do not add their counts as independent tests.
- **1 native LiveServer browser journey passed** in focused-native-4.log: real login,
  invalid POST, retained draft through theme change, inline-category creation, saved
  decimal price and soft archive. ORM assertions run outside Playwright's async
  context. Earlier harness failures remain in native-form-browser-2/3.log.
- **3 offline setup refusal tests passed**; wrong settings/serve phase, route and
  changed source are rejected before an unverified database operation.
- Real frozen BEFORE and AFTER browser matrix: **40 cases per side**, covering list,
  create/edit service/category at 1440/768/390/320px and light/dark. AFTER: no page
  overflow, one main heading, checked 44px targets, zero module axe violations and
  no JavaScript errors. Empty/long/archive/no-booking and both-vertical role checks
  also completed. The final current-source capture rechecked four desktop/tablet/
  mobile cases after scoped label/placeholder styling refinements.
- Raw axe retains **16 incomplete case findings** in the matrix for human review.
  Full-page axe still reports the **two pre-existing shared Phoenix sidebar-label
  contrast failures** (4.41:1); unchanged shared shell is outside this manifest.
  This is not an AA certification.
- The human `readonly` fixture lacks a synthetic provider price identity and
  correctly redirects to subscription attention. Actual eligible grace-expiry
  catalogue read/no-write behavior is covered by the final isolated Django test;
  the preview redirect is not presented as a read-only catalogue browser pass.
- Both review databases' initial synthetic domain/financial inventories were
  compared after validation and remain unchanged. Native write checks used the
  separate test database. No reset, reseed, provider or ordinary database operation.
- All 15 approved source paths exist; three original non-Services content bodies
  exactly match frozen BEFORE bytes. The Logistics rendering regression compares
  original/current responses, normalizing only CSRF and inter-tag whitespace.
  Ruff/format, scope/hash checks and git diff --check passed.

Evidence: BEFORE `before/evidence/catalogue-1795207713730264808/report.json`,
AFTER matrix `after/evidence/catalogue-1795207888723186468/report.json`, current
source capture `after/evidence/catalogue-final-1795208502648214474/report.json`.
Logs and full captures remain external; four representative screenshots are saved
here. Final current source changes after the full matrix were test/harness fixes
and scoped form label/placeholder styles, checked by the final capture and journey.

Reproduce with the existing installed browser:

```sh
export PWA_CHROMIUM=/home/mzero/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome
PYTHONPATH=scripts .venv/bin/python -B -m ui_preview.catalogue_checks --session /tmp/motionmate-preview-session-1g0dntl_ --suite backend
PYTHONPATH=scripts .venv/bin/python -B -m ui_preview.catalogue_checks --session /tmp/motionmate-preview-session-1g0dntl_ --suite capture-after
```

Installed browser: Chrome for Testing 148.0.7778.96. Existing preview debug-allocator
workaround is retained; no ordinary-runtime or provider readiness is claimed.
