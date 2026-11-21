# Business Settings — Gate B integration proposal

Design: **v1**, Gate A approved by exact user reply “approved” following both
named Gate A links. See [approval record](gate-a-approval.json). Implementation
and resource approvals remain pending. Keep approved design artifacts immutable.

Routes `/businesses/settings/` and `/businesses/settings/booking/`;
root scope `.mm-services-settings`.

## Production integration

Both current entry templates keep the same Phoenix parent and add SERVICE-only
assets/content selection. Preserve original Logistics/non-Service/no-business
body and legacy Settings stylesheet. New Settings partials implement compact
workspace/actor identity, existing section anchors, the complete multipart
Business form, separate account-prefixed personal form, security link and exact
configuration gates. New Booking partials group existing rules and Single/Bulk
entry; availability becomes a full-width record list. No backend form split,
autosave, new endpoint, field omission or altered return behavior.

Keep `business-settings-form`, section anchors, account prefix, `section=business`
and `section=account`, `form_kind=settings|availability|bulk_availability`, CSRF,
Bootstrap tab/panel IDs, current selected-error panel, same unit/time formats and
POST-only deactivation. Currency/tax/numbering/logo remain one Business save.
No data is copied from `SaaSUserProfile` and no new preferences are invented.

The new Services share-panel partial retains the exact authoritative readiness
predicates and existing Copy/Open/Finish setup URL/handler behavior, using proper
heading levels and scoped composition. The original shared share include is
unchanged for other consumers. No new clipboard feedback or booking-state logic.
Invoice-logo upload, preview/fallback, replace/remove validation and atomicity
remain in existing services; clarify newly generated invoice scope only.

## Explicit narrow accessibility repair

The approved brief deferred duplicate availability IDs for a compatibility
proposal. This manifest proposes one pure template-rendering helper,
`businesses/templatetags/services_settings.py`, used only by new Services partials.
It renders existing BoundFields via Django escaping/widget APIs, adds associated
help/error IDs and allows a fixed DOM-only `bulk_` namespace for bulk controls.
It performs no query, save, permission evaluation or validation change.

On the new Services bulk form only, generated control IDs become
`id_bulk_staff_member`, `id_bulk_days` (with derived choice IDs),
`id_bulk_start_time`, `id_bulk_end_time`, `id_bulk_is_active` and corresponding
label/help/error targets. Single-form IDs remain unchanged. Input `name` values
remain `staff_member`, `days`, `start_time`, `end_time`, `is_active`; Django form
prefixes remain empty. Preserve all Bootstrap `availability-*` hooks. Shared
backend, original templates/Logistics and authentication do not use this helper.
Source search found no separate bespoke handler using these repeated field IDs;
verify actual widgets/labels/keyboard behavior in disposable browsers. If another
hook is found, stop the dependent repair for reconciliation rather than changing
it silently. No new JavaScript is proposed.

## Shared consumers and risks

Two entry templates are shared; preserve Logistics country choice, cancellation
fee, carrier/vessel names/defaults, `section=logistics_transport`, operating
profile, location links/scripts and all existing personal/business/role guards.
Keep shared `business-settings.css`, settings field include, share include, parent,
forms/views/models and account/password/profile aliases unchanged. No-business
fallback remains the existing shared page. The new rendering tag is unused there.

Do not conflate invoice logo with shell branding, locale text with language
switching, or manual-only help/model confirmation choices with a new booking
policy. File inputs follow native behavior on invalid submissions. Availability
GET may create settings; all browser work requires disposable resources.

## Validation and completion criteria

Follow [the approved validation plan](validation.md) and resource proposal below.
Add focused tests for distinct POST scopes, tenant/role restrictions, no-business/
legacy-profile compatibility, all fields and error-bound values, and the DOM-only
bulk ID repair preserving identical form names/payloads. Reuse UnifiedSettings,
BusinessSettingsViewTests, BusinessBookingSettingsTests, relevant account profile
and InvoiceLogoSettings/validation/rendering tests. Verify local synthetic logo
upload/replace/remove/conflict/invalid/rollback and relevant PDF/HTML regeneration;
no real invoice send or financial/provider writes.

Cover Owner/Admin/Staff/Accountant/Viewer, restricted/no subscription, no business,
second tenant, Dutch/Caribbean address variants, missing/corrupt logo, long content,
empty/active availability and single/bulk invalid cases. Real browser POST checks
prove Staff self-only availability, protected business-wide/other-tenant targets,
atomic bulk rows and original confirmation choices. Configuration/share gates,
legacy anchors, theme/drafts/file selection and independent saves remain usable.

Browser matrix: 1440/768/390px in light/dark plus 320px reflow, RTL, zoom, keyboard,
focus, error labels/legends, unique IDs, contrast, 44px controls, tabs and reduced
motion. Retain axe failures/incompletes and console/request errors with compact
results/representative screenshots. Prove Logistics/fallback rendering and POST
behavior unchanged; preserve all previous Services source/assets and Team work.

## Closed implementation manifest

21 exact paths. SHA-256 before values and shared-consumer details are in
[implementation-manifest.json](implementation-manifest.json); this is the same list
bound by state. Existing dependencies remain read-only, not mutation scope.

| Path | Action | Category | Impact | Purpose |
| --- | --- | --- | --- | --- |
| `src/templates/businesses/settings.html` | modify | implementation | SHARED entry; SERVICE branch | Select Services settings/assets; retain original Logistics/no-business body, forms and stylesheet. |
| `src/templates/businesses/booking_settings.html` | modify | implementation | SHARED entry; SERVICE branch | Select Services booking composition/assets; preserve existing non-Service path and all route guards. |
| `src/templates/businesses/services/settings/assets.html` | add | implementation | SERVICE | Load independent settings stylesheet only for SERVICE. |
| `src/templates/businesses/services/settings/page.html` | add | implementation | SERVICE | Compact identity/index, role/write feedback and existing anchor/section layout. |
| `src/templates/businesses/services/settings/business_form.html` | add | implementation | SERVICE | Complete existing multipart Business form with grouped company/address/region/invoice/logo controls. |
| `src/templates/businesses/services/settings/account.html` | add | implementation | SERVICE | Separate account-prefixed personal save and unchanged password navigation. |
| `src/templates/businesses/services/settings/configuration.html` | add | implementation | SERVICE | Existing capability/role-guarded configuration destinations. |
| `src/templates/businesses/services/settings/booking.html` | add | implementation | SERVICE | Existing booking page hierarchy, plan feedback, rule/availability composition and return links. |
| `src/templates/businesses/services/settings/booking_rules.html` | add | implementation | SERVICE | Unchanged settings form_kind/fields/choices and staff read-only summary. |
| `src/templates/businesses/services/settings/availability_entry.html` | add | implementation | SERVICE | Original Single/Bulk tab hooks and independent forms; explicit bulk DOM-ID accessibility repair only. |
| `src/templates/businesses/services/settings/availability_list.html` | add | implementation | SERVICE | All existing availability fields/inactive count and guarded deactivation POST. |
| `src/templates/businesses/services/settings/share_panel.html` | add | implementation | SERVICE | Services-specific semantic headings around identical authoritative readiness and Copy/Open/Finish setup actions. |
| `src/templates/businesses/services/settings/field.html` | add | implementation | SERVICE | Persistent labels, errors/help and bound widgets; no field-name or form-prefix changes. |
| `src/static/assets/css/services-settings.css` | add | required_asset | SERVICE | Independent Services-only settings/booking styles and both-theme responsive/accessibility states. |
| `src/apps/businesses/templatetags/services_settings.py` | add | implementation | SERVICE | Pure scoped widget rendering/IDs/error associations; no form, validation, permission or data mutation. |
| `src/apps/businesses/test_services_settings_ui.py` | add | tests | SERVICE | Save separation, tenant/permission/logo/booking contracts, unique bulk IDs and Logistics/no-business parity. |
| `scripts/services_settings_browser_check.py` | add | tests | SERVICE | Owned real Django settings/booking forms, labels/themes/reflow/axe and relevant logo/PDF evidence. |
| `scripts/ui_preview/business_settings_fixtures.py` | add | implementation | SERVICE | Fresh synthetic settings/account/logo/availability and Logistics regression scenarios. |
| `scripts/ui_preview/business_settings_preview.py` | add | implementation | SERVICE | Task-specific creation through current guarded session/cluster tooling. |
| `scripts/ui_preview/business_settings_checks.py` | add | tests | SERVICE | Owned source/backend/browser/targeted document checks; fixed allowlisted labels. |
| `scripts/ui_preview/test_business_settings.py` | add | tests | SERVICE | Wrong phase/settings/route/source-ownership refusal before Django or database access. |

## Preservation and integration boundary

Keep Phoenix 1.23.0 and the global shell/theme/asset-loading order. New stylesheet
loads only for resolved SERVICE, with a unique root wrapper and no global token,
button, typography or navigation selectors. Reuse existing Manrope WOFF2 and OFL
unchanged; no new framework, dependency, downloaded font or collected output.

All existing routes, HTTP methods, fields/prefixes, CSRF, hidden discriminators,
messages, bound values, errors, operation/return navigation and conditional gates
remain authoritative. No view/model/form/resolver/role/subscription/quota change.
Shared template modifications only select the new Services include/assets and
retain the original non-Service body. Preserve original fallback bytes and test
rendered Logistics/fallback parity against frozen BEFORE.

The manifest is closed. Additions outside its exact paths require a concrete
revised proposal, not an implicit follow-on edit. Task-owned workflow records
may record authorized phases, baselines, checks and approvals; they do not expand
application scope. Other workstreams and all previous accepted records are protected.

## Review resources and execution

[validation-resources.json](validation-resources.json) specifies the proposed
independent source snapshot/session, HTTP/PostgreSQL ports, settings and owned
synthetic resources. None is created or live-verified yet. Gate B must explicitly
authorize their creation, application of existing migrations on empty disposable
PostgreSQL, synthetic fixtures and server/browser/test evidence. Setup must prove
ownership before migration/fixture/test writes. Never contact ordinary local,
staging, production or Test Lab databases. No ordinary secrets/data/uploads copied.

Implement with `.venv/bin/python` and installed tooling only. Reuse existing
`core`, `cli`, `runtime`, `settings`, `guard` and test boundary without edits or
weakening. New task-specific adapters must reject wrong phase/settings/route/
source/ownership before model import or writes. Freeze the actual working-tree
BEFORE before any approved application edit; adapter setup must support that old
source without importing new production helpers. Canonical fixture hashes must
match before servers start. Keep independent cookies and later review writes.
Refresh AFTER only; never reset or resynchronize. Real Django behavior is the
review, not a static prototype. Existing debug-allocator workaround is disclosed
and cannot establish ordinary-runtime or provider readiness.

## Independent sequential ownership and baseline limits

Team implements first; Settings implements second only if separately authorized.
Each task owns distinct application/test/tooling paths and its own review pair,
fixture identities, manifest and Gate C decision. Approval for one never covers
another. Settings BEFORE must capture the current tree containing completed Team
work. Review any target drift before proceeding; never silently rebaseline.

Both proposals carry an offline Git/target/reference baseline before Gate B.
The helper's broad protected-workspace snapshot also hashes the sibling's mutable
workflow directory: activating both helper baselines while preparing both proposals
would immediately invalidate the first when the second state changes. Keep that
guard intact. Activate Team's helper baseline once after all proposal records are
frozen; activate Settings's helper baseline once at its serial execution preflight,
after verifying the approved design/target hashes and documenting exact authorized
Team ownership. This is first baseline activation, not replacement. Settings has
no existing execution baseline to overwrite. The immutable proposal baseline is
retained. A later broad-snapshot warning on Team must be disclosed and reconciled
against exact sibling ownership; never present a failed helper check as a pass.

No staging/commit/push/merge/deploy, new schema source, provider configuration,
branch/worktree operation, ordinary database mutation or automatic cleanup.

## Gate B decision

Authorize only this task's exact manifest and proposed disposable resources,
under the preserved contracts, exclusions and sequential policy. After B, verify
all identities/baselines immediately before changes, implement, fix/revalidate
within scope and present real Django BEFORE/AFTER evidence. Stop at Gate C for
explicit acceptance; release authorization remains separate.
