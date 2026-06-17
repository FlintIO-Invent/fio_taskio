# Clarivo

Clarivo is a Django multi-tenant SaaS for Caribbean service businesses. The current private-testing release focuses on workspace onboarding, tenant-scoped CRM and billing, invitation-only employee access, role permissions, business-specific services and pricing, invoice service line selection, and plan-based access control.

The internal Django package name remains `taskio` for now. That is expected.

## Current private-testing scope

- Business workspace registration
- Business login
- Invitation-only employee access
- One active workspace per login for the current MVP
- Tenant-scoped clients and service requests
- Tenant-scoped invoices
- Business-specific service categories
- Business-specific services and prices
- Public request forms at `/crm/public_request/<business_slug>/`
- Workspace subscription and plan enforcement

## Out of scope for this release

- Appointments
- Public booking
- Memberships
- Stripe billing
- Major new product features

## Local setup

1. Install dependencies:

```bash
uv sync --extra dev
```

2. Create local environment variables:

```bash
cp .env.example .env
```

3. Choose one database strategy:

- For private production testing and production, use PostgreSQL.
- Set `DATABASE_URL` to a PostgreSQL database, or use the PostgreSQL `DB_*` values from `.env.example`.
- Use SQLite only as a temporary local fallback when a PostgreSQL test database cannot be created on your machine.

4. Run migrations:

```bash
uv run --no-sync python src/manage.py migrate
```

5. Start the development server:

```bash
uv run --no-sync python src/manage.py runserver
```

6. Optional admin user:

```bash
uv run --no-sync python src/manage.py createsuperuser
```

## Environment variables

`DATABASE_URL` takes priority over the individual `DB_*` variables.

Clarivo private testing and production requirements:

- PostgreSQL is required before inviting external testers.
- Validate migrations and smoke flows against a real PostgreSQL-backed deployment.
- SQLite is acceptable only as a local emergency fallback while unblocking development.

Important settings for local and production use:

- `DEBUG`
- `SECRET_KEY`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `DATABASE_URL`
- `DB_ENGINE`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`
- `SECURE_SSL_REDIRECT`
- `SESSION_COOKIE_SECURE`
- `CSRF_COOKIE_SECURE`
- `SECURE_HSTS_SECONDS`
- `SECURE_HSTS_INCLUDE_SUBDOMAINS`
- `SECURE_HSTS_PRELOAD`
- `USE_X_FORWARDED_PROTO`
- `SECURE_REFERRER_POLICY`
- `DEFAULT_FROM_EMAIL`
- `EMAIL_BACKEND`
- `LOG_LEVEL`

Production notes:

- `DEBUG` defaults to `False`.
- `SECRET_KEY` is required whenever `DEBUG=False`.
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are environment-driven.
- When `DEBUG=False`, secure cookie and HTTPS settings default to safe private-testing behavior unless explicitly overridden.
- WhiteNoise serves collected static files in production.

## Checks and tests

Recommended local verification commands:

```bash
uv run --no-sync python src/manage.py check
uv run --no-sync python src/manage.py makemigrations --check --dry-run
uv run --no-sync python src/manage.py test apps.crm.tests apps.accounts.tests apps.businesses.tests apps.billings.tests
```

Recommended PostgreSQL validation commands:

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='clarivo-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
uv run --no-sync python src/manage.py migrate
```

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='clarivo-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
uv run --no-sync python src/manage.py check
```

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='clarivo-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
uv run --no-sync python src/manage.py makemigrations --check --dry-run
```

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='clarivo-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
SECURE_SSL_REDIRECT=True \
SESSION_COOKIE_SECURE=True \
CSRF_COOKIE_SECURE=True \
SECURE_HSTS_SECONDS=3600 \
SECURE_HSTS_INCLUDE_SUBDOMAINS=True \
SECURE_HSTS_PRELOAD=True \
USE_X_FORWARDED_PROTO=True \
uv run --no-sync python src/manage.py check --deploy
```

Recommended Django suite command:

```bash
uv run --no-sync python src/manage.py test apps.crm.tests apps.accounts.tests apps.businesses.tests apps.billings.tests --verbosity 2
```

`python src/manage.py test` and `pytest` are also wired to the same four app suites by default.

If your local PostgreSQL role does not have `CREATEDB`, Django cannot create the temporary `test_...` database automatically. In that case, either:

- grant the local role `CREATEDB`, or
- have a DBA pre-create the PostgreSQL test database and run the suite with `--keepdb`

## Deployment

Clarivo is set up for Heroku-style or Render-style PaaS deployment with a release phase and a Gunicorn web process.

Build behavior:

- `build.sh` runs `uv sync --locked`
- `build.sh` runs `collectstatic`
- `build.sh` does not run `migrate`

Release and web behavior:

- `Procfile` release: `uv run --frozen python src/manage.py migrate`
- `Procfile` web: `uv run --frozen gunicorn taskio.wsgi:application --chdir src --log-file - --bind 0.0.0.0:${PORT:-8000}`
- `start.sh` mirrors the Gunicorn web command for environments that use a start script directly

Deployment requirements:

- `SECRET_KEY` must be set
- `DEBUG=False`
- `ALLOWED_HOSTS` must include the deployed hostname
- `CSRF_TRUSTED_ORIGINS` should include the deployed HTTPS origin when forms are submitted cross-origin or through the public domain
- `DATABASE_URL` should point to the production PostgreSQL database
- `USE_X_FORWARDED_PROTO=True` is recommended behind Heroku/PaaS SSL termination
- `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and `SECURE_HSTS_SECONDS` should be enabled for internet-exposed private testing
- Configure a real email backend before invitation-based testing if you want live email delivery

## Private-testing deployment checklist

- Set all production environment variables
- Confirm the deployment uses PostgreSQL, not SQLite
- Confirm the release phase can reach the database
- Run migrations against PostgreSQL successfully
- Run `check --deploy`
- Confirm static assets load after `collectstatic`
- Confirm a default active trial plan exists
- Confirm the default Pro or Pro Trial path allows the public request form
- Run smoke routes on the PostgreSQL-backed deployment before sending invite links
- Create one owner account, one invited teammate account, and one superuser
- Verify `/accounts/register-business/`, `/accounts/login/`, `/crm/public_request/<business_slug>/`, `/crm/agent/dashboard/`, `/businesses/subscription/`, and `/admin/`

## Useful routes

- `/home/`
- `/accounts/register-business/`
- `/accounts/login/`
- `/accounts/agent_login`
- `/accounts/invitations/accept/<token>/`
- `/businesses/settings/`
- `/businesses/subscription/`
- `/businesses/team/`
- `/crm/agent/dashboard/`
- `/crm/public_request/<business_slug>/`
- `/crm/staff/clients/`
- `/crm/staff/leads/`
- `/crm/settings/service-categories/`
- `/crm/settings/services/`
- `/billings/`
- `/admin/`
