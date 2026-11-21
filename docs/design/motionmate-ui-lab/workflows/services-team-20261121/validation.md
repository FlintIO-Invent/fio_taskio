# Team — planned validation and evidence limits

Status: prospective plan only. No Django, tests, browsers, databases, email,
providers or previews ran. Gate A permits no runtime setup. The v1 design is
bound separately from any later validation results.

## Gate B resource proposal to prepare after A

Identify exact task-owned temporary snapshot/session roots, HTTP ports, settings,
separate BEFORE/AFTER PostgreSQL clusters/databases and disposable test database.
Verify live process/host/port, cluster directory/system identifier and ownership
before any data-writing operation. Ask for existing migrations on empty disposable
PostgreSQL and synthetic fixture/test/browser output only, explicitly scoped to
this workstream. Never read an ordinary `.env`, records, uploads or secrets.

Use `.venv/bin/python`. Keep providers/network/real email/workers disabled; use
local-memory email for invitation success/failure checks. Preserve preview identity,
network and financial guards. Inspect existing tools before execution. Dashboard
validation is not a Team adapter; propose exact fixture/check source in Gate B.
No resource is currently selected, verified or authorized.

## Server and workflow checks after B

| Cases | Required evidence |
| --- | --- |
| Roles/tenant isolation | Owner and Admin may read; Staff/Accountant/Viewer denied; unauthenticated login and no-business setup behavior. Cross-tenant deactivation IDs fail; inactive membership/business cannot obtain active context. Legacy multi-membership resolver unchanged. |
| Plan/write restrictions | Trial/active, read-only/restricted, no subscription, workspace-module unavailable, users limit reached. No invite/link/remove writes when existing guards deny. Counts retain existing meaning. |
| Role choices/removal | Owner/Admin choices intersect actual plan choices; invalid/tampered role POST rejected; self-removal, target higher-role removal and last-owner removal rejected; normal staff deactivation remains a soft membership change. User and other records unchanged. |
| Invitation form | Real browser login/CSRF and normal POST; invalid/duplicate/other-workspace email; seven-day expiry; existing pending-email refresh; capacity reservation including pending invites; success/failure email messages and fallback URL. No live delivery. |
| Acceptance dependency | Synthetic fresh-user, existing-user, matching/wrong signed-in user, expired/accepted/cancelled token, inactive account, conflicting membership and restricted subscription. Separate direct server POST evidence from browser-offered controls. Record the known existing-user template gap; do not claim full browser acceptance coverage if it remains. |
| Navigation/data | Guarded Settings/Subscription links, dashboard return and onboarding hook. Membership data/order and inactive rows; current tenant only; GET expiry writes confined to disposable fixture databases. No unexpected backend/source changes. |

Reuse relevant existing tests after checking fixture compatibility:
`apps.businesses.tests.BusinessInvitationViewTests`,
`apps.accounts.tests.BusinessInvitationAcceptanceTests`, current-Business tests,
invitation/location tests in `apps.businesses.test_configuration_update` and
relevant capacity checks. Broaden only for changed shared consumers/unresolved
failures. Do not add tests solely mirroring markup.

## Real Django browser and accessibility

- Freeze actual working-tree BEFORE before implementation; record immutable
  sources and equivalent initial synthetic fixture hashes in independent databases.
  Refresh AFTER only. No automatic reseed/resynchronization; review writes diverge.
- Check 1440/768/390px in light/dark plus 320px reflow, long names/emails/URLs,
  populated/empty lists, invalid fields and restricted states. There is no
  independent async loading state; do not invent one.
- Check headings/landmarks, record/header association, visible focus, tab order,
  labels/error associations, 44px controls, native confirmation, role disclosure,
  action contrast, RTL, zoom and reduced motion. Run axe and retain failures and
  incompletes; automated checks alone do not certify accessibility.
- Capture a small representative set and compact results. Distinguish browser,
  isolated server/static, provider and manual findings. Record console/request
  errors and existing failures; do not silently call them passes.

## Protected consumers and review

If the shared team entry template changes, prove Logistics keeps its current
markup/assets/location field/column and invitation/location-grant behavior under
Owner/Admin and relevant denied roles/subscription states. Include current-site,
no-site, unreviewed and inactive-site conditions where shared regression needs
location setup. Preserve shared authentication and fixture identities.

Compare protected previous Services screens/sources and all other workflow records;
no completed redesign's assets are editable scope. Team checks own Team artifacts;
Settings artifacts belong to that task. After B/C sequencing, no old approved
manifest may silently absorb another task's newly changed files.

At Gate C present this workstream's real BEFORE/AFTER URLs, review accounts
locally, source/candidate/fixture/environment identities, actual validation
results, representative screenshots and all limitations. Stop for explicit
acceptance. Commit preparation follows C, but staging/commit/push/deploy still
needs separate authorization. Keep review resources available; no cleanup.
