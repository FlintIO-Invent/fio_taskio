# Employees & Team Management — Gate B integration proposal

Design: **v1**, Gate A approved by the user's exact reply “approved” following
both Gate A links. See [approval record](gate-a-approval.json). Implementation
and resource authorization remain pending. Approved design artifacts are frozen.

Route `/businesses/team/`; root scope `.mm-services-team`.

## Production integration

The existing `team_members.html` continues to extend the same Phoenix parent.
Add a SERVICE-only page-assets block and content branch; non-Service rendering
retains its complete current template body. No parent/navigation change.
New independent partials provide the directory-first screen, invite form and
pending records; retain all names/emails/roles/active states, ordering, membership
count, CSRF/confirmation Remove forms and exact guards. Group fields using native
bound-field rendering with existing IDs/names and Django-associated help/errors.
Role guidance states only audited role/plan rules; choices still come from the
bound form. The primary invitation control is an anchor to the existing form.

Pending URLs remain selectable/wrapping text under the original write condition.
No new Copy, Resend, Revoke, employee detail/edit, search, bulk operation or role
editor. Existing repeated-email refresh and email success/failure feedback stay
unchanged. The existing-user acceptance-template defect stays excluded; document
server-path versus browser-path coverage rather than repairing authentication.

## Shared consumers and risk

The entry template serves Logistics too. Preserve its location field/column,
location-access link, roles, work context and grant semantics byte-for-byte in
the fallback. Owner/Admin restriction, workspace write checks, tenant lookups,
capacity locks and last-owner/self/higher-role removal protections stay server-side.
No changes to notifications, login/logout/password/invitation acceptance or models.

Template Remove visibility remains broader than target-role server eligibility;
the redesign must retain denial feedback without claiming all visible actions
succeed. Team/acceptance GET expiry writes run only in disposable resources.
Long emails/token URLs must wrap safely and remain readable; never include real
invitation tokens in durable records. Runtime tests use synthetic invitations.

## Validation and completion criteria

Use [the approved validation plan](validation.md) plus the resource scope below.
Add focused meaningful backend tests for role/tenant/write/capacity/POST behavior,
preservation of fields/actions and untouched Logistics rendering. Reuse existing
`BusinessInvitationViewTests`, `BusinessInvitationAcceptanceTests`, current-
Business, location-invitation and relevant capacity checks where compatible.
Fixture setup covers all five roles, active/inactive memberships, pending/expired
invitations, long/empty/read-only/plan-restricted records and a second tenant.
Invitations/email tests use local-memory delivery; no live provider delivery.

Actual browser checks cover real login/CSRF/invite/deactivate behavior, validation,
role/plan denials, new form anchor, unchanged navigation, theme/draft preservation,
1440/768/390px and 320px reflow, keyboard/focus/labels/contrast/44px controls,
RTL/zoom/reduced motion and axe with raw incompletes. Distinguish existing acceptance
controls gap from regressions. Record a small representative screenshot set and
console/request failures. Logistics regression includes location/grant states.
Hash-prove prior Services redesigns unchanged; check relevant links/navigation.

## Closed implementation manifest

14 exact paths. SHA-256 before values and shared-consumer details are in
[implementation-manifest.json](implementation-manifest.json); this is the same list
bound by state. Existing dependencies remain read-only, not mutation scope.

| Path | Action | Category | Impact | Purpose |
| --- | --- | --- | --- | --- |
| `src/templates/businesses/team_members.html` | modify | implementation | SHARED entry; SERVICE branch | Select Services-only content/assets; preserve original non-Service body and backend guards. |
| `src/templates/businesses/services/team/assets.html` | add | implementation | SERVICE | Load the task-specific Services stylesheet only. |
| `src/templates/businesses/services/team/page.html` | add | implementation | SERVICE | Directory-first composition, role/access context, guarded anchors and navigation. |
| `src/templates/businesses/services/team/directory.html` | add | implementation | SERVICE | All existing membership fields, inactive rows and original guarded Remove POST/confirmation. |
| `src/templates/businesses/services/team/invite_form.html` | add | implementation | SERVICE | Existing email/role form, exact choice/error/CSRF behavior and truthful invitation guidance. |
| `src/templates/businesses/services/team/pending_invitations.html` | add | implementation | SERVICE | Existing pending records, expiry/inviter/role and selectable wrapping fallback URL. |
| `src/templates/businesses/services/team/field.html` | add | implementation | SERVICE | Native bound-field rendering with existing IDs/names and associated help/errors. |
| `src/static/assets/css/services-team.css` | add | required_asset | SERVICE | Services-wrapper-only Manrope/tokens/layout, responsive records, both themes, focus/reflow/RTL/reduced motion. |
| `src/apps/businesses/test_services_team_ui.py` | add | tests | SERVICE | Meaningful permission/POST/form-preservation and unchanged Logistics rendering regressions. |
| `scripts/services_team_browser_check.py` | add | tests | SERVICE | Real Django browser/forms/accessibility/reflow and protected-consumer evidence on owned resources. |
| `scripts/ui_preview/team_fixtures.py` | add | implementation | SERVICE | Guarded fresh synthetic team/invitation and Logistics regression fixture source; no ordinary data. |
| `scripts/ui_preview/team_preview.py` | add | implementation | SERVICE | Task route/port adapter through existing session initialization and start guards. |
| `scripts/ui_preview/team_checks.py` | add | tests | SERVICE | Allowlisted owned-source/backend/browser checks through existing verified test boundary. |
| `scripts/ui_preview/test_team.py` | add | tests | SERVICE | Negative ownership/phase/route guard tests before any Django/model/database import. |

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
