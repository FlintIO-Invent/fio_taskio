# Catalogue validation plan — pending Gate B

No implementation or runtime validation has occurred. This is a proposed coverage
plan, not permission, a test log or a claim about the ordinary local application.

## Offline Gate A checks

Verify source references and hashes in source-audit.json, local documentation
links, schema-2 state and Gate A stop using the offline workflow helper. Check
whitespace and that only the three newly owned documentation directories changed.
No Django initialization or database/browser access is required for these checks.

## Future authorized environment

Gate B must name the exact owned disposable PostgreSQL BEFORE/AFTER clusters,
settings, sanitized database identity, owner, cluster directory/system identifier,
ports/processes, synthetic fixture setup and any separate test database. Verify
live ownership independently before writes. Existing migrations may run only in
empty disposable databases if explicitly authorized. No ordinary local, staging,
production or Test Lab database, copied records, .env, uploads or provider access.

Use actual working-tree bytes frozen immediately before application edits; do not
substitute HEAD or a historical dashboard. Preserve BEFORE, refresh AFTER only.
One real Django BEFORE/AFTER review belongs to this workstream after implementation,
with equal initial synthetic records, distinct cookies and recorded source/fixture
hashes. No prototype or screenshot can replace actual login/forms/navigation.
Existing dashboard validation is not a catalogue adapter. Any fixture/check source
needed for this module must be reviewed in the Gate B manifest first.

## Proposed functional coverage

| Case | Required evidence after implementation |
| --- | --- |
| List | Tenant-scoped service/category values and every field retained; active/archive states, booking flag versus entitlement, category counts, localized price/tax and update date. |
| Create/update | Actual GET/POST/CSRF, same route/field IDs/payload/return; category preselection; choose existing versus new category; same errors/submitted values; atomic category+service save. |
| Price/tax | Decimal-point/comma locales, zero price, invalid price/tax, blank tax defaults on create, blank retains tax on edit, duplicate external codes. No totals calculated in presentation. |
| Compatibility | Nullable/historical category records and retained instance selection; no global category exposure, record duplication or schema change. |
| Booking | Preserve all existing booking-field behaviors and supplied values; public booking entitlement notice; no policy change, inherited duration/buffer unchanged. |
| Archive | POST-only, CSRF, same idempotent active check/messages, soft archive and reference preservation for category/service. |
| Permissions | OWNER/ADMIN; STAFF/ACCOUNTANT/VIEWER rejection; read-only list where current read policy permits, denied writes, missing services module, tenant switching/direct foreign IDs denied. |
| Navigation | Settings/dashboard, service/category edit/create/cancel, import/sample CSV, category-list compatibility redirect and catalogue anchors retain destination/method. |
| Downstream | Existing invoice/appointment/public-booking service choices and saved references remain unchanged. |

Use existing tests as appropriate after inspecting their settings/side effects:
apps.crm.tests.CRMBusinessScopingTests, apps.crm.test_combined_service_import
as an import boundary regression, apps.businesses.test_capabilities and relevant
booking/invoice service-consumer tests. Select actual relevant cases at B; do not
run broad destructive-management suites or tests that merely mirror markup.

## Browser, accessibility and Logistics preservation

Exercise populated/empty/archive-only/uncategorized/long/error/restricted states
at 1440/768/390px, light/dark, plus 320px reflow and relevant RTL/zoom. Check
44px targets, text/controls/focus contrast, headings/labels/error association,
keyboard/save/cancel/return focus, draft retention through theme changes, table
semantics/labeled mobile records, wrapping and reduced motion. Retain axe failures
and incompletes; Chromium/axe does not certify full accessibility.

Because entry templates are shared, compare unchanged Logistics list/editor and
category presentation/assets under permitted owner/admin and denied staff states,
read/write/module restrictions and relevant location-scoped downstream charge
choices. No Logistics redesign or access grant. Include existing Clients/Invoices
surfaces as unchanged consumer samples if the final manifest touches their shared
assets; the proposed design avoids those assets entirely.

Record actual static, isolated backend, real Django/browser and manual evidence
separately. Save representative screenshots and failure evidence only; keep logs,
browser output and databases in owned external session storage. Runtime/provider
readiness and ordinary database migration status remain outside these checks.

## Gate C prerequisites

Present actual URLs, source/candidate/fixture/environment identities, equivalent
initial synthetic records, compact test results and every missing capability.
Do not mark Full Redesign complete while required Django/browser evidence is
missing. Human acceptance, commit preparation and release authorization follow
separate stages. No cleanup or release action is implied.

## Gate B preparation — 20 November 2026

Gate A is now approved; runtime implementation and resource consent remain pending.
The existing coverage plan above is retained. integration.md now specifies exact
source/adapter boundaries and validation-resources.json specifies the new owned
resources/actions proposed for B. No runtime check or fixture has run.

All three modules use separate source/fixture/session identities; test runs are
serialized through the existing guarded test boundary on 127.0.0.1:8768 and only
the selected module AFTER cluster's runner-owned test_services_rollout database.
Keep read-only review financial blocks intact. Real write/form checks happen in
the separate synthetic test DB/LiveServer; provider SDK responses are synthetic,
external browser transport is blocked and provider-hosted screens remain unverified.
No fake UI substitutes for actual forms, routes, login, CSRF or permissions.

Do not run the existing dashboard validator as proof of module coverage: the
new listed screen adapter owns its cases. Reuse existing ownership, source, live
DB-identity and network guards unchanged. Evidence must distinguish inspected
source, isolated backend tests, real browser behavior and live provider/runtime
checks. Missing required evidence keeps validation/Gate C pending.
