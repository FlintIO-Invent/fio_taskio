# Motionmate Appointment Staging QA

## Purpose

This checklist is for Motionmate's internal appointment workflow release candidate before appointments are exposed to private testers.

This is staging/PostgreSQL QA only. It does not add or expand product scope.

## Release candidate scope

The staging pass must cover the current internal appointment workflow:

- Internal appointment management
- Manual appointment creation
- Appointment creation from a service request
- Appointment visibility on the dashboard
- Appointment visibility on client detail pages
- Appointment visibility on service request detail pages
- Invoice creation from an appointment
- Role enforcement
- Plan enforcement
- Tenant isolation

Key routes to verify:

- `/appointments/`
- `/appointments/create/`
- `/appointments/create/from-request/<lead_id>/`
- `/appointments/<appointment_id>/`
- `/appointments/<appointment_id>/edit/`
- `/appointments/<appointment_id>/change-status/`
- `/billings/from-appointment/<appointment_id>/`
- `/crm/agent/dashboard/`
- `/crm/staff/clients/<client_id>/`
- `/crm/staff/leads/<lead_id>/`
- `/businesses/subscription/`
- `/admin/`

## Environment requirements

The staging or private-test app must use PostgreSQL.

Required expectations:

- `DEBUG=False`
- `SECRET_KEY` is a real long random value
- `ALLOWED_HOSTS` includes the exact deployed hostname
- `CSRF_TRUSTED_ORIGINS` includes the exact deployed HTTPS origin
- `DATABASE_URL` points to the managed PostgreSQL database
- Static files load correctly through the deployed app
- Migrations are applied through the release phase before web traffic is promoted
- `python src/manage.py check --deploy` is reviewed with production-style settings

Current deployment shape in this repo:

- `Procfile` release runs `python src/manage.py migrate`
- `Procfile` web runs `gunicorn taskio.wsgi:application --chdir src --log-file - --bind 0.0.0.0:${PORT:-8000}`
- WhiteNoise serves collected static assets when `DEBUG=False`

## Pre-deploy local validation

Run these from the repo root before pushing the release candidate:

```bash
uv run --no-sync python src/manage.py check
uv run --no-sync python src/manage.py makemigrations --check --dry-run
uv run --no-sync python src/manage.py test apps.accounts.tests apps.businesses.tests apps.crm.tests apps.billings.tests apps.appointments.tests
```

If local PostgreSQL test database creation is blocked by missing `CREATEDB`, treat SQLite as a local fallback only for development unblocking. Do not treat SQLite-only success as sufficient staging signoff.

Recommended PostgreSQL-oriented local validation when a real PostgreSQL database is available:

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='motionmate-staging-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
uv run --no-sync python src/manage.py migrate
```

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='motionmate-staging-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
uv run --no-sync python src/manage.py check --deploy
```

## Post-deploy PaaS checks

After the staging deploy completes, run:

```bash
heroku run "python src/manage.py check" --app <staging-app>
heroku run "python src/manage.py check --deploy" --app <staging-app>
heroku run "python src/manage.py showmigrations" --app <staging-app>
```

Review logs during smoke testing:

```bash
heroku logs --tail --app <staging-app>
```

What to confirm:

- No unapplied migrations remain
- No repeated 500 errors appear in logs
- No static-file manifest or WhiteNoise errors appear
- No `DisallowedHost`, CSRF, or database connection errors appear

## Browser smoke checklist

### A. System health

- Load `/home/` and confirm Motionmate branding is visible
- Load `/accounts/login/` and confirm Motionmate branding is visible
- Confirm CSS, JS, and favicon assets load correctly
- Load `/admin/` and confirm admin login works
- Confirm logs do not show repeated 500 errors during basic navigation

### B. Business owner flow

- Register a business
- Log out and log back in
- Open `/crm/agent/dashboard/`
- Open `/businesses/settings/`
- Open `/businesses/subscription/`
- Confirm subscription and module access display correctly

### C. Services, client, and request flow

- Create a service category
- Create a business service
- Create a client
- Create an internal service request
- Submit a public request if the current plan allows it
- Confirm public request client upsert is safe and does not overwrite richer existing client data

### D. Appointment flow

- Confirm appointment navigation appears only when the plan allows appointments
- Create an appointment manually from `/appointments/create/`
- Create an appointment from `/appointments/create/from-request/<lead_id>/`
- Confirm the appointment appears on the dashboard
- Confirm the appointment appears on the client detail page
- Confirm the appointment appears on the service request detail page
- Update an appointment
- Change appointment status
- Confirm invalid time ranges are blocked
- Rename the linked service and confirm the appointment keeps its original service-name snapshot

### E. Appointment to invoice flow

- Create an invoice from `/billings/from-appointment/<appointment_id>/`
- Confirm the invoice uses the appointment client
- Confirm the line item pre-fills from the appointment service when available
- Confirm a manual line item still works
- Confirm totals calculate correctly
- Confirm invoice status changes work

### F. Role checks

- `Owner` can manage appointments and invoices
- `Admin` can manage appointments and invoices
- `Staff` can manage appointments but not invoices
- `Accountant` can manage invoices but appointments are read-only
- `Viewer` is read-only

### G. Tenant isolation

- Create two businesses
- Verify one business cannot access another business's clients
- Verify one business cannot access another business's service requests
- Verify one business cannot access another business's appointments
- Verify one business cannot create an invoice from another business's appointment
- Verify direct cross-business URLs return the expected `404` or permission response for the current pattern

## Issue tracking format

Capture each staging issue with:

- `issue`
- `URL/page`
- `role`
- `expected behavior`
- `actual behavior`
- `log output`
- `severity: blocker/high/medium/low`
- `fix branch`
- `retest result`

## Release decision gate

Appointments can be exposed to private testers only if all of the following are true:

- Migrations pass on PostgreSQL
- Browser smoke tests pass
- No tenant leakage is found
- No role-permission bypass is found
- No repeated 500 errors appear in logs
- Appointment and invoice workflows work end-to-end
- Motionmate branding is consistent in the visible UI

## Coverage notes

The current automated suites already cover the main release-candidate behaviors, including:

- Appointment time validation and service-name snapshots
- Service request to appointment linking
- Dashboard, client-detail, and request-detail appointment visibility
- Appointment-to-invoice creation
- Role boundaries for owners, admins, staff, accountants, and viewers
- Tenant scoping for clients, requests, appointments, services, and invoices
