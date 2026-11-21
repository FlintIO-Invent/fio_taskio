# Employees & Team Management — Django source audit

21 November 2026 · Full Redesign · SERVICE · source evidence only

Primary screen: `/businesses/team/` (`business_team_members`). This workstream
audits the existing Django implementation. No application was started, database
accessed, page visited, email sent or form submitted. Browser appearance and
interactive behavior remain unverified. `source-audit.json` records exact source
hashes and the Git identity; it is not the frozen interactive BEFORE.

## Existing screens and contracts

| Surface | Verified implementation |
| --- | --- |
| Directory and invitation form | `src/apps/businesses/urls.py`; `views.py:831–967`; `src/templates/businesses/team_members.html`. GET/POST on the same named route. Owner/admin only through `business_role_required`, current Business and active membership. |
| Directory data | All current-Business `BusinessUser` rows, including inactive memberships, with related users; ordered by first name, last name, email. Displays name, email, role, active/inactive and guarded Remove form. No search, filter, pagination or employee detail route. |
| Invitation creation/refresh | `BusinessInvitationForm` in `forms.py:740`; unprefixed `email`, `role`; CSRF; same-route POST. Normalized email; assignable roles intersect actor permission and plan packaging. A repeated pending email refreshes expiry/role and attempts email again through the existing form. |
| Pending invitation list | Current-Business pending rows, newest first; email, inviter, role, expiry and fallback acceptance URL. Links appear only with `workspace_can_modify`. The template displays the URL as text; it has no clipboard button, resend/revoke action or invitation history. |
| Deactivation | POST `/businesses/team/<membership_id>/deactivate/`, `business_team_member_deactivate`, CSRF and existing confirmation prompt. Tenant-scoped lookup; changes membership `is_active`, retains the user and records. Prevents self-removal, role escalation and removal of the last active owner. |
| Invitation acceptance | `/accounts/invitations/accept/<token>/`, `accounts/views.py:556`, `businesses/utils.py:1209`, shared `accounts/forms/accept_business_invitation.html`. Audited as a downstream dependency, excluded from this redesign's application changes. |
| Navigation | Existing guarded Settings/Subscription and dashboard return links; shell `data-onboarding-target="team"` preserved. No workspace switcher. |

The current screen renders an invite/pending row before the directory, uses h2/h4
headings, small table actions/metadata and horizontally scrollable tables. It
prints the internal model name `BusinessUser` in customer-facing directory copy.
These are source findings; no measured overflow, contrast or interaction pass is
claimed.

## Permission, subscription and capacity contracts

- `utils.py:125–180` resolves only active memberships in active Businesses,
  preserving the session selection and legacy first-membership fallback.
- Team GET is owner/admin only. Staff, Accountant and Viewer receive the existing
  denial; no-business requests use setup navigation. Do not turn this management
  list into an employee-wide directory.
- POST checks subscription modification access, the workspace module, same-
  workspace membership, other-workspace conflict and users capacity including
  pending invitations. Keep all error and success messages and submitted values.
- `utils.py:1104` lets Owners assign all role enums; Admins can assign only Staff,
  Accountant and Viewer, further restricted by `forms.py:28` plan packaging.
  Starter allows Owner/Admin/Staff; Pro/Beta additionally Accountant; Business
  additionally Viewer. Display the bound form's choices, never rebuild policy in
  JavaScript. One membership has one role.
- The membership table's Remove visibility is broader than the target-role
  server check: an Admin may see Remove against an Owner/Admin but the POST is
  rejected. Preserve authoritative behavior; do not promise every visible action
  can complete. A target-specific eligibility projection would need an explicit
  Gate B proposal or separate functional change.
- `utils.py:1156` locks capacity scope and refreshes an existing pending invitation
  or creates a token with seven-day expiry. Acceptance validates tenant, email,
  status, activity, competing membership and capacity under existing locks. It
  retains existing active membership roles and may restore an inactive member
  through an invitation already held; the directory has no Reactivate action.
- Email success/failure is reported immediately after submission. There is no
  stored delivery-state column; Pending must not be labeled Delivered.

## GET side effects and existing gaps

1. Team GET bulk-expires elapsed pending invitations (`views.py:837`). Acceptance
   GET can also persist expiry (`accounts/views.py:563`, `utils.py:1132`). Neither
   route is safe to visit against an ordinary database for a read-only audit.
2. The acceptance view supplies `login_form` and a matching signed-in-user POST
   path, but its template renders only `signup_form` fields and the create-account
   button. It has no existing-user password or matching-user accept presentation.
   Existing acceptance tests submit the password directly and do not establish
   that the browser offers that path. This is an existing source-level UI gap,
   not a browser reproduction or a new authentication feature. Repair is a
   separate proposal; Gate A does not authorize it.
3. Membership detail/edit pages, custom role editing, invitation revoke/history,
   bulk invitation/removal, dedicated resend and a clipboard control do not
   currently exist. The schema's Cancelled status is not a cancellation UI.
   Do not fabricate controls or endpoint support.
4. The existing creation form already refreshes a pending invitation when its
   email is submitted again. Preserve that path; distinguish it from a proposed
   per-row Resend button.

## Shared impact and preservation

The team template, view/form, role helpers, context processor, acceptance template,
notification service and navigation serve both verticals. Logistics additionally
has a tenant-scoped invitation `location` field, location column and operational
grant semantics. `test_configuration_update.py` and `docs/logistics_location_access.md`
cover that dependency. A future integration should select a new Services-only
composition from the current template while retaining the existing Logistics
branch and shared backend. Do not edit authentication, email services, global
shell, vendor assets, location logic or permission policies.

The paired Settings workstream owns settings and booking configuration. Team
retains navigation to it; neither task owns the other's templates/assets. Prior
Services Dashboard/Appointments/Clients/Invoices/Catalogue/Data Import/Subscription
redesign sources, accepted workflow records, frozen labs and ignored Phoenix
references are protected.

## Evidence and later validation

Read the relevant route, model, form, resolver, guards, view, shared template,
context processor, email and acceptance paths. Read existing test source:
`BusinessInvitationViewTests`, `BusinessInvitationAcceptanceTests`, current-
Business tests and invitation/location/capacity coverage. No tests ran.

At Gate B identify verified disposable PostgreSQL resources and a task-specific
fixture/browser adapter. The existing preview validator targets Dashboard;
passing it would not prove this journey. Planned checks are in `validation.md`.
Capture current working-tree BEFORE only after implementation/resource consent.
