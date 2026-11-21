# Services Data Import — design direction v1

19 November 2026 · Full Redesign · SERVICE · **Gate A pending**

Primary route: `/crm/staff/data-import/` (`data_import`).
Outcome: clarify import choice, CSV preparation, server review, confirmation and
results without changing import behavior.

## Authorization and independent ownership

The current user requested three independent workstreams and said:
“Use Workflow v2: audit and design planning first, then one real Django
BEFORE/AFTER review after implementation.” and “Stop at Gate A for
design-direction approval for each module.”

This task owns the proposed hub, Lead CSV screens, Service/Category CSV screens
and import history. **Existing redesigned Services Client Import is preserved**:
upload/preview/result/unavailable includes, base and CSS/JS are reference and
regression targets, with no v1 changes. Hub links continue to that real journey.
Catalogue retains import/download links but does not own CSV screens. Approvals
and implementation are independent; each module works with the others unchanged.

Authorized work is offline source audit and saved planning/state only. No
application edits, runtime setup, database access/writes, migrations, installs,
providers, staging, commits, pushes or deployment. Gate A covers direction only;
the closed integration manifest follows after A.

## Actual Django audit — source evidence

| Journey | Current routes and source |
| --- | --- |
| Hub | GET `/crm/staff/data-import/`; `crm/views.py:2179–2208`, `importing/data_import.html`; capability/role flags, CRM write gate. |
| Clients | GET/POST `/crm/staff/data-import/clients/`; GET `template/`; GET `<uuid>/preview/`; POST `<uuid>/execute/`; GET `<uuid>/result/`. `crm/views.py:2270–2430`; shared entries explicitly include accepted `crm/services/clients/import_*.html` for SERVICE. |
| Leads | Corresponding routes under `/crm/staff/data-import/leads/`; `crm/views.py:2433–2615`, `importing/lead_*.html`. Historical leads/requests remain Lead rows; no client/appointment/invoice/outreach side effect. |
| Services & Categories | GET/POST `/crm/settings/services/import/`; GET `<uuid>/preview/`; POST `<uuid>/execute/`; GET `<uuid>/result/`; GET `/crm/settings/services/sample.csv`. `crm/views.py:2033–2177,2618–2634`, `settings/business_service_import.html`, `importing/service_*.html`. |
| History | GET `/crm/staff/data-import/history/`, 50 jobs per page via `page`; GET `<uuid>/` details for completed/failed/expired only. `crm/views.py:2211–2268`, `importing/history.html`, `history_detail.html`. |

Source chain: `src/taskio/urls.py:146` → `src/apps/crm/urls.py` → current Business,
role/module guards → existing handlers → `Client`, `Lead`, `BusinessService`,
`ServiceCategory`, `ImportJob` → `src/apps/crm/importing/` parser/schema/validators,
preview store and execution services → real templates and Phoenix shell.

### Preserved contracts

- **Upload → Validate → Preview → Confirm → Result** remains the exact process.
  Validate is existing upload POST/server work; Confirm is the existing preview
  section. Five labels do not add five routes or a client-side wizard. Preserve
  methods, UUIDs, CSRF, multipart encoding, `csv_file`, `id_csv_file`, help IDs,
  sample text hook `sample-csv-text`, download endpoints and return navigation.
- Upload creates ImportJob metadata/stored preview before confirmation. Domain
  records change only on execute. Existing “nothing is saved” copy is too broad;
  proposed wording is “No clients/leads/services are created or updated until you
  confirm.” Storage/retention policy is unchanged.
- Binding includes job, Business, actor, schema, file digest and expiry
  (`importing/preview.py:45`, `jobs.py:39`). Preserve status/lock-based retry
  protection, ready checks, expiry and 410 unavailable screens. No browser-edited
  rows, replacement payload or new hidden retry mechanism.
- Execution (`client_execution.py:173`, `lead_execution.py:244`,
  `service_execution.py:329`) locks/rechecks permission, ownership and relevant
  quota/matches/category state; domain writes are atomic. Completed retries
  return existing results. Keep failure codes, counts and destinations.
- All fields remain optional. Validate supplied values; skip empty rows. Current
  parser limits: 2 MiB, 500 rows, 50 columns, 10,000 characters/cell
  (`constants.py`). Render provided UX limits; no extra browser policy. Tenant/
  ownership columns remain forbidden input.
- Clients: keep duplicate/review/error classification, active-client capacity,
  statuses and consent. Leads: preserve private historical-import semantics,
  INTEREST/NEW/false-consent defaults, duplicates and existing category matching.
- Services: preserve localized decimals/tax; `external_code` match updates,
  otherwise creates; new categories/services commit together. Missing name/price
  creates inactive/non-bookable defaults; omitted columns and blank name/price
  on matches retain current values. Show all changes/notes/category counts.
- Confirm only when `job.status == 'ready'` and `preview.ready`. Preserve
  type-specific keys (`new_count`, `ready_count`, `create_count`, `update_count`),
  statuses, issues, messages and result codes. No force/ignore-error import,
  auto-confirm, rollback, new resume action or new import type.
- Clients: OWNER/ADMIN/STAFF/ACCOUNTANT and CRM gate. Leads: OWNER/ADMIN/STAFF
  and service_requests gate. Services: OWNER/ADMIN and services gate. Hub uses
  CLIENT_MANAGE_ROLES/CRM write plus capability/role flags. Keep existing
  differences between hub visibility and direct-route access; no new evaluator.
- History: OWNER/ADMIN, CRM read, current Business; metadata/counts only, no
  uploaded rows/preview JSON/file digest. Actor-bound preview access stays
  distinct from tenant-wide sanitized history. Preserve 50-job pagination.

## Findings and proposed composition

All findings are from source inspection; no rendered/browser result is claimed.

| Current source pattern | Proposed design | Benefit |
| --- | --- | --- |
| Hub uses four equal cards and preparation-focused steps; Clients is redesigned while other types/history use older presentation. | Three guarded task rows: **Clients**, **Services & Categories**, **Leads**, with existing import/template links. Move guarded **Import history** to the header. Five-stage process plus quiet optional preparation note. | Clear choice; template download stays optional. |
| Lead/service upload splits repeated explanations across large cards. | Main upload panel plus **Start with what you have** aside, persistent optional-field/UTF-8 guidance; service headers/examples/copyable CSV in accessible native disclosures. | Upload is prominent; details remain available. |
| Preview has many count cards and wide row tables. | Compact supplied summary, ready/blocked status and blocking issues first; one row-results surface with full changes/notes/issues; confirmation after reviewed rows. | Clear decision with complete evidence. |
| Result/history uses nested cards, small text and many columns. | One outcome panel with real counts/next steps; metadata-first history table and labeled mobile records. | Clearer recovery/audit review without new data exposure. |

Layout proposal only:

```text
Data Import                                      [Import history — existing guard]
Upload → Validate → Preview → Confirm → Result
Clients                   [Import Clients]                  [Template]
Services & Categories     [Upload categories and services]   [Template]
Leads                     [Import Leads]                    [Template]
All fields optional · Exact template headers · Review before confirming

Preview: filename / workspace / Ready or Import blocked
File issues → type-specific summary → row results + changes + issues
Confirm this import: server readiness/counts → existing POST or blocked notice
```

Each task row retains its existing capability condition. Preview rows remain
read-only. Warning/Review/Error/duplicate/create/update meanings stay distinct.
Confirmation follows evidence with exact counts and **Upload a revised CSV**;
no sticky overlay, inline row editing or automatic retry.

## Motionmate styling, mobile and accessibility

Use the approved [design system](../../../motionmate-design-system/DESIGN.md),
[components](../../../motionmate-design-system/COMPONENTS.md) and
[vertical rules](../../../motionmate-design-system/VERTICALS.md): existing local
Manrope/OFL, indigo actions, calm surfaces/navy dark theme, 4px spacing, 12px panels,
8px controls. Existing Services Client Import is the composition reference;
do not edit or clone its entire module to create domain rules.

Keep Phoenix 1.23.0, shell/navigation/themes and Bootstrap breakpoints. Use
scoped Django includes/styles; no Tailwind/DaisyUI production imports, dependency,
global asset change or framework migration. Read-only Phoenix wizard examples
inform labels only; do not instantiate a replacement client-side wizard.

- Desktop: upload and guidance aside; preview uses full width. Tablet: guidance
  follows upload as needed. Mobile: one column, 44px controls and labeled row
  records retaining all changes/issues/full filenames in DOM order. Use one
  dataset and preserve table relationships. Wide sample CSV uses a labeled local
  scroll region with copyable text alternative; no horizontal document scroll.
- One h1, ordered progress list with actual `aria-current='step'`, persistent
  labels, associated errors and focus. Native example disclosures preserve text
  selection. Theme changes retain file/form context and disclosure state.
- Preserve ready/blocked, missing file, malformed CSV, no rows, partial optional
  data, expired/stale preview, completed retry, atomic failure, empty history and
  restricted outcomes/recovery. No fabricated async progress or estimated time.
- Check light/dark, reduced motion, long content and scoped RTL. Do not change
  shared theme preference keys or make denied screens appear as empty datasets.

## Shared impact and protected work

Hub/Leads/Services/History participate in shared routes. Integration must select
Services content explicitly while retaining Logistics fallback, methods, guards
and asset order. Client Import's Services branch, base, CSS/JS and completed
workflow evidence remain protected. No shared status/issue include edits are
proposed. Catalogue forms, subscription/billing and all Logistics redesign are
outside this workstream. Shared entry templates require both-vertical regressions.

Initial branch: `experiment/motionmate-ui-redesign`; HEAD
`6d65bc4d5e80f772e1822572f8ee20b4686fd7da`. Initial tree was clean. The two other
new workstreams are independently owned. Preserve Clients/Invoices records and
ignored references. `source-audit.json` is inspected-source hashes, not frozen
Django BEFORE or Gate B target baseline.

## Validation boundary and deferred decisions

`validation.md` plans isolated PostgreSQL synthetic import fixtures, actual
POST/CSRF/retry/atomicity/tenant checks, responsive themes/accessibility, preserved
Client Import and Logistics regressions. Resources and any screen-specific
adapter belong in B's concrete manifest. No Django initialization, database or
browser access, migration, fixture, provider call, capture or runtime test ran.
After B, freeze actual working-tree BEFORE, implement and present one real
Django BEFORE/AFTER review for this workstream; no standalone prototype.

Defer schema/default/limit changes, duplicates/capacity policy, retention,
ownership, permissions, editable previews, new formats, upload automation and
domain side effects. Historical docs describing unfinished imports do not
override current source: Client, Lead and Service execution routes exist.
Availability still follows actual capability/role/module/subscription guards.

## Gate A decision

Approve **Services Data Import v1**: task-choice hub, consistent existing
five-stage journey, read-only review surface, grouped type-specific guidance,
result/history composition and preservation of current Client Import. Approval
covers only this module's design, excluding functional decisions. Exact artifact
hashes/scope-bound identity are in `state.json` and offline check output.
Approvals remain null. After A, prepare exact integration/impact/baseline/resources
and stop at B. A never authorizes application changes.
