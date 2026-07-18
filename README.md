# Motionmate

Motionmate is a Django multi-tenant SaaS for Caribbean service businesses. The current private-testing release focuses on workspace onboarding, tenant-scoped CRM and billing, invitation-only employee access, role permissions, business-specific services and pricing, invoice service line selection, and plan-based access control.

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
- Stripe SDK dependency and local subscription configuration checks
- Stripe-hosted Checkout setup for paid-plan signup when enabled
- Signed Stripe webhook subscription activation and local time-aware access checks
- Owner-only Stripe Customer Portal entry point for eligible subscriptions

## Out of scope for this release

- Appointments
- Public booking
- Memberships
- In-app plan-change checkout
- Major new product features

Appointment release-candidate staging QA is tracked separately in [docs/APPOINTMENT_STAGING_QA.md](/home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/docs/APPOINTMENT_STAGING_QA.md) and must pass before appointments move into private-tester scope.

## Development workflow

While the live private-test app is being evaluated, keep feature work off the production line.

- `main`: production and private-test stable branch
- `develop`: preferred shared local or staging integration branch, if used
- `feature/*`: new feature branches created from `develop`
- `hotfix/*`: minimal production bug-fix branches created from `main`
- This repo currently has both `develop` and `development` branch variants in Git history and remotes. Standardize on one shared integration branch name before active feature work resumes. The workflow docs use `develop`.

See [docs/DEVELOPMENT_WORKFLOW.md](/home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/docs/DEVELOPMENT_WORKFLOW.md) for the release checklist, hotfix checklist, and promotion flow.

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

## Common local development commands

Install dependencies:

```bash
uv sync --extra dev
```

Run migrations:

```bash
uv run --no-sync python src/manage.py migrate
```

Start the local server:

```bash
uv run --no-sync python src/manage.py runserver
```

Run a targeted app test module:

```bash
uv run --no-sync python src/manage.py test apps.businesses.tests
```

Run a more targeted test case:

```bash
uv run --no-sync python src/manage.py test apps.businesses.tests.BusinessSettingsViewTests
```

Run the migration drift check:

```bash
uv run --no-sync python src/manage.py makemigrations --check --dry-run
```

## Environment variables

`DATABASE_URL` takes priority over the individual `DB_*` variables.

Motionmate private testing and production requirements:

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
- `SERVER_EMAIL`
- `EMAIL_BACKEND`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`
- `EMAIL_USE_SSL`
- `EMAIL_TIMEOUT`
- `MOTIONMATE_PUBLIC_BASE_URL`
- `MOTIONMATE_SUPPORT_EMAIL`
- `STRIPE_ENABLED`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_STARTER_MONTHLY_USD`
- `STRIPE_PRICE_STARTER_YEARLY_USD`
- `STRIPE_PRICE_STARTER_MONTHLY_EUR`
- `STRIPE_PRICE_STARTER_YEARLY_EUR`
- `STRIPE_PRICE_PRO_MONTHLY_USD`
- `STRIPE_PRICE_PRO_YEARLY_USD`
- `STRIPE_PRICE_PRO_MONTHLY_EUR`
- `STRIPE_PRICE_PRO_YEARLY_EUR`
- `STRIPE_PRICE_BUSINESS_MONTHLY_USD`
- `STRIPE_PRICE_BUSINESS_YEARLY_USD`
- `STRIPE_PRICE_BUSINESS_MONTHLY_EUR`
- `STRIPE_PRICE_BUSINESS_YEARLY_EUR`
- `LOG_LEVEL`

Production notes:

- `DEBUG` defaults to `False`.
- `SECRET_KEY` is required whenever `DEBUG=False`.
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are environment-driven.
- When `DEBUG=False`, secure cookie and HTTPS settings default to safe private-testing behavior unless explicitly overridden.
- WhiteNoise serves collected static files in production.
- The literal placeholder `replace-with-real-secret` is only a documentation example and will still trigger `security.W009`. Use a long random secret for real deploy checks.
- Stripe subscription configuration is documented in [docs/STRIPE_SUBSCRIPTION_CONFIG.md](/home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/docs/STRIPE_SUBSCRIPTION_CONFIG.md). `STRIPE_ENABLED=false` keeps Checkout dormant and preserves the local pilot trial flow for normal local work.

## Email Configuration

Local development uses Django's console email backend by default, so transactional emails are printed to the runserver console instead of being delivered.

Production and staging should use SMTP through a transactional email provider. Postmark is the recommended pilot provider unless the project owner chooses otherwise. Acceptable alternatives include Mailgun, SendGrid, Brevo, and Amazon SES.

Gmail SMTP should not be used for production app email. It is designed for mailbox sending, not application delivery, and can make throttling, domain authentication, bounce handling, and deliverability support harder than a transactional provider.

The detailed production runbook is [docs/PRODUCTION_EMAIL.md](/home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/docs/PRODUCTION_EMAIL.md).

Before enabling production delivery:

- Verify the MotionMate sending domain with the selected provider.
- Configure SPF, DKIM, DMARC, and any provider-required return-path or bounce records.
- Use the exact DNS values generated by the provider dashboard. Do not invent DNS values.
- Set `EMAIL_TIMEOUT=10` so slow or hanging SMTP connections do not block requests indefinitely.
- Set `MOTIONMATE_PUBLIC_BASE_URL` to the real deployed app URL used by users.
- Store `MOTIONMATE_PUBLIC_BASE_URL` without a trailing slash.

Local email defaults:

```dotenv
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
MOTIONMATE_PUBLIC_BASE_URL=http://localhost:8000
EMAIL_TIMEOUT=10
DEFAULT_FROM_EMAIL=MotionMate Local <noreply@localhost>
SERVER_EMAIL=MotionMate Local <system@localhost>
MOTIONMATE_SUPPORT_EMAIL=support@localhost
```

Production SMTP example:

```dotenv
MOTIONMATE_PUBLIC_BASE_URL=https://www.motionmate.net
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_TIMEOUT=10
DEFAULT_FROM_EMAIL=MotionMate <noreply@motionmate.net>
SERVER_EMAIL=MotionMate System <system@motionmate.net>
MOTIONMATE_SUPPORT_EMAIL=support@motionmate.net
```

Provider-specific notes:

- `EMAIL_HOST` and `EMAIL_HOST_USER` come from the selected provider dashboard.
- `EMAIL_HOST_PASSWORD` must be stored only in staging or production environment config.
- `EMAIL_PORT=587`, `EMAIL_USE_TLS=True`, and `EMAIL_USE_SSL=False` are the recommended SMTP defaults unless the provider instructs otherwise.

Staging email smoke test:

- Trigger password reset, team invitation, customer request confirmation, internal business alert, appointment confirmation if in scope, and invoice PDF email flows.
- Confirm password reset and invitation links point to the intended MotionMate app URL.
- Confirm the invoice PDF opens.
- Confirm failed sends are logged safely and logs do not expose passwords, reset tokens, SMTP credentials, API keys, or private DNS values.

## Checks and tests

Recommended local verification commands:

```bash
uv run --no-sync python src/manage.py check
uv run --no-sync python src/manage.py makemigrations --check --dry-run
uv run --no-sync python src/manage.py test apps.accounts.tests apps.businesses.tests apps.crm.tests apps.billings.tests apps.appointments.tests
```

Recommended PostgreSQL validation commands:

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='motionmate-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
uv run --no-sync python src/manage.py migrate
```

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='motionmate-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
uv run --no-sync python src/manage.py check
```

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='motionmate-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
uv run --no-sync python src/manage.py makemigrations --check --dry-run
```

```bash
DATABASE_URL='postgresql://taskio_user_dev:self.taskio@localhost:5432/taskio_database_dev' \
DEBUG=False \
SECRET_KEY='motionmate-audit-secret-key-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ' \
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
uv run --no-sync python src/manage.py test apps.accounts.tests apps.businesses.tests apps.crm.tests apps.billings.tests apps.appointments.tests --verbosity 2
```

`python src/manage.py test` and `pytest` are also wired to the same four app suites by default.

If your local PostgreSQL role does not have `CREATEDB`, Django cannot create the temporary `test_...` database automatically. In that case, either:

- grant the local role `CREATEDB`, or
- have a DBA pre-create the PostgreSQL test database and run the suite with `--keepdb`

## Deployment

Motionmate is set up for Heroku-style or Render-style PaaS deployment with a release phase and a Gunicorn web process.
The repo root is the expected working directory for build, release, and web commands.

Build behavior:

- `build.sh` runs `uv sync --locked`
- `build.sh` runs `collectstatic`
- `build.sh` does not run `migrate`

Release and web behavior:

- `Procfile` release: `python src/manage.py migrate`
- `Procfile` web: `gunicorn taskio.wsgi:application --chdir src --log-file - --bind 0.0.0.0:${PORT:-8000}`
- `start.sh` mirrors the Gunicorn web command for environments that use a start script directly

Confirmed deployment behavior for this repo:

- `gunicorn taskio.wsgi:application --chdir src` resolves the correct WSGI app from the repo root.
- Heroku can use `uv` during build, but runtime and release commands should use the installed `python` and `gunicorn` binaries directly.
- `build.sh` does not run migrations, so build does not require a live production database.
- `collectstatic` works from the repo root and WhiteNoise serves the collected assets in non-debug deployments.
- `DATABASE_URL` overrides the individual `DB_*` settings when present.
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are fully environment-driven.
- `DEBUG=False` requires an explicit `SECRET_KEY` and automatically enables safe secure-cookie and HTTPS defaults unless overridden.

## Private Production Test Deployment

Motionmate private testing must use a real PostgreSQL-backed deployment.
Do not use SQLite as the private test app database.

### Required environment variables

Minimum deployment values:

- `SECRET_KEY`: use a long random secret value
- `DEBUG=False`
- `ALLOWED_HOSTS`: include the deployed hostname
- `CSRF_TRUSTED_ORIGINS`: include the deployed HTTPS origin
- `DATABASE_URL`: point to the managed PostgreSQL database

Recommended explicit production security values:

- `SECURE_SSL_REDIRECT=True`
- `SESSION_COOKIE_SECURE=True`
- `CSRF_COOKIE_SECURE=True`
- `SECURE_HSTS_SECONDS=3600`
- `SECURE_HSTS_INCLUDE_SUBDOMAINS=True`
- `SECURE_HSTS_PRELOAD=True`
- `USE_X_FORWARDED_PROTO=True`
- `SECURE_REFERRER_POLICY=strict-origin-when-cross-origin`
- `LOG_LEVEL=INFO`

Email and invitation notes:

- Production email readiness and launch checks are tracked in [docs/PRODUCTION_EMAIL.md](/home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/docs/PRODUCTION_EMAIL.md).
- `DEFAULT_FROM_EMAIL` should be set to the sending identity you want testers to see.
- `SERVER_EMAIL` defaults to `DEFAULT_FROM_EMAIL` when it is not set.
- `EMAIL_BACKEND` defaults to the console backend locally.
- For staging or production SMTP delivery, set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend` plus `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and either `EMAIL_USE_TLS=True` or `EMAIL_USE_SSL=True` according to the provider.
- Set `EMAIL_TIMEOUT=10` for staging and production SMTP delivery.
- Set `MOTIONMATE_PUBLIC_BASE_URL` to the deployed app URL with no trailing slash, for example `https://www.motionmate.net`.
- Set `MOTIONMATE_SUPPORT_EMAIL` to the support inbox shown in security emails.
- If live email is not configured yet, use the manual invitation link fallback from the team flow rather than assuming invite delivery is live.

Static-file note:

- No extra static environment variable is required for the current PaaS setup.
- `build.sh` runs `collectstatic`, and WhiteNoise serves the collected files in the deployed app.

Example deployment environment:

```dotenv
SECRET_KEY='replace-this-with-a-long-random-secret'
DEBUG=False
ALLOWED_HOSTS=motionmate-2026-abc123.herokuapp.com,motionmate.example.com
CSRF_TRUSTED_ORIGINS=https://motionmate-2026-abc123.herokuapp.com,https://motionmate.example.com
DATABASE_URL=postgresql://app_user:app_password@db-host:5432/motionmate
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=3600
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
USE_X_FORWARDED_PROTO=True
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=motionmate-smtp-user
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_TIMEOUT=10
DEFAULT_FROM_EMAIL=MotionMate <noreply@motionmate.net>
SERVER_EMAIL=MotionMate System <system@motionmate.net>
MOTIONMATE_SUPPORT_EMAIL=support@motionmate.net
MOTIONMATE_PUBLIC_BASE_URL=https://www.motionmate.net
LOG_LEVEL=INFO
```

### Heroku/PaaS deployment sequence

1. Create the app or web service and attach a managed PostgreSQL database.
2. Set the required environment variables, especially `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and `DATABASE_URL`.
   For Heroku-hosted smoke testing, `ALLOWED_HOSTS` must include the exact generated `*.herokuapp.com` hostname shown in the browser or logs, and `CSRF_TRUSTED_ORIGINS` must include the matching `https://...` origin.
3. Deploy the repo from the repository root so the platform can run `build.sh`.
4. Let the build complete `uv sync --locked` and `collectstatic`.
5. Let the `release` process run `python src/manage.py migrate` against PostgreSQL before the web process is promoted.
6. Start the `web` process with Gunicorn through the existing `Procfile` entry.
7. Create or confirm a superuser, an active default trial plan, and the default Pro public-request behavior before sharing tester links.

### Post-deploy smoke checklist

Run this quick pass on the deployed PostgreSQL-backed app before inviting testers:

- System/admin: app loads over HTTPS, static CSS and JS load, admin login works, and no obvious 500s appear on `/home/`, `/accounts/login/`, or `/admin/`.
- Business owner flow: owner can register a business, log in, reach `/crm/agent/dashboard/`, and load `/businesses/settings/` and `/businesses/subscription/`.
- Team flow: owner or admin can create an invite, the invite can be accepted, the employee joins the existing workspace, and no new workspace is created for the invitee.
- Role permissions: owner has full current-scope access, admin remains elevated, staff stays CRM-focused, accountant stays client and billing focused, and viewer stays read-only.
- CRM flow: client create and edit work, service requests can be created, and records remain invisible across businesses.
- Services flow: a category and a priced business service can be created and stay scoped to the active business.
- Public request flow: `/crm/public_request/<business_slug>/` loads, `REQUEST` submissions upsert clients safely, `INTEREST` submissions stay lead-only if supported, and plan gating blocks the route only when expected.
- Billing flow: invoices can be created from clients, saved services can be selected, manual lines can be added, totals compute correctly, statuses can move from draft to sent to paid, and lower roles cannot perform restricted billing actions.

See [docs/USER_TESTING_PLAN.md](/home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/docs/USER_TESTING_PLAN.md) for the deeper scenario-by-scenario pass after this first smoke test.

## Private-testing deployment checklist

- Set all production environment variables
- Confirm the deployment uses PostgreSQL, not SQLite
- Confirm the release phase can reach the database
- Run migrations against PostgreSQL successfully
- Run `check --deploy`
- Confirm static assets load after `collectstatic`
- Confirm a default active trial plan exists
- Confirm the default Pro or Pro Trial path allows the public request form
- Confirm the email provider has verified the MotionMate sending domain
- Confirm SPF, DKIM, DMARC, and provider-required return-path/bounce DNS records are configured from provider-supplied values
- Confirm `MOTIONMATE_PUBLIC_BASE_URL=https://www.motionmate.net` is set with no trailing slash before sending live password reset or invitation links
- Run the staging email send checklist in `docs/PRODUCTION_EMAIL.md` before enabling production delivery
- Run smoke routes on the PostgreSQL-backed deployment before sending invite links
- Create one owner account, one invited teammate account, and one superuser
- Verify `/accounts/register-business/`, `/accounts/login/`, `/crm/public_request/<business_slug>/`, `/crm/agent/dashboard/`, `/businesses/subscription/`, and `/admin/`

## Rollback and troubleshooting

- `DisallowedHost` or HTTP 400 on first load usually means `ALLOWED_HOSTS` does not include the deployed hostname.
- On Heroku, fix that with the full current hostname, for example `ALLOWED_HOSTS=motionmate-2026-abc123.herokuapp.com` or `ALLOWED_HOSTS=motionmate-2026-abc123.herokuapp.com,motionmate.example.com`.
- CSRF origin failures usually mean `CSRF_TRUSTED_ORIGINS` is missing the exact HTTPS origin, including scheme.
- On Heroku, that usually means `CSRF_TRUSTED_ORIGINS=https://motionmate-2026-abc123.herokuapp.com` plus any custom `https://...` domain you also use.
- `ImproperlyConfigured: SECRET_KEY must be set when DEBUG=False` means the app is in production mode without a real `SECRET_KEY`.
- `DATABASE_URL` errors or release migration failures usually mean the PostgreSQL credentials, hostname, or network access are wrong.
- `/bin/sh: 1: uv: not found` on Heroku release or web dynos means the runtime command still depends on `uv`. Use `python` and `gunicorn` directly in `Procfile` and startup scripts.
- Missing CSS or JS usually means the build did not complete `collectstatic`, the release used the wrong working directory, or the deploy skipped the standard build step.
- If `check --deploy` still warns, make sure you are not using the literal placeholder secret and explicitly set `SECURE_HSTS_INCLUDE_SUBDOMAINS=True` and `SECURE_HSTS_PRELOAD=True` when your domain policy allows it.
- If local PostgreSQL test runs fail with `permission denied to create database`, grant the local role `CREATEDB` or pre-create the test database and run Django tests with `--keepdb`.
- If invitation or booking emails are not arriving, confirm the deployed `EMAIL_BACKEND` and SMTP provider settings or fall back to manual invite-link testing for the smoke pass.
- If a bad code deploy reaches production-like testing, roll back to the previous app release first. Avoid ad-hoc schema reversals unless you have a deliberate migration rollback plan.

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
