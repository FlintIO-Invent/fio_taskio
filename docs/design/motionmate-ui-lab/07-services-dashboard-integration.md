# Step 7 — Services dashboard integration

15 November 2026 · authorized local implementation · `agent_dashboard`,
`/crm/agent/dashboard/` · Strategy B within Phoenix 1.23.0.

**Approved local implementation. No release authorization.** The approved visual direction
is expressed through scoped CSS, local Manrope and a Django partial. Phoenix,
Bootstrap, navigation, business policies and the existing build remain in place.
No production Tailwind/DaisyUI packages, lab runtime imports or replacement shell
were introduced.

Step 7 and the Step 8 interactive workflow were subsequently approved by the
user. The evidence below remains a historical report of the original runs;
Phase 2 did not rerun them. Current setup uses the
[portable runbook](REPRODUCIBILITY.md), the verified Git baseline and the
[separate evidence archive](PRESERVATION.md). Historical local URLs may be absent
in a fresh clone.

## Actual file changes

The [Step 6 manifest](06-production-integration-audit.md) is the implementation
boundary. These are the complete application/documentation changes for Step 7:

| File | Change |
| --- | --- |
| `src/templates/inheritance/dashboard_parent.html` | Default-preserving `page_assets`, `page_body_attributes`, `services_mobile_search` hooks. Brand/theme accessible names only when the Services-dashboard marker is present. |
| `src/templates/crm/agent_dashboard/agent_dashboard.html` | Conditional dashboard assets/body marker/overview include; omit unsupported mobile search only here. Retain Logistics header/snapshot and onboarding includes/scripts. |
| `src/apps/crm/views.py` | Three Services-context additions only: `services_dashboard_ui`, `dashboard_timezone`, `dashboard_now`. |
| `src/apps/crm/tests.py` | Three presentation assertions updated for the new appointment/invoice headings and absence of locked appointment rows. Other assertions retained. |
| `src/templates/crm/agent_dashboard/includes/services_overview.html` — new | Actual server-provided appointments, requests, invoice presentation, workspace defaults, public booking link and existing setup trigger. |
| `src/static/assets/css/services-dashboard.css` — new | Dashboard-scoped typography, colors, panels, responsive records, themes, focus and control sizes. Scoped compatibility adjustments for Phoenix section padding and existing subscription notice spacing. |
| `src/static/assets/js/services-dashboard.js` — new | Native disclosure enhancement, exact-URL clipboard feedback, dashboard-local onboarding progress names. |
| `src/static/assets/fonts/manrope/manrope-latin-wght-normal.woff2` — new | Local variable Latin Manrope, copied from the approved lab asset. |
| `src/static/assets/fonts/manrope/OFL.txt` — new | Font license retained. |
| `src/apps/crm/test_services_dashboard_ui.py` — new | Disposable-only fixtures and 13 server/static contracts. |
| `scripts/services_dashboard_ui_browser_check.py` — new | Actual Django/Chromium baseline, comparison and interaction checks. |
| This document — new | Implementation, evidence, limitations and review/rollback instructions. |

No changes to models, migrations, URLs, forms, billing services, permissions,
subscription policies, dependencies, configuration, Phoenix bundles, collected
static output, Logistics source or other Services templates. Existing edits to
`AGENTS.md`, existing design documentation, ignored skill/reference files and
`ui-lab/` were preserved. Approved Step 4/5 evidence was not regenerated.

## Implemented behavior and preserved contracts

Appointments lead the page; booking follow-up sits beside them on wide screens.
Invoice follow-up, workspace information and the existing ready-to-share booking
link follow in reading order. Phone layouts initially show three appointments
and requests with keyboard-operable native disclosures. Desktop/tablet show all
records supplied by the existing five-record preview. All five remain available
without JavaScript; the UI performs no extra fetching or record creation.

The view's existing querysets, ordering, counts, time windows and flags remain
authoritative. Today's count and future appointment count have separate labels.
Requests remain eligible existing `Lead` records; their preferred times are not
presented as scheduled appointments. Detail/list links keep their existing named
routes, including `?state=needs_follow_up`. No new creation, scheduling, payment
or subscription operation was added.

Invoice rows reuse `Invoice.presentation`, `financial.billing_business` and the
existing invoice-status include. Workspace-currency amounts and all-currency
counts are explicitly distinguished. Issued value is not labeled cash received.
The existing HTML-commented finance-totals include remains commented, under the
same invoice display guard. There is no currency conversion or UI settlement
calculation. Saved USD receipt currency remains authoritative after EUR defaults.

The overview's timezone block uses the already resolved business timezone,
without globally activating it or changing business-day calculations. Semantic
appointment datetimes retain UTC. Local display includes per-record ISO offsets,
including both occurrences of a repeated DST hour. Django's `date:"O"` omits
ambiguous offsets; ISO datetime suffixes avoid that omission. Invalid business
zones reuse the existing UTC fallback. Other pages retain their original time
presentation.

The existing Bootstrap setup modal/offcanvas, IDs, targets, hidden operation
fields, CSRF and real POST endpoints remain. The offcanvas's static backdrop and
Escape behavior remain deliberate. Dashboard-only enhancements add readable
controls, progress names, focus rings, a keyboard-reachable native theme checkbox
and 44px action targets. The dashboard omits the known broken mobile search
trigger; other Services pages retain their existing behavior.

Clipboard success announces “Link copied”; busy state prevents duplicate clicks.
Unavailable/denied clipboard access selects the exact server-provided URL and
announces manual-copy guidance. No replacement URL or public booking policy is
constructed in JavaScript.

### Deliberate differences from the Step 4 preview

The existing Phoenix sidebar, brand lockup, account menu, Nunito shell typography,
992px navigation breakpoint and theme storage remain. Manrope applies to the new
working content. Existing Font Awesome/Feather assets remain. The prototype's
parallel shell, theme controls, simulated actions and synthetic business rules
were not copied. Actual Django fields, currencies, timezone offsets and setup
state can produce taller records than the frozen canonical fixture.

Phoenix applies padding to every `section`; the new panel class neutralizes that
padding locally. Existing subscription notice containers also inherit full-page
minimum height and insufficient top clearance. Scoped dashboard CSS places those
notices below the fixed header and removes the empty gap, preserving their
markup, actions and conditions. Global Phoenix overrides remain untouched.

## Disposable environment and baseline

The live PostgreSQL process was rechecked before fixture execution, including
host, port, actual data directory, system identifier and databases. Subsequent
verification also ran before final test commands:

- PostgreSQL 14.24, `127.0.0.1:55487`.
- Data directory `/tmp/motionmate-step7-rg6s8g_0/pgdata`.
- Cluster identifier `7708225022795438932`, matching the disposable marker.
- Base databases only `postgres`, `template0`, `template1`; public schema empty.
- `taskio.services_test_settings`; Django creates/destroys only
  `test_services_rollout` in this private cluster.
- In-memory email/cache; final runner disables provider keys and blocks Python
  DNS/connections outside approved loopback destinations. No external attempts
  occurred. Browser requests are restricted to the test server. Existing Google
  Nunito is substituted with the approved local font bytes; unused external
  Unicons CSS/Turf JS are replaced with inert test responses.

Synthetic fixtures contain five appointments, five requests, three invoices,
five Services roles, empty/long/locked/grace/restricted variants and Logistics
owner/staff memberships. Logistics uses the existing local test billing bypass;
no provider configuration or live entitlement was verified.

**Before connecting the new components**, the original Django-rendered dashboard
and representative unchanged pages were captured: 102/102 browser cases passed
their baseline checks. Raw baseline accessibility findings were retained.
No ordinary database was queried, migrated, seeded or modified.

## Validation evidence

Evidence root: `/tmp/motionmate-step7-rg6s8g_0/`.

| Check | Result |
| --- | --- |
| New dashboard server/static tests | **13 passed**, within the final 267-test run. Covers roles, assets, unchanged projections/domain records, tenant isolation, empty/locked/restricted context, CSRF and onboarding POST, local time/DST/fallback, mixed EUR/USD receipts, capped previews and temporary manifest/font rewriting. |
| Existing focused suites | 240 tests reconstructed against the saved original view/tests/templates: **5 failures, 9 errors**. Final 267-test run has the **identical 5 failures and 9 errors**, with no new issue identities. |
| Additional existing checks | **14 passed**: money localization, subscription grace/restriction/redirects, booking creation and tenant/read-role guards, recorded payments, receipt currency and normal payment UI. |
| Final Django checks | No Django system-check issues. No external Python network attempts. Final log: `final-django-tests.log`. |
| Final Chromium matrix | **102/102 passed**, Chromium 148.0.7778.96. Ten Services dashboard scenarios × three widths × two themes; five unchanged Services pages and Logistics owner/staff views use the same width/theme matrix. Data projections, ordered IDs and onboarding form contracts match the baseline. |
| Other-page regression captures | **42/42 cases, 84/84 PNGs pixel-identical** to baseline (viewport and full-page). No new dashboard CSS/JS/font requests on these pages. |
| Real browser interactions | **Passed**: appointment/request/invoice details and lists, public-booking new tab, Bootstrap menus/navigation, Phoenix theme persistence and Tab/Space control, disclosures, visible focus, dialog keyboard containment, clipboard feedback, real CSRF onboarding POST/redirects, Next/Back/start task, 320px reflow, normal/reduced motion and no-JS records/manual copy. |
| Time/currency/direction browser checks | **Passed**: both repeated 02:30 Amsterdam DST times with distinct offsets; EUR workspace balance with saved USD receipt/partial payment at 390/1440px in both themes; existing RTL switch at 390px. A further focused pass confirms the local Manrope face is loaded in Chromium. |
| Browser accessibility/errors | **Zero violations and zero incompletes in the dashboard region**, and no new full-document violation nodes against baseline. Inherited full-document findings remain; raw incompletes retained. No page errors or failed requests in the final matrix/interaction checks. |
| Source/static inspection | Ruff, JavaScript syntax and `git diff --check` pass. View AST matches the saved original after removing only the three new presentation keys. |
| Scope preservation | All **13,829** starting-file hashes checked: only the four authorized existing files differ; no missing files or changes outside that manifest. |

The original-source regression run was reconstructed **after implementation**
using saved original Python modules and a temporary original-template loader.
It did not overwrite or revert the working tree. This is distinct from the
actual pre-change browser capture. See `existing-before-reconstructed.log`,
`final-django-tests.log`, `existing-regression-comparison.json` and
`source-preservation.json`.

The final browser module ran three tests successfully in 226.449 seconds
(`final-browser.log`). The explicit font/time/currency follow-up passed in
9.708 seconds (`font-and-time-browser.log`). Full-page axe still records contrast
findings in 70 cases and link-name findings in 24 cases, including unchanged
comparison pages. Full-page incompletes are color-contrast in 32 cases and
aria-valid-attr-value in six. These incompletes require manual review.
Native Bootstrap permits tabbing to browser chrome; returning must re-enter the
dialog without focusing another application control. The keyboard check covers
that boundary rather than treating browser chrome as an application escape.

Earlier setup/development runs are not presented as passes. They exposed runner
debug-mode/settings metadata and synthetic subscription setup issues, a browser
route-callback signature error, asynchronous test timing, and presentation label
assertions. The first server run also caught the DST offset omission. Final
results supersede these attempts; the logs and development captures stay in the
temporary evidence directory.

### Existing failures, kept separate

The following issue identities reproduce with the original source:

- Four `CurrentBusinessTests` errors and four role subtest errors in
  `OnboardingVisibilityTests`: existing fixture capacity verification rejects
  their memberships (`QuotaError`).
- `CRMBusinessScopingTests.test_business_service_import_page_displays_examples_in_browser`:
  expects the old “Required columns” text.
- Three Logistics financial tests expect the old “Mark as Sent” text:
  `test_normal_ui_issues_protected_draft_without_modifying_lines`,
  `test_service_staff_keep_generic_invoice_management_without_location_assignments`,
  `test_staff_keep_scoped_invoice_access_without_dashboard_summaries`.
- `LocationAccessTests.test_creation_and_route_tampering_cannot_expand_access`:
  expected `PermissionDenied` is not raised.
- `LocationAccessTests.test_shipment_cargo_expected_at_authorized_site_and_existing_lifecycle`:
  shipment operation raises the existing role denial.

These tests were not weakened or repaired. This is a demonstrated unchanged
baseline, not a claim that the existing suite is green. The two Logistics
authorization mismatches warrant a separate investigation.

## Screenshots and local review

Open the [local before/after gallery](http://127.0.0.1:8771/index.html). Select
scenario, width and theme; open full-page PNGs for lower sections.

| Capture | Before | After |
| --- | --- | --- |
| Desktop · light | [Original](http://127.0.0.1:8771/before/populated-1440-light-viewport.png) | [Integrated](http://127.0.0.1:8771/after/populated-1440-light-viewport.png) |
| Tablet · dark | [Original](http://127.0.0.1:8771/before/populated-768-dark-viewport.png) | [Integrated](http://127.0.0.1:8771/after/populated-768-dark-viewport.png) |
| Phone · dark | [Original](http://127.0.0.1:8771/before/populated-390-dark-viewport.png) | [Integrated](http://127.0.0.1:8771/after/populated-390-dark-viewport.png) |
| Restricted · phone | [Original](http://127.0.0.1:8771/before/restricted-390-light-viewport.png) | [Integrated](http://127.0.0.1:8771/after/restricted-390-light-viewport.png) |

Additional actual-Django captures: [welcome modal](http://127.0.0.1:8771/after/interactions/welcome-1440-light.png),
[guide on phone](http://127.0.0.1:8771/after/interactions/guide-390-dark.png),
[320px](http://127.0.0.1:8771/after/interactions/reflow-320-dark.png),
[no JavaScript](http://127.0.0.1:8771/after/interactions/no-js-390.png),
[DST and mixed currency](http://127.0.0.1:8771/after/time-currency/dst-eur-usd-1440-light.png),
[RTL](http://127.0.0.1:8771/after/time-currency/rtl-390-dark.png).

Raw browser results: [baseline](http://127.0.0.1:8771/before/results.json),
[final matrix](http://127.0.0.1:8771/after/results.json),
[interactions](http://127.0.0.1:8771/after/interactions/results.json),
[font/time/currency](http://127.0.0.1:8771/after/time-currency/results.json).

The static gallery's selectors/images were also checked in Chromium. After all
test runners finished, the cluster was rechecked: the same identifier/directory,
empty public schema and only its three original base databases remain.

The gallery is read-only evidence from actual Django test responses. It does not
submit forms or connect to an ordinary database. Browser fixtures are destroyed
when the runner exits; an interactive authenticated app is not left running.
Only the loopback static evidence server remains. To restart it if needed:

```sh
.venv/bin/python -m http.server 8771 --bind 127.0.0.1 \
  --directory /tmp/motionmate-step7-rg6s8g_0/evidence
```

The original run used an ephemeral runner tied to that historical cluster.
Current reproduction does not depend on it. After disposable-runtime permission,
capture commit `34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c`, create a fresh pair and
follow [the portable validation commands](REPRODUCIBILITY.md#validation):

```sh
.venv/bin/python -B scripts/motionmate_preview.py check-dashboard --session SESSION_PATH
.venv/bin/python -B scripts/motionmate_preview.py check-dashboard --session SESSION_PATH --browser
```

These focused commands verify the owned cluster before creating a disposable
Django test database and apply email/cache/provider/network isolation. They
cover the retained dashboard contracts and browser/axe comparison, not the
entire historical 267-test selection or its baseline failures. Preserve earlier
evidence and use a fresh pair for another comparison. Never point checks at an
ordinary database. No validation was run during the Phase 2 documentation update.

## Limitations and remaining review decisions

- The user approved this composition and Step 8's real interactive previews.
  No next-screen implementation or release is authorized by those approvals.
- Existing Phoenix navigation/quota CTA contrast findings remain outside the
  new working region; full-page WCAG conformance is not claimed. Browser axe
  incompletes are evidence requiring interpretation, not automatic passes.
- The dashboard's existing request queue has no separate request-module guard.
  The unified destination does. This pre-existing policy discrepancy is retained
  and needs separate functional authorization if it is to change.
- Other Services mobile search triggers retain the known defect. Global search,
  shared-shell redesign and global Phoenix accessibility repairs are separate.
- Chromium and synthetic local billing bypass do not establish Safari/Firefox,
  assistive-technology, live-provider or ordinary-runtime/database behavior.
  Clipboard tests simulate API outcomes, not the operating-system clipboard.
  RTL evidence covers layout direction with Latin synthetic content; Manrope's
  Latin font is not a claim of full language coverage.
- Static validation post-processes only the new assets in a temporary directory.
  A full production manifest/WhiteNoise serving, deployment/cache invalidation,
  PWA offline/fresh-cached navigation and release-hook checks remain for a
  separately authorized release environment. Service workers were blocked in
  browser checks. No production `collectstatic` or build/release hook ran.
- Historical `/tmp` evidence and backups are ephemeral. The
  [preservation archive](PRESERVATION.md) now retains complete galleries and
  selected sanitized runtime evidence; the original runtime is recoverable
  from the verified Git commit without those backups.

## Rollback and stopping boundary

No database rollback is required: there are no schema or ordinary-data changes.
For a separately authorized source rollback, compare **only the four existing
manifest files** with verified baseline commit
`34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c`, checking for newer user edits first.
Remove only the eight Step 7 additions listed above. Do not reset/clean the
repository or remove existing `AGENTS.md`, skill/reference, design docs or lab
files. Re-run the focused comparison in a verified disposable environment.

For a future released rollback, restore the matching prior application/static
artifact together and follow the approved deployment/cache process; no such
deployment is authorized here.

The original task stopped for human review; local approval was subsequently
given. No commit, push, deployment, ordinary-database migration,
provider configuration change or continuation to another screen occurred.
