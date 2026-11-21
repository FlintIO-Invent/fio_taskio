# Employees & Team Management — design direction v1

21 November 2026 · Full Redesign · Motionmate Services · Gate A pending

Route: `/businesses/team/` (`business_team_members`). Outcome: make existing
membership, invitation and role information easier to understand and manage,
without adding an employee database, new actions or permission policy.

## Authorization and evidence

The user requested: “Automatically complete both audits and design plans.” and
“Stop at Gate A for design-direction approval.” Saved audit/design/state records
are within that workflow request. Application changes, runtime/fixture setup,
data changes, migrations, installations and Git/release actions are excluded.

The [actual Django source audit](audit.md) traces the existing screen and its
downstream acceptance/authentication contracts. [Source identities](source-audit.json)
record branch/HEAD, clean initial working tree and protected source/reference
hashes. No browser visit or runtime check occurred; these are source findings.

## Specific screen composition

| Current task friction | Proposed direction | Preserved behavior |
| --- | --- | --- |
| Secondary navigation competes with the invitation task. | One h1 **Employees & Team**, current workspace and actor role on a compact context line. Primary **Invite team member** jumps to the existing form; secondary Settings, guarded Subscription and dashboard links remain visible. | Existing named routes/guards and onboarding hooks. No create-employee route or modal. |
| Directory is below invitation panels. | Place **Current team** immediately after context/access feedback. Put the existing membership count with the section title. Retain inactive rows. | Existing dataset, sort and count meaning; no search/filter/pagination or extra metrics. |
| Small table text and action targets weaken record scanning. | Member identity/name and email together visually, separate role and textual Active/Inactive state, existing Remove action plainly labeled. All fields remain present. | Existing membership data and CSRF/confirmation-protected POST. No detail/edit/reactivate route. |
| Invitation form has dense explanatory copy. | Group existing Email and Role, followed by Send invitation. Place company-specific-email/one-role/expiry guidance beside the form; use a keyboard-operable disclosure for longer role guidance. | Bound `invite_form` choices and values, non-field/field errors, CSRF and same-route POST. No permission editor. |
| Pending tokens are hard to read in tables. | **Pending invitations** keeps email/inviter, role, expiry and a wrapping, selectable fallback URL. Count remains beside the section heading. Explain the existing refresh-via-form path. | Existing URL visibility/write guard, ordering and expiry. No Copy/Resend/Revoke controls or invented delivery state. |
| Read-only access removes write controls without a local explanation. | Plain notice distinguishing membership role and existing subscription write restriction; keep permitted read content and navigation. | Existing guards/denials remain authoritative. No business-wide directory for Staff/Accountant/Viewer. |

Desktop layout proposal:

```text
Employees & Team                                 [Invite team member → form]
Workspace · Your role          Settings · Subscription (guarded) · Dashboard
Existing messages / access explanation
Current team (existing membership count)
  Name + email | Role | Active/Inactive | Existing guarded Remove
Invite team member (5 columns)   Pending invitations (7 columns)
  Email / Role / Send              Email + inviter / Role / Expires / Fallback URL
  Existing invitation guidance    Existing pending count / honest empty state
```

The header anchor does not submit, change form state or open a new workflow.
The existing form already refreshes a pending email and attempts email again;
presentation may explain that exact behavior. Pending does not prove delivery.
The directory remains an owner/admin management screen, with details inline.

## Roles and permissions presentation

Use the actor's existing role badge and the **server-bound** invitation choices.
Owners may assign role enums permitted by the plan; Admins can assign only
Staff/Accountant/Viewer, further limited by packaging. One membership has one
role. Keep existing guidance to use Admin for combined operational/accounting
access. Avoid a new universal access matrix: module/subscription checks still
apply and Services billing read access must not be hidden by an invented rule.

The existing Remove visibility is broader than target-role authorization. Preserve
the server rejection; a target-specific eligibility projection is a separate
proposal. No promise that every visible Remove operation can succeed.

## Motionmate design and Phoenix integration direction

Use the approved [design system](../../../motionmate-design-system/DESIGN.md),
[components](../../../motionmate-design-system/COMPONENTS.md) and
[vertical boundaries](../../../motionmate-design-system/VERTICALS.md): existing
local licensed Manrope, restrained indigo, quiet surfaces, navy dark surfaces,
12px panels and 8px controls. Reuse Phoenix/Bootstrap components and asset order.
No dependency, font download, Tailwind/DaisyUI production import or framework
migration. The existing licensed Phoenix 1.23.0 reference is present and read-only.

Keep shell/sidebar, navigation breakpoints and brand mark unchanged. Scope assets
and selectors to a unique Services page wrapper; select a Services composition
from the shared entry template while preserving Logistics. Exact file selection
and validation resources follow only after Gate A.

- Desktop: full-width directory; invitation/pending columns below; 20–24px
  spacing, 32px title and 20px section headings.
- Tablet: wrap full record content; stack invitation panels when needed, retaining
  all information and semantic order.
- Mobile: 16px gutters/padding, 28px title, labeled membership and invitation
  records, wrapping emails/URLs and actions of at least 44px. One dataset only.
- Light/dark: same information and guards; semantic text statuses and visible
  boundaries/focus/hover. Preserve Phoenix theme preferences and pending input.
- Accessibility: one h1, ordered headings, table caption/headers/row identity,
  associated errors, native keyboard disclosure, visible focus and existing
  confirmation. Check 320px reflow, zoom, RTL, reduced motion and long content.
  Rendered contrast and screen-reader table behavior remain unverified.

## Separate proposals and exclusions

The audit records an existing acceptance-template gap for existing users; its
shared authentication presentation repair is **not included in v1**. Employee
detail/edit pages, custom role editing, member role changes/reactivation, invitation
revoke/history/per-row resend/copy, bulk operations and directory search need
separate functional proposals. A model status is not evidence of an existing UI.

No backend, schema, record, email/provider, authentication or Logistics policy
change. Preserve prior Services redesigns, shared theme/reference assets and
legacy membership behavior. The [Settings workstream](../services-business-settings-20261121/brief.md)
owns settings and booking configuration; Team retains navigation to it only.

## Validation and Gate A decision

See the [separate validation plan](validation.md). No runtime, browser,
accessibility, data-writing test or provider pass is claimed. After design
approval prepare an exact Gate B manifest/baseline/resource proposal. After Gate
B capture the actual working-tree BEFORE, implement and validate, then refresh
AFTER alone and present one real Django comparison before Gate C.

If both tasks are authorized, implement Team first and Settings second. Keep
separate manifests, preview/fixture identities and Gate C decisions. Neither
task's approval transfers to the other; either may be approved independently.

Approve **Employees & Team Management v1**: directory-first composition, focused
existing invitation form, readable pending invitations and truthful role/access
presentation, subject to these preservation rules/exclusions. Exact artifact
hashes and scope-bound design identity appear in `state.json` and the Gate A
review. Approved design artifacts remain immutable; Gate A authorizes preparing
Gate B proposals only.
