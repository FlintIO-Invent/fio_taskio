# Services Registration & Onboarding — prospective validation

Full Redesign · SERVICE · v1 · planning only, Gate A pending

This document is a validation plan, not passing implementation evidence.
No runtime, database, browser, provider or data-writing test ran. Current offline
results are recorded separately in [offline-checks.json](offline-checks.json).
Do not replace this hash-bound design artifact with later results; add a separate
validation report after Gate B.

## Authorization and resources to specify after Gate A

The Gate B proposal must identify exact settings, isolated fixture/check/adapter
source, private temporary output roots, available HTTP/PostgreSQL ports and
expected ownership proofs before any setup. Runtime authorization is absent.
Do not reuse another workstream's resource approval, database, cookies or records.

Use independently owned disposable PostgreSQL only, with live host/port/database,
cluster data-directory/system-identifier and process-owner/start-identity checks.
Existing migrations may run only in fresh empty owned databases with explicit
authorization. No migration source changes, ordinary `.env`, customer-data copy,
uploads, ordinary local/staging/production/Test Lab DB, external mail, workers or
provider access. Keep secrets/tokens/session material out of repository evidence.

The existing `scripts/ui_preview/settings.py` disables Stripe/free-test;
`guard.py` blocks `/billing/`, subscription writes and external redirects. A
dashboard `--route` change is not a registration validator. Before Gate B resolve
a dedicated isolated adapter for the actual signup/return routes and real POSTs
without weakening shared financial/network guards. Specify every adapter/test
file in the closed manifest. Its permitted writes must be bounded to authorized
synthetic owned records, with negative tests proving ordinary DB/external network/
schema/financial operations remain denied. This is a validation requirement,
not consent to edit existing guards or establish new runtime policy now.

For Stripe branches use isolated backend tests with explicit service/SDK doubles;
keep server dimensions, price validation, metadata, idempotency and access-state
assertions. A provider double does not establish hosted Checkout operation.
The interactive pair must show actual Django forms/auth/navigation/welcome and
fixture-backed server return states; label provider handoff unavailable there.
Do not fabricate a hosted Checkout interface or imply end-to-end payment proof.
If a safe adapter is not concretely achievable, expose the gap at Gate B and
keep dependent browser validation pending.

## Required checks after authorized implementation

| Area | Cases and preserved assertions |
| --- | --- |
| Public pricing | Active Starter/Pro/Business rows; inactive/no plans; recommendations; dynamic counts including finite/unlimited clients/users; supplied prices/currency; monthly/yearly display and CTA URLs; USD/EUR navigation/session behavior. No invented discount or allowance; public page outside pricing unchanged. |
| Standard form GET | Direct default/fallback, each plan/interval/currency link, invalid queries and session fallback; no tenant/user/subscription creation on viewing. |
| Standard form invalid POST | Missing fields; duplicate owner email; invalid business email; mismatch/weak passwords; invalid/inactive/missing plan; unsupported interval/currency; Europe/EUR and International/USD mismatch. No new user/Business/membership/subscription on rejected submissions. |
| Form recovery | One unchanged form payload and CSRF; field/non-field/selection errors visible and associated; error summary/focus; retain non-secret bound values; password re-entry; plan/currency editor accessible and location correction visible. In-place changes preserve all draft inputs and query routing. JS-disabled selection remains usable. |
| Valid standard local signup | Real atomic user/Business/OWNER membership/legacy profile writes and local trial, login, current Business, dashboard. Existing slug uniqueness and selected-plan entitlements. Do not infer persisted interval/currency from a local trial. |
| Stripe signup, isolated doubles | Pending subscription with exact server-selected dimensions; no access before reconciliation; rejected/tampered price data; unavailable/missing configuration and provider failure keep account/workspace for recovery. Service doubles only; no actual provider traffic. |
| Private Services access | Enabled/disabled/wrong/rotated/missing tokens; eligible/inactive tiers; forged plan; reusable links; selected Beta ACTIVE/BETA without trial/Stripe; free-test fixed plan ACTIVE/LOCAL/FREE_TEST without expiry/card. Preserve Beta route's existing public options/default. Flag/token changes must not modify existing records. |
| Checkout return | Owner-only/Business scoped; anonymous/other roles/inactive Business; direct success URL and arbitrary `session_id` cannot activate access. Pending/trialing/active/attention/no-subscription/cancelled states. Existing resume precedence, exact POST/CSRF, 405 on GET; saved workspace, existing session ownership/reuse/expiry/completion and failures in isolated service tests. |
| Welcome | Fresh owner/admin modal auto-show; all three existing journeys; select/dismiss POST; explicit reopen; returning/dismissed users not reset. No automatic journey selection or creation of operational records. |
| Guide | Start/Back/Next/Skip/Finish/Continue later/close and journey switch; exact hidden keys and `setup_guide=1`; current step/last step persistence; actual completion vs position vs skip; locked modules; prerequisite effective CTA/target; completed/missing/stale journey state. |
| Roles/isolation | Owner/admin visibility; Staff/Accountant/Viewer do not gain setup guide or actions; read-only workspace POST denial; current Business resolution/legacy membership fallback; cross-Business identifiers/step keys cannot expand access. Shared setup-without-membership fallback and auth routes unchanged. |
| Logistics regressions | Shared free-test entry for Core/Growth/Scale and guards/vertical/profile; enrollment untouched; annual pending/active/attention/cancelled returns and resume delegation; Logistics dashboard/journeys/status/location restrictions preserved. Negative assertions that Services includes/assets do not render. |
| Prior Services redesigns | Dashboard outside onboarding, Catalogue, Clients, Appointments, Invoices, Imports, Subscription and Team/Settings retained source/behavior; existing setup CTAs reach current screens without duplication or altered guards. |

Reuse relevant existing behavioral coverage in `apps.accounts.tests`,
`apps.businesses.tests`, `apps.crm.tests`,
`apps.accounts.test_logistics_free_test_registration` and affected Logistics
checkout/enrollment suites. Select exact tests after the manifest exists; preserve
behavioral assertions while explicitly updating approved copy expectations.
No full suite or markup-only tests by default. No tests against unknown settings.

## Browser, accessibility and difficult states

Cover 390/768/1440px light/dark on real Django pages; targeted 320px reflow,
RTL, zoom and reduced motion. Include long company/email/country/plan/price/error
text, no plans, missing selection, bound validation failures, private access,
pending/failed confirmation, no subscription, completed/missing/locked setup
tasks and read-only/denied states. No invented async loading state or polling.

Verify pricing display and link agreement, in-place draft-preserving selection,
actual form POST/CSRF/login/redirects, keyboard radios/disclosure, field help/error
association and error focus, names/headings/landmarks, contrast/focus/touch targets,
document overflow, modal/offcanvas keyboard containment, explicit close, return
focus, mobile scrolling and existing static dismissal exception. Preserve desktop
spotlight and missing-target fallback, with mobile spotlight remaining disabled.
Theme switches must retain unsaved inputs; use existing Phoenix/Silicon preferences.

Retain raw axe violations/incompletes and baseline failures. Report measured
contrast separately from source review. Capture a small representative set:
desktop registration, mobile validation/selection, yearly EUR pricing, checkout
pending/recovery and welcome/guide; summarize other cases without duplicating a
screenshot matrix. Keep logs/browser output outside Git in owned resources.

## One real Django BEFORE/AFTER pair and Gate C

After Gate B and immediately before application edits, recheck branch/status,
approved file hashes and unrelated work, then freeze actual working-tree bytes.
Create one independent BEFORE/AFTER pair with matching initial synthetic fixtures,
separate cookies and verified identities. Include representative local/private
accounts and subscription/onboarding states without customer data. Preserve
BEFORE; refresh AFTER alone. Never silently reset/reseed later review writes.

Report actual URLs, source/candidate/initial-fixture hashes, environment/settings/
DB ownership identity, exact performed checks, remaining guard/provider limits
and representative evidence. A missing real comparison keeps Gate C pending.
No source-only/prototype pass can replace it. No actual pair or candidate exists
at Gate A.

After explicit Gate C acceptance, prepare the exact classified commit selection
as workflow documentation; one commit per redesign is recommended. Staging,
commit, push, merge, deployment and cleanup still require separate authorization.
