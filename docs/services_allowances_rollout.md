# Services allowance rollout

This change targets `ClarivoPlan.family=SERVICE`: Starter 5 users / unlimited clients / 200 invoices / 250 appointments, Pro 10 / unlimited / 500 / 750, Business 15 / unlimited / 2,000 / 3,000. Baseline-compatible Beta receives Pro's allowances. All include public booking. Users include the owner and pending, unexpired invitation reservations.

Prices, regional prices, Stripe mappings, subscriptions, payment records and Logistics entitlements are not updated. Business base/USD remains 159/1590; EUR remains 149/1490 in regional pricing.

## Accounting and writes

Services writers serialize on Business, then BusinessSubscription. Model saves and supported bulk operations enforce finite client/user/invoice/appointment limits, and reject unavailable entitlements. Initial registration can create its first owner before provisioning its subscription; this exception does not apply to additional seats or clients.

Appointments count once from the existing Appointment table, in the UTC calendar month of `start_time`. Every status counts. Deletion releases capacity. Moving to a different month checks that destination, excluding the edited row. Editing within an already over-limit month does not consume another appointment. No historical row is modified by reconciliation.

Book now continues creating a scheduled appointment immediately. Contact-first creates a request and client, consuming appointment capacity only when scheduled. Public slot validation and insertion hold the same tenant lock used by internal writers. This prevents simultaneous public selections from both claiming an occupied staff slot; internal scheduling retains its existing overlap policy.

New public/internal creation forms carry a UUID operation key. Tenant-scoped unique constraints and a bound payload fingerprint replay a completed operation without another appointment/request or another notification. A changed payload with the same key is rejected. Distinct keys permit deliberate multiple appointments from one Lead. Already-open/legacy submissions without a key remain compatible; they cannot receive retry guarantees. Deleting an operation's record also deletes its retry record, consistent with existing deletion semantics.

Draft invoice creation consumes capacity; editing, payment recording, emailing, resending and downloading existing invoices do not. Invitation acceptance exchanges one pending reservation for one active membership inside the lock.

## Public POST protection

A separate technical throttle uses the existing tracking endpoint's atomic cache add/incr pattern, independent keys, hashed client identities and a 30 POST/minute window per business and socket identity. Cache failures deny submissions. CSRF, form validation and existing availability rules remain. This is a new control, not a previously verified Services spam limiter.

`SERVICES_BOOKING_CACHE_ALIAS=default` uses the current per-process LocMem cache. For multiple workers, configure a shared Redis/Memcached alias; the existing `logistics_tracking` alias can be reused with separate Services keys after configuring its backend/location. This does not alter Logistics counters. Keep SECRET_KEY consistent across workers.

`SERVICES_BOOKING_CLIENT_IP_MODE=direct` trusts only REMOTE_ADDR. Use `heroku` only with router-only ingress: it requires DYNO and uses the router-appended rightmost forwarded IP. No client-supplied leftmost header is trusted. Verify the deployed proxy/cache contract before rollout.

## Later deployment steps

1. Back up the target database and capture canonical/custom plan values, all regional prices, provider mappings, subscription billing fields and Logistics snapshots.
2. Run `python src/manage.py inspect_services_allowances` in the intended environment. It is read-only and reports baseline/approved/customized plans, existing over-limit UTC appointment months and multiple appointments linked to one request. Multiple links are review candidates, not proof of duplication.
3. Explicitly reconcile customized/missing canonical or Beta configurations. Migration `businesses.0035` refuses the entire allowance rollout if any targeted row has an unexpected tuple, family or feature flag. It changes only the four approved allowance fields, accepts already-approved tuples and does not create missing plans. Migration reversal does not remove granted allowances.
4. Schedule an application maintenance window: stop/drain old workers and background writers before applying the migrations, so old code cannot continue enforcing the removed request quota or bypass new checks. Review `python src/manage.py migrate --plan` first; reconcile unrelated pending migrations separately. Apply `python src/manage.py migrate businesses 0035 --noinput`, `python src/manage.py migrate crm 0018 --noinput` and `python src/manage.py migrate appointments 0003 --noinput`, then start all workers on this code. The two schema migrations add nullable retry metadata/unique constraints; they do not backfill historical requests or appointments. Ensure all supported writers use the application boundary; raw SQL is not a quota API.
5. Rerun the read-only inspection. Compare the protected snapshots, confirm exact allowances and unchanged subscriptions/prices/Logistics, and review reported historical months/links without automatic changes.
6. Verify shared cache/proxy behavior across workers. Smoke-test EUR/USD, monthly/yearly trial destinations, internal/public scheduling, contact-first, retries, imports and invitation acceptance on mobile/desktop. No Stripe price changes or subscription reassignment are needed.

The original implementation did not migrate local development data. Its automated migration, concurrency and browser evidence used disposable databases. The authorized application-database rollout is recorded below.

## Isolated verification

Start a disposable PostgreSQL cluster with trust authentication on a dedicated loopback port. Set `SERVICES_TEST_PG_PORT` to that port and, if needed, `SERVICES_TEST_PG_USER` to its local superuser. The test settings refuse the default database port and never inherit DATABASE_URL. Do not point this at a shared PostgreSQL service.

```
SERVICES_TEST_PG_PORT=<disposable-port> .venv/bin/python src/manage.py test apps.businesses.test_service_allowances --settings=taskio.services_test_settings --noinput
SERVICES_TEST_PG_PORT=<disposable-port> .venv/bin/python src/manage.py test scripts.services_allowances_browser_check --settings=taskio.services_test_settings --noinput
```

Run the browser check separately from transaction suites that flush migration seed data. It writes screenshots to `/tmp/services-rollout-browser/`.

## Local results — 24 October 2026

- PostgreSQL 14.24, dedicated disposable cluster on loopback port 56439. The expanded targeted suite passed 355 tests; the final focused Services suite passed 30 tests. Eight real concurrency checks cover appointment admission, cross-month reschedule versus creation, public staff slots, public retry submissions, invoice creation, invitations, reactivation and reserved invitation acceptance.
- Chromium passed at 390 px and 1440 px. Verified all three tiers in EUR/USD and monthly/yearly modes, registration destination parameters, subscription usage/cards, absence of a separate public quota, no page JavaScript exceptions and no horizontal overflow. Screenshots are in `/tmp/services-rollout-browser/`.
- Django checks, migration drift check, Ruff for changed production/new test code, Black for the new quota/migration/operation/test modules, and `git diff --check` passed.
- Read-only development preflight: Starter, Pro, Business and Beta all match expected old baselines; no over-limit appointment months or multiple-appointment request links were reported. No development/staging/production migration was applied. The existing dashboard template edit is preserved.
- Logs: `/tmp/services-rollout-final-tests2.log`, `/tmp/services-rollout-focused-final.log`, `/tmp/services-rollout-browser-final.log`. Provider tests use mocks; no live Stripe or deployed cache/proxy verification is claimed.

## Logistics isolation audit — 24 October 2026

The source baseline is Git `02551e103b770bdf8006d9b4c1a615cfcd08fa7a` plus the existing dashboard edit (View Bookings / Create Booking / DISABLED). The index was empty; the Services implementation was unstaged or untracked. Git history and the full working diff were reviewed. An archived checkout of that commit, with the protected dashboard patch, was used for baseline comparisons. The dashboard diff remains byte-for-byte identical to the audit's starting snapshot.

Three shared boundaries needed correction:

| Difference | Classification and correction |
| --- | --- |
| Appointment now uses `ServiceCapacityQuerySet`, inheriting `CapacityQuerySet` as well. The parent selected Logistics tier rows even though Appointment is absent from its Logistics metric registry. | Actual ORM regression: Logistics appointment bulk conflict handling and SQL expressions were rejected. Restrict the parent's tier selection and update handling to its existing `MODEL_METRICS` registry. Logistics appointment bulk writers retain their previous SQL behavior; Services appointment admission remains enforced. This does not enable Logistics appointment pages. |
| `sync_client_from_lead` acquired an unconditional transaction and Business/subscription lock before matching. | Internal concurrency/locking change, rather than a new Logistics entitlement or page: matching now held a Services serialization lock for Logistics callers too. Scope that matching transaction/lock to SERVICE and retain the original matching body for Logistics. Existing Logistics Client model quota locks remain. Supported request/appointment conversion pages already exclude Logistics. |
| Quota middleware sent every anonymous quota error to the Services public-booking template. | Actual error-handler contract change, including anonymous Logistics requests. Limit the new public template branch to the public booking/request routes. Preserve existing Logistics JSON/dashboard error handling. This regression was demonstrated at the middleware boundary; no ordinary Logistics enrollment request was observed hitting this exceptional path. |

Five focused regression tests pass on the archived baseline. The three appointment tests failed on the original implementation; the two shared-boundary tests failed before their corrections. They cover conflict handling, expression updates, bulk updates, the matching lock and anonymous error-template selection.

The remaining shared differences were traced as follows:

| Area | Evidence and Logistics result |
| --- | --- |
| Plans, defaults and migration writes | Shared model allowance defaults and subscription fields are unchanged. Migration 0035 checks the four canonical slugs and SERVICE family, then updates only their four allowance fields. No Logistics plan, subscription, price, activation flag or business is written. The repeatability test compares every plan row and preserves subscription values. |
| Clients and quota accounting | The resolver's available/unlimited distinction is unchanged. Client import previously accepted null limits for Logistics; removing the Services-only rejection keeps that Logistics decision identical. The shared Client/Invoice/member/invitation managers delegate Logistics writes to the original capacity boundary. Existing Logistics deduplicated invitation reservations, finite limits, unavailable-entitlement denial and durable UTC monthly meters remain. Services appointment deletion does not release Logistics invoice/parcel/shipment usage. |
| Appointments, retry metadata and throttling | Services checks require a SERVICE destination. Nullable retry metadata and unique constraints add shared schema but do not backfill Logistics records; existing Logistics writers do not supply keys. Capability checks deny Logistics booking/request/appointment operations. Public POST protection is Services-specific, and cache counters use an independent namespace. Logistics tracking protection is unchanged. |
| Shared invoice helper transactions | `create_invoice_from_lead` gained an outer atomic wrapper, but its Logistics branch already enclosed authorization, Client synchronization and invoice creation in an atomic block. This is a nested transaction refactor with the same permission checks, writes and rollback boundary. |
| Registration, approval, enrollment and annual checkout | Enrollment creates an explicit LOGISTICS business before its owner, and its subscription uses the selected Logistics plan and yearly billing. Existing approval/token/identity/Price validation and webhook gates remain in the call path. Legacy pricing retirement, inactive tier defaults, annual EUR values, disabled Logistics portals and lack of a Logistics trial are preserved. Provider checks are mocked. |
| Permissions, dashboards, navigation and copy | Capability checks and role context builders are unchanged. `logistics_subscription_usage` returns a populated dictionary even for missing/inactive subscriptions, so Logistics never enters the modified Services usage/card branch. Logistics has no Services plan options. Public pricing uses `motionmate_plans()` filtered to active canonical SERVICE plans; the archived landing template is not a routed Logistics page. The protected dashboard patch was retained exactly. |

Three existing enrollment/pilot fixtures used invalid uppercase `OWNER` values or created an owner only after deactivating its Services business. They now use `BusinessUser.Role.OWNER` and create historical membership before deactivation. Their Logistics conflict-policy assertions are unchanged; no production enrollment policy was relaxed.

The broader 305-test investigation found eight failures that reproduce on the archived baseline: two staff shipment-create navigation expectations, one shipment form CSS expectation, one dashboard query-count expectation (88 versus 82), and four demo-seed tests rejecting port references. These are existing issues and were left unchanged. The original 355-test rollout result above is a targeted result, not evidence that every Logistics test passes.

Final verification:

- 106 focused Logistics tests passed: capacity plans and migrations, quota writers/imports/concurrency, usage displays, enrollment/tier enrollment, selected dashboard isolation and shared invoice permissions. Log: `/tmp/services-logistics-targeted-final.log`.
- 132 Services/shared tests passed after the appointment correction and fixture repairs: appointment workflows, Services allowances, subscription/checkout family guards, pilot approval, and real Logistics billing/registration races. Log: `/tmp/services-logistics-shared-verified.log`.
- After the final matching-lock and error-template corrections, 80 tests passed: all five new regressions, Services allowance/concurrency tests, public booking, legacy public requests, and selected Client conversion/scoping cases. Log: `/tmp/services-logistics-final-boundaries-verified.log`. These runs overlap; their counts are not a unique-test total.
- All five regressions also pass on the archived pre-change baseline: `/tmp/services-logistics-baseline-all-regressions.log`. Before-correction failures: `/tmp/services-logistics-before-fix.log` and `/tmp/services-logistics-shared-before-fix.log`. Broader investigation/baseline-failure logs: `/tmp/services-logistics-audit-tests.log` and `/tmp/services-logistics-existing-baseline-failures.log`.
- Django checks, `makemigrations --check --dry-run`, Ruff on audit-changed Python, Black on audit-changed production/new test modules, and `git diff --check` passed. No new schema/model change was needed for these corrections.

All audit databases used a fresh disposable PostgreSQL 14 cluster on loopback port 56449, stopped after verification. No application database migration, application business update, live Stripe call/configuration change, commit, push or deployment was performed. Shared retry schema still requires the planned worker maintenance window; customized canonical plans can intentionally block the Services data migration, so complete its preflight before deploying this combined code. No live-provider, deployed cache/proxy or load-performance verification is claimed.

## Authorized local application rollout — 24 October 2026

### Root cause and instance

The actual local server was the runserver parent PID 80813 and worker PID 2038474, listening on `127.0.0.1:8000`, from `/home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio`. Its interpreter was this checkout's `.venv/bin/python`, settings were `taskio.settings`, environment was `local`, and DEBUG was enabled. The management commands below inherited that process's environment rather than the invoking shell's environment.

The database connection was confirmed as PostgreSQL `taskio_database_dev`, with server address `127.0.0.1` and port 5432. No remote environment was selected. Only the three approved rollout migrations were pending before the copy correction was added: `businesses.0035`, `appointments.0003`, and `crm.0018`.

Both real view contexts selected canonical plan IDs 1/2/3 and contained the old allowance tuples. The authenticated Services owner session selected Business 13 on the Business plan (ID 3): its live usage context was 3/10 users, 15/150 clients, 0/500 monthly invoices and 0/400 monthly appointments. Fresh Chromium requests reproduced the old values. The original isolated tests initialized their own migrated database; they did not establish application-database rollout completion. The new booking wording was template code and therefore appeared independently of the missing data migration. No cache failure or stale response was needed to explain the mismatch.

### Database operations and protected data

The existing read-only `inspect_services_allowances` passed: all four targets were `baseline`; no over-limit months or multiple-appointment request links were reported. No unexpected customized target was found. A private full PostgreSQL backup and protected-row digests were captured before changes. The server was stopped before applying migrations and restarted afterward in the same checkout with its original environment.

Applied successfully in this dependency-valid order, using the existing management entrypoint:

```text
.venv/bin/python src/manage.py migrate businesses 0035 --noinput
.venv/bin/python src/manage.py migrate appointments 0003 --noinput
.venv/bin/python src/manage.py migrate crm 0018 --noinput
.venv/bin/python src/manage.py migrate businesses 0036 --noinput
```

`0035` changed only the four approved allowance fields on Starter, Pro, Business and Beta. The two existing retry migrations added their nullable keys, fingerprints and uniqueness constraints without backfilling historical requests or appointments. New migration `0036_services_starter_description` replaces only the exact original Starter description on the SERVICE-family canonical row, removing “solo owners and”. It preserves customized descriptions, all other plans and all other fields. No existing applied migration was edited, no migration history was faked, and no reconciliation command was needed.

Before/after digests matched for 52 tables containing 1,585 rows, excluding only the explicitly permitted allowance fields, Starter description, migration history, browser sessions and empty newly added retry fields. All remaining plan fields, regional prices, Stripe mappings, subscription states, customer records, role permissions, custom plans, business settings and Logistics records/configuration were preserved. The protected snapshot still matched after browser verification.

Final database and rendered allowances:

| Allowance | Starter | Pro | Business | Internal Beta |
| --- | --- | --- | --- | --- |
| Total users including owner | 5 | 10 | 15 | 10 |
| Staff accounts alongside owner | 4 | 9 | 14 | 9 |
| Clients | Unlimited | Unlimited | Unlimited | Unlimited |
| Invoices/month | 200 | 500 | 2,000 | 500 |
| Appointments/month | 250 | 750 | 3,000 | 750 |
| Online booking | Included | Included | Included | Included |

Beta remains active and free with unchanged access configuration. There are no Beta subscriptions in this local database. Business pricing remains USD 159/1590 and EUR 149/1490; Starter and Pro prices are also unchanged. The legacy `max_public_bookings_per_month` storage is deliberately preserved: Services admission ignores that retired quota, Services usage/comparison contexts omit it, and scheduled appointments share the appointment allowance. The generic legacy scalar resolver still exposes that stored field if explicitly queried; it is not a Services admission limit.

### Copy and actual browser verification

Both routed templates now include `businesses/includes/services_plan_features.html`, visibly listing clients/enquiries; appointments/online booking; services/prices/categories; invoices/payment recording; team roles/permissions; dashboard; client/service imports; business settings; and guided onboarding. Starter's card positioning now refers to small service teams. The subscription page uses one neutral team-roles chip across tiers; permission code is unchanged. All displayed allowance numbers continue to come from database plans.

The restarted runserver parent PID is 2080290, initially serving through worker PID 2080301 at the same loopback URL. Fresh Chromium contexts made actual HTTP requests to `/home/` and `/businesses/subscription/`, using an existing local owner session rather than test fixtures or a disposable live server.

- Desktop 1440 px and mobile 390 px passed for both pages, including usage and all plan comparisons.
- All eight homepage viewport/currency/interval combinations passed: EUR/USD and monthly/yearly. The real currency links and interval switch were exercised. Prices and trial-link plan/currency/interval parameters matched each selection.
- All nine shared features were visibly present on both pages. No stale solo-owner positioning, tier-exclusive role chips, separate booking quota, horizontal overflow or page JavaScript exception was found.
- Current Business usage is 3/15 users, 15/Unlimited clients, 0/2000 invoices and 0/3000 appointments; staff availability is 12 of 14. Actual effective user/client/invoice/appointment entitlements match the refreshed plan.
- The focused Services suite passed 31 tests on a separate disposable PostgreSQL instance on loopback port 56459, subsequently stopped. The added regression covers the description migration's baseline, custom-description and repeatability cases while comparing every plan field.
- Django system checks, migration drift check and `git diff --check` passed. `migrate --plan` reports no pending operations. The post-rollout preflight reports all four plans `approved`, with no reported historical anomalies. Ruff and Black pass for the changed test file; the new applied migration has whitespace-only formatting findings and was left unchanged after application.

Fresh evidence, logs and sanitized snapshots are in `/tmp/services-local-rollout/`: `home-{usd,eur}-{monthly,yearly}-{1440,390}.png`, `subscription-{1440,390}.png`, `subscription-usage-{1440,390}.png`, `browser-results.json`, `browser.log`, `tests.log`, `context-before.json`, `context-after.json`, `preflight-before.json`, `preflight-after.json`, `final-database.json`, and `protected-{before,after}.json`. The database backup remains private. Browser credentials and the copied runtime environment were removed after verification.

No local copy or database rollout step remains. Staging/production rollout and deployed shared-cache/proxy/provider checks were not performed or authorized by this local task. No Stripe mutation, commit, push or deployment was performed.
