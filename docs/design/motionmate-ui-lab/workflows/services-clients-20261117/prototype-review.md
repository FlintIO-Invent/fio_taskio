# Services Clients — Gate A design v1

Full Redesign · SERVICE · 17 November 2026. Approved Motionmate design-system
references, local Manrope, Tailwind 4/DaisyUI 5 in an isolated HTML document.
Phoenix 1.23.0 and all application records/logic remain unchanged.

## Review links

- Directory: http://127.0.0.1:8766/services-clients/dist/
- Profile: http://127.0.0.1:8766/services-clients/dist/?screen=profile
- Create: http://127.0.0.1:8766/services-clients/dist/?screen=create
- Edit: http://127.0.0.1:8766/services-clients/dist/?screen=edit
- CSV journey: http://127.0.0.1:8766/services-clients/dist/?screen=upload
- Inline draft: http://127.0.0.1:8766/services-clients/dist/?screen=draft
- Empty history: http://127.0.0.1:8766/services-clients/dist/?screen=profile&scenario=no-history
- Gallery: http://127.0.0.1:8766/services-clients/evidence/v1/gallery.html

The review disclosure supplies screen/scenario selection outside the product
frame. All writes are page-memory simulations, cleared on reload. Selected CSV
files are not parsed: the review uses supplied ready/blocked server-preview
projections. Appointment/request/billing destinations expose their audited named
routes without sending application requests. Scheduling examples explicitly use
America/Lower_Princes; the fixed review date is 17 November 2026.

## Design and preserved contracts

- Directory keeps search, district, record-activity filter, true/false/1/0 aliases,
  six sort subjects, 10-row pagination, View all/less and selection. A visible
  sorting/selection toolbar avoids clipped mobile focus controls. No bulk write.
- One client identity replaces duplicated company columns. Contact and record
  actions stay visible; mobile records retain identity, company, email, phone,
  locality, activity and actions. Long/partial imported records have honest labels.
- Profile exposes identity/contact/address first, relationship context alongside,
  all optional business/contact details, notes, and distinct appointment/invoice
  sections with existing module/role projections. Classification and activity
  remain distinct. Financial labels are supplied, never calculated from status.
- Full-page create/edit keep all 32 PrivateClientForm fields, required values,
  six named sections, country-sensitive create address, form errors and current
  return routes. Mobile Notes & Consent remain reachable. No new active checkbox.
- Archive confirmation names the client, explains inactive state, preserves
  invoice/appointment records and retains the existing classification effect.
- CSV retains Upload → Validate → Preview → Confirm → Result, optional columns,
  duplicate skipping, blocked review/error states and explicit confirmation.
  Inline creation retains six new_client-* fields and the parent draft/focus.

## Validation

| Width | Light | Dark | Long/reflow/targets | Evidence |
| --- | --- | --- | --- | --- |
| 1440×900 | Pass | Pass | Pass | run-02, final-delta, supplement-01 |
| 768×1024 | Pass | Pass | Pass | run-02, final-delta, supplement-01 |
| 390×844 | Pass | Pass | Pass | run-02, final-delta, supplement-01 |
| 320×844 | Pass | Pass | Pass | run-02, final-delta, supplement-01 |

256 matrix cases pass; all eight journeys pass with 316 assertions. Eight
supplemental cases pass with 126 assertions: every form field expanded/labeled,
partial profile, native dialog keyboard wrapping and return focus, visible focus,
normal/reduced motion, inline quota rejection and preserved draft, mobile drawer
navigation/scroll. Final build adds no-history; 72 final cases pass. Of 128
screenshot comparisons, 125 are exact. Three inspected full-page pairs differ only
by 1/255 channel rounding on 196 pixels total; identical dimensions, no content or
layout change. The strict parity failure remains retained, with reviewed
resolution in evidence/v1/pixel-review.json.

Tested scenarios: populated, long, partial, empty, admin, staff, accountant,
viewer, read-only, locked, no-invoices, no-appointments, no-history, quota,
loading, error, invalid, import-blocked, invoice-review. These are synthetic
projections; they do not prove server authorization. No-invoices/no-appointments
omit unavailable sections; no-history shows honest empty sections within access.

Full-page axe WCAG A/AA tagged checks report zero violations and zero incompletes
in the matrix, journey end states and expanded/dialog supplemental states.
Rendered checks cover overflow, text sizes, 44px targets, font/theme, required
labels and semantic text/control/hover/focus/error contrast. Passing final runs
report zero browser errors, failed requests or external/non-GET requests.
Browser: explicitly selected existing Chromium 148.0.7778.96. No tooling installed.
Final task-only rebuild matches all 11 built assets exactly.

12,619 protected files remain byte-identical, including production/Logistics,
shared tokens/components, dashboard and Appointments sources/builds. Registry
changes add only Clients; existing entries retain their original values and
formatting. See preservation-after.json. Sources, built assets, reports and
review evidence are SHA-256 bound in design-identity.json and workflow state.

## Retained findings and limitations

See validation.md and raw initial/run-01 evidence: default browser binary missing,
CSP-blocked initial inline axe injection, shorthand-color parser, clipped mobile
sort controls and ambiguous test selector. All fixes remain task-local. The
strict final screenshot rounding finding is recorded separately, not hidden.

No actual Django BEFORE/AFTER, database tests or provider verification were run.
The ordinary running application was not accessed. Actual server forms, CSRF,
quota locks, tenant/role enforcement, financial presentation and Logistics browser
regressions belong to a separately authorized implementation review. No claim
of ordinary-runtime stability or complete WCAG conformance is made. Firefox,
Safari, assistive technology, RTL and native zoom were not tested.

The repository-wide workflow checker reports an existing Step 7 manifest mismatch
for src/apps/crm/tests.py. Its bytes match HEAD and this task’s intake baseline;
no source or historical manifest was changed to silence it. Focused Ruff and
diff checks pass. This does not affect the isolated Clients browser results.

## Gate A — awaiting explicit design approval

Review v1's visual layout and simulated interactions, bound to the artifact hash
in design-identity.json/state.json. Deferred: manual Individual company requirement
is preserved; Export stays an honest handoff; no merge/restore/activity writer,
new finance/role policy, schema or data changes. Design approval does not
implement anything or grant release permission. Integration and Gate B remain
unstarted. No approval has been recorded on the user's behalf.

Static preview remains available on loopback port 8766, task-started PID 2899549
(exec session 20257), serving ui-lab with GET-only handler. No other preview
process was changed or stopped. Rebuild/start instructions: ui-lab/services-clients/README.md.
