# Permanent Services Appointments workspace

Appointments is the standard operational workspace for Services. There is no
feature flag. Online scheduled bookings and internal appointments use existing
Appointment rows; active, open REQUEST Leads without a linked appointment appear
as **Needs follow-up**. No artificial date, duplicate record, or schema change is
required. Logistics retains its existing capability and navigation behavior.

## Creation and follow-up

- Open Appointments and choose **New Appointment**. The existing
  `appointment_create` route renders `AppointmentForm`, including the existing
  client selector and inline client dialog. The existing operation handles
  validation, quotas, retries and creation. Success opens appointment details;
  its Appointments breadcrumb returns to the unified list.
- Choose **Create Request** for an internal follow-up. The existing request form
  defaults to REQUEST; new internal records receive the existing STAFF source.
  Successful creation returns to Appointments. The compatibility Interest option
  remains available and opens its historical detail page after creation.
- Public Online Booking remains customer-facing and unchanged. Book now uses its
  existing request/client/appointment transaction. Contact me before booking
  produces an undated request through the existing synchronization handler.
- Open a follow-up to use the existing confirmation/scheduling, client conversion,
  invoice and edit actions. Scheduling preserves its source Lead and Client;
  the linked request stops appearing as a second operational row. Existing Active
  Clients are not downgraded, and Lead remains a Client classification.
- Sidebar and dashboard operational links point to Appointments. Contextual client
  shortcuts and named creation/detail URLs keep using the same established forms.
  **Request history** retains access to closed, inactive and Interest records and
  the original list filters. Public routes and compatibility redirects are retained.

## Access and read projection

The list accepts either appointment or service-request read entitlement and the
existing workspace view roles. Each row type requires its own entitlement.
New Appointment/Edit retain appointment role and write guards; Create Request/Edit
require request role and write access. Request-only plans can follow up without
accessing scheduled appointment rows, creation or details. Existing mutation
endpoints retain their tenant, subscription, role, scheduling and quota guards.

The list reads existing records without rewriting them. It preserves all legitimate
appointments, including multiple historical appointments linked to a request.
Dashboard follow-up/review counts exclude inactive and already-linked requests;
historical total counts remain intact. Booking, notification, payment and invoice
writers are unchanged except for the internal request source and return navigation.

Filters include state, source, classification, staff, service and search; existing
`status` bookmarks continue working. Unknown historical sources, including direct
appointments without source metadata, remain Unspecified. Classification uses the
appointment's Client, or exactly one same-business email match for a request.
Ambiguous/unmatched requests remain Unknown. Staff filters apply to actual
appointment assignments rather than free-text requested staff.

## Validation

Use only `taskio.services_test_settings` and a disposable localhost PostgreSQL
cluster. This settings module refuses port 5432, replaces database configuration,
and uses in-memory email/cache backends. No ordinary development, staging or
production records are needed for validation.

```bash
SERVICES_TEST_PG_PORT=55481 .venv/bin/python src/manage.py test \
  apps.appointments apps.crm.tests.PublicBookingTests \
  apps.crm.tests.DashboardOnboardingViewTests \
  --settings=taskio.services_test_settings --noinput

SERVICES_TEST_PG_PORT=55481 PWA_CHROMIUM=/path/to/chrome \
  .venv/bin/python src/manage.py test scripts.unified_appointments_browser_check \
  --settings=taskio.services_test_settings --noinput
```

Browser coverage includes 1440px and 390px, creation through the workspace, inline
client creation with draft preservation, follow-up creation, filters, scheduling,
classification, invoice navigation, and request-only access. Screenshots are saved
under `/tmp/taskio-unified-appointments-browser`.

## Known limits

The inherited projection materializes filtered results before pagination (50 per
page). Database-level pagination for very large histories is a separate performance
decision. This integration does not infer or backfill missing historical sources.

## Files changed from the supplied Phase 1 workspace

- `.env.example`, `src/config.py`, `src/taskio/settings.py`: remove temporary
  configuration and retain the workspace navigation context processor. The first
  two files now match HEAD because Phase 1 itself was uncommitted.
- `src/apps/appointments/workspace.py`: permanent entitlement-based list access
  and explicit request read/write navigation context.
- `src/apps/appointments/views.py`: always render the unified list after access
  checks; remove the obsolete list/filter fallback and its unused import.
- `src/apps/crm/views.py`: permanent follow-up dashboard counts; default internal
  request creation to REQUEST, set STAFF source, and return to Appointments.
- `src/templates/appointments/workspace.html`: New Appointment, entitlement-aware
  request actions, read-only notice and historical request access.
- `src/templates/appointments/includes/workspace_navigation.html`: one Appointments
  menu, follow-up shortcut and online booking settings/status.
- `src/templates/appointments/list.html`: deleted; no remaining callers after
  removing the temporary fallback.
- `src/templates/inheritance/dashboard_parent.html`: remove the obsolete separate
  operational menus and use the workspace navigation. The pre-existing commented
  Client CSV import link is preserved.
- `src/templates/crm/agent_dashboard/agent_dashboard.html`: operational links lead
  to Appointments; follow-up copy reflects the unified queue.
- `src/templates/crm/forms/lead_create.html`,
  `src/templates/crm/forms/request_convert_to_client.html`, and
  `src/templates/crm/main/lead_detail.html`: Appointments breadcrumbs/return links.
- `src/apps/appointments/test_workspace.py`: retain functional projection,
  authorization and isolation tests; remove flag tests; add creation, retry,
  history, classification and independent entitlement coverage.
- `src/apps/appointments/tests.py`, `src/apps/crm/tests.py`: adapt existing list,
  navigation and request-only access regressions to the standard workflow.
- `scripts/unified_appointments_browser_check.py`: remove flag setup and cover
  workspace-driven creation with inline clients at desktop/mobile sizes.
- `docs/services_unified_appointments.md`: permanent workflow and validation handoff.

No models, migrations, billing/payment operations, public booking handlers,
notification handlers, quota policies, or Logistics implementation files changed.
No commits, pushes or deployments were performed.

## Validation evidence — 11 November 2026

- Final focused run: **148 tests passed**, including all 24 unified-workspace
  tests, existing appointment tests, public-booking and dashboard/navigation
  regressions, and both desktop/mobile Chromium tests
  (`/tmp/taskio-permanent-final-focused.log`).

- Before removing the flag: all 22 Phase 1 tests passed, including its desktop and
  mobile browser workflow (`/tmp/taskio-permanent-baseline.log`).
- Broader regression run: 508 tests, with 502 passing. One new workspace assertion
  accidentally counted navigation text as a row; it was corrected to inspect
  workspace rows and included in the final focused rerun. The remaining five
  failures/errors reproduce in the preserved pre-change source copy.
- Unrelated failures: the existing service CSV-import test expects "Required
  columns" copy; four `VerticalInvoiceAuditTests` demo-seeding tests fail existing
  `port_load_unlocode` / `port_discharge_unlocode` reference validation. The same
  failures occur before this integration. No import or Logistics rules/fixtures
  were changed to hide them.
- Baseline reproduction: 10 tests, five passing and the same one failure/four
  errors (`/tmp/taskio-permanent-prechange-regression.log`). The CSV-import test
  body and its template also match the pre-change files exactly.
- Broader coverage includes appointments, public booking, CRM, quick clients,
  client invoices, Logistics client capacity, payments, invoice presentation,
  concurrency, quotas, vertical isolation, subscription access, settings and team
  invitations (`/tmp/taskio-permanent-regression.log`).
- Django system checks and `makemigrations --check --dry-run` passed (no changes).
  Ruff lint/format checks passed on all nine touched Python files, as did
  `git diff --check`. A broader exploratory format check reported six pre-existing
  formatting findings in untouched appointments files/migrations; they were left
  unchanged.
- Shared navigation before/after the Services module block was compared exactly
  against the supplied Phase 1 workspace and is unchanged.
- All database/browser validation used disposable localhost PostgreSQL on port
  55481, in-memory email/cache backends and local Chromium. This does not claim
  ordinary-runtime database, provider, staging or production verification.

Separate decisions: fix the unrelated CSV-import test copy and Logistics demo
reference fixtures, or optimize projection pagination for very large histories.
None blocks the implemented Services workflow; the broad suite is not fully green.
