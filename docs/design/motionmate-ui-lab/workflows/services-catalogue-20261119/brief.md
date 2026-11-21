# Services Catalogue — design direction v1

19 November 2026 · Full Redesign · SERVICE · **Gate A pending**

Primary route: `/crm/settings/services/` (`business_service_list`).
Outcome: make pricing, availability and category maintenance easier to scan and
edit, preserving every current form and operational contract.

## Authorization and independent ownership

The current user requested three independent workstreams and said:
“Use Workflow v2: audit and design planning first, then one real Django
BEFORE/AFTER review after implementation.” and “Stop at Gate A for
design-direction approval for each module.”

This task owns the proposed catalogue list, service create/edit and category
create/edit presentation. **Data Import owns the complete service CSV journey**,
including the uploader reached from this catalogue. Catalogue retains the current
import and sample CSV links. Each workstream can be approved and implemented
independently; no approval transfers between them.

Authorized work here is offline source audit and saved planning/state only.
Application edits, runtime setup, data changes, migrations, installs, providers,
staging, commits, pushes and deployment are excluded. Gate A is design direction;
the exact integration manifest and resources follow only after A.

## Actual Django audit — source evidence

| Surface | Existing route / handler / contract |
| --- | --- |
| Catalogue | GET `/crm/settings/services/`; `crm/views.py:1875` supplies tenant-scoped services/categories including archived records, counts and booking entitlement. No current server search, filters or pagination. |
| Categories | GET `/crm/settings/service-categories/` redirects to the combined catalogue. The older `service_category_list.html` is not the active list. Preserve the redirect. |
| Service editor | GET/POST `/crm/settings/services/create/` and `/<int:service_id>/edit/`; `BusinessServiceForm`, current Business, same list return. Create supports `?category=ID` preselection after tenant/active checks. |
| Category editor | GET/POST `/crm/settings/service-categories/create/` and `/<int:category_id>/edit/`; `ServiceCategoryForm`, same list return. |
| Archive | POST-only service/category `/<id>/archive/`, CSRF, existing active check/messages; soft archive retains references. No new delete or restore operation. |
| Import/download | Keep `business_service_import` and `business_service_sample_csv`; the CSV screens belong to Data Import. |

Source chain: `src/taskio/urls.py:146` → `src/apps/crm/urls.py` →
`business_role_required` / `business_module_required` in
`src/apps/businesses/utils.py:224,931` →
`src/apps/crm/views.py:190–202,1740–2030` →
`src/apps/crm/forms.py:1129–1430` and `models.py:135–315` →
`src/templates/crm/settings/business_service_list.html`,
`business_service_form.html`, `service_category_form.html` → Phoenix shell.

- Catalogue/category access is OWNER/ADMIN (`SERVICE_MANAGEMENT_ROLES`). Lists
  require services **read** access; editors/archive require services **write**
  access. Preserve `workspace_can_modify` blocks and authoritative server checks.
- Preserve category `name`, `code`, `is_active`; service `name`, `category`,
  `new_category_name`, `external_code`, `description`, `unit_price`, `tax_rate`,
  `is_active`, `is_bookable_online`, `default_duration_minutes`,
  `booking_buffer_minutes`, `public_description`, `requires_manual_confirmation`.
  Keep field IDs, CSRF, non-field/field errors, submitted values and cancel URLs.
- Existing-category choice and inline new-category name are mutually exclusive;
  category plus service saves are atomic. No redirect that discards the service
  draft, autosave, replacement record or new modal workflow.
- Decimal parsing, `money` formatting, currency/locale and tax defaults remain
  authoritative. Blank tax on edit retains existing tax; new-service tax uses
  the Business default. External codes remain tenant-scoped matching identifiers.
- `ServiceCategory.business` stays nullable. Lists remain business-scoped; form
  selection retains existing instance compatibility (`forms.py:30`). No global
  exposure of historical null-business categories, copying, backfill or migration.
- Services feed invoices (`billings/views.py:82,213`), appointments
  (`appointments/forms.py:110`), public booking (`crm/forms.py:53`) and Logistics
  charge choices (`logistics/billing_forms.py:48`). Preserve those consumers,
  stored values, booking policy and existing records.

## Findings and proposed composition

These are source findings, not observations from a running browser.

| Current source pattern | Proposed direction | Benefit |
| --- | --- | --- |
| Five competing header actions, four large count cards and booking notice precede records. | One h1 **Services Catalogue**; primary **Create service**; secondary **Upload categories and services**. Keep **Create category**, **Sample CSV**, guarded **Back to settings** as visible quiet links. Compact labeled existing-count summary. | Clear main task; records closer to the title. |
| Two tables use small actions and horizontal scroll wrappers. | Titled **Services** then **Categories**, with in-page anchor links; preserve all columns, visually group related values and use labeled mobile records. | Easier navigation without new filters, tabs or hidden records. |
| Service editor mixes identity, pricing and booking fields beside a large scope sidebar. | One existing form grouped into **Service details**, **Pricing & tax**, **Online booking**, **Availability**. Quiet scope/tax guidance aside. | Clear field relationships with unchanged validation/submission. |
| Category actions are only beside the title. | Compact name/code/status editor, inline code/reference guidance, one save/cancel group after fields. | Easier keyboard and mobile completion. |

Desktop layout proposal only:

```text
Services Catalogue                 [Upload categories and services] [Create service]
Create category · Sample CSV · Back to settings (existing guard)
Active services / Archived services / Bookable online / Active categories
Existing booking-plan notice
Services ↓     Categories ↓
Services: identity + code | category | price + tax | booking | status | updated | actions
Categories: name | code | linked service count | status | actions
```

Keep full names, code, price, tax, booking flag/duration, active/archive status,
update date, category code/count and existing Edit/Archive actions. Booking flag,
activation and plan entitlement remain distinct facts; no inferred “Live” badge.
Category archiving never implies service deletion.

## Motionmate styling and interaction

Use the approved [design system](../../../motionmate-design-system/DESIGN.md),
[components](../../../motionmate-design-system/COMPONENTS.md) and
[vertical boundaries](../../../motionmate-design-system/VERTICALS.md): existing
local Manrope/OFL, restrained indigo, calm light/navy dark surfaces, 4px spacing
scale, 12px panels, 8px controls, 1px dividers and textual statuses. Reduce
ornamental shadows and uppercase micro-labels. Preserve the mark and Phoenix
shell, navigation, theme controls, Bootstrap breakpoints and vendor order.

Use Django includes and Phoenix/Bootstrap with module-scoped presentation.
Tailwind/DaisyUI remain optional lab references, never production imports.
Existing local Manrope WOFF2/OFL can be reused within this module after B, with
fallback/glyph coverage checked; no global typography change or dependency.
Phoenix 1.23.0 reference is present and read-only; table/form examples inform
composition, not domain behavior.

- Desktop: records are primary; explanations secondary. Tablet: deliberate
  action wrapping and two-column fields only where readable. Mobile: single
  column, labeled records retaining every field, equal/full-width action groups,
  44px targets and full names/codes/prices wrapping without page overflow.
- No new search, sorting, pagination, bulk actions, inline edit, auto-submit,
  client-side tabs, archive confirmation or invented asynchronous loading.
  In-page links navigate the two existing sections.
- One h1, ordered headings, real table headers/row identity, persistent labels,
  associated errors and visible focus. Theme changes preserve drafts/focus;
  support reduced motion and scoped RTL without shared theme changes.
- Empty services/categories retain only existing permitted next actions. Read-only
  content retains records and existing mutation guards. No invented counts,
  unauthorized data or hidden validation messages.

## Shared impact, evidence and deferred decisions

The three current templates serve both verticals. Integration must explicitly
select Services content and preserve Logistics fallback/asset loading. No shared
shell, global CSS/JS, permission helper, model, route or downstream source change
is proposed. Both verticals require regression evidence at implementation review.

Initial branch: `experiment/motionmate-ui-redesign`; HEAD
`6d65bc4d5e80f772e1822572f8ee20b4686fd7da`. Worktree was clean before the three
new task directories. Preserve Clients/Invoices workflows and implementations,
frozen lab references and ignored Phoenix. `source-audit.json` records source
hashes; it is neither frozen Django BEFORE nor Gate B target baseline.

Known discrepancy: service form help refers to “future” public booking and
manual-only behavior while booking documentation describes additional paths.
Keep fields/behavior; defer claims needing that discrepancy resolved to a
separate source-verified decision. Do not restore obsolete architecture.

`validation.md` plans isolated Django/browser/accessibility/Logistics checks.
No Django initialization, database access, browser, fixture, capture, provider
call or runtime test occurred. After B, freeze the actual working-tree BEFORE,
implement scoped files, then present one real Django BEFORE/AFTER review for
this workstream. No standalone prototype is required.

## Gate A decision

Approve **Services Catalogue v1**: the two-section record workspace, compact
existing-count summary, prioritized actions and grouped existing edit forms,
subject to these preservation rules/exclusions. Functional decisions remain
deferred. Exact artifact SHA-256 and scope-bound design identity are recorded
in `state.json` and offline check output. Approval fields remain null until
explicit user consent. After A, prepare exact integration, impact, baseline and
validation resources; stop at B. A does not authorize implementation.
