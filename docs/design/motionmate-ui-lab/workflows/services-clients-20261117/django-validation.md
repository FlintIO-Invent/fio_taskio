# Services Clients Django validation

All database and browser checks used session
`/tmp/motionmate-preview-session-p29z5cgt`, with independent owned PostgreSQL
clusters. Runtime settings are `ui_preview.settings`; regression settings are
`taskio.services_test_settings`. Ownership, process, source and live database
identity are checked before execution. Ordinary databases, external providers,
email, workers and interactive financial writes are unavailable. Existing
migrations were applied only to empty authorized disposable databases.

## Automated results

| Check | Result | Evidence |
| --- | --- | --- |
| New Clients Django integration suite | 15 passed | `backend-and-logistics-final.log` |
| Active Logistics browser regression | 80 screens, five roles, four widths, both themes; test and database teardown passed | `backend-and-logistics-final.log`; evidence index |
| Existing CRM/import/capacity/financial/booking regression suite | 219 passed, one pre-existing failure out of 220 | `backend-regression-01.log` |
| Frozen original-source reproduction | Same pre-existing failure reproduced | `backend-baseline-known-failure-02.log` |
| Fixture/adapter refusal unit checks | Four passed | `ui_preview.test_clients` |
| Core AFTER capture | 56 HTTP 200 screens, no browser page errors; zero axe violations in new Clients content | evidence index |
| Services roles and edge states | 76 passed, including all 32 expanded fields and RTL | evidence index |
| Real create/edit/archive/import journeys | All eight width/theme combinations passed; 72 checks per passing case | evidence index; final journey delta log |
| Final contacts/modal/invoice GET review | Eight width/theme cases passed | `final-readonly-contact-delta.log` |
| Additional equivalent-profile and subscription review | 40 passing read-only cases, including grace/restricted/module-limited tenants | `final-readonly-review-02.log`; cases file |
| Final form and equivalent-directory delta | 32 passed; both country widget types, retained locality and one optional marker | `final-form-delta-03.log` |
| Existing draft-save browser test | All four appointment/request saves and assertions passed; process then crashed in GC teardown | `existing-draft-browser-final.log` |
| Scoped Ruff, JavaScript syntax and whitespace | Passed | final static-check log |
| Protected source, design and original fixture comparison | Passed | `final-preservation.json`; `legacy-branch-preservation.json` |

Browser widths were 1440, 768, 390 and 320 pixels in both existing themes.
Journeys exercised real Django GET/POST and CSRF, validation and return routes,
all 32 field values, country/locality normalization, filter aliases, six sort
subjects, 10-row pagination, select/clear, theme preservation, inline 400/201
responses and draft retention, archive cancel/Escape/POST, CSV partial rows,
duplicates, blocked previews, confirmation/retry, tenant 404 and missing-CSRF 403.
No financial POST was attempted in interactive review.

Read-only review checked owner/admin/staff/accountant/viewer controls, quota,
empty/long/partial clients, no history, absent modules, all fields visible with
labels, RTL layout, reflow and 44-pixel targets in the redesigned content. The
archive modal was checked independently with axe and focus assertions. Existing
website/mail/phone/WhatsApp destinations are asserted in Django tests; runtime
preview deliberately rewrites external contact destinations to its disabled page.

## Failures and practical limits

- The existing service-import test expects “Required columns” although the
  existing service CSV form permits optional columns. The same assertion fails
  against the untouched BEFORE source. It is outside Clients scope and remains
  unchanged; the full regression suite is not reported as green.
- The assigned-staff BEFORE profile returns HTTP 500 because the old template
  resolves `assigned_to.username` on a custom email-based user. All eight
  width/theme failures remain in the BEFORE capture. AFTER renders the same
  assigned record. An equivalent unassigned/no-history fixture provides the
  additional visual comparison; the BEFORE source was not repaired.
- Scoped Clients axe checks pass. Full-page checks retain shell contrast and
  unnamed-link findings, and unchanged appointment/request content has separate
  target issues. This review does not establish whole-page WCAG conformance.
- The preview launcher uses the existing `PYTHONMALLOC=debug` workaround. The
  existing draft test passed its assertions and then SIGSEGV occurred in forced
  garbage collection during teardown even with that setting. Original logs are
  retained. This remains a runtime/test-process limitation, not a passing process
  result. Its stranded runner-owned test database was dropped only after exact
  cluster/catalog ownership and zero active sessions were independently verified;
  no sessions were terminated or review records removed.
- The first active Logistics test passed 80 screens but originally left a worker
  connection at teardown. The task-owned test adapter now closes its worker
  connections. A fresh final run passed all 16 integration/browser tests and
  teardown. Both the failed attempt and restricted identity-checked recovery are
  retained. Database guards were not weakened.
- Early fixture/selector/count/focus-timing mistakes and guard-refused attempts
  remain in their original logs. Successful reruns are identified separately in
  the evidence index. The final locality delta found and fixed a control reuse
  issue, rather than relaxing its draft-preservation assertion.
- Chromium was used. Safari, Firefox, screen-reader operation, native browser
  zoom, real providers and ordinary-runtime stability were not verified. No
  ordinary-runtime or release readiness is claimed.

The original Gate A validation report is immutable. This separate report records
the authorized implementation review and does not change earlier evidence.
