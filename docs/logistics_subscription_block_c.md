# Logistics operational allowances — Block C

Implemented on top of the existing uncommitted Blocks A/B. No Blocks D–F,
Stripe activation, environment reset or customer subscription reassignment is
included. The staged tiers remain inactive and excluded from approved checkout.

## Recovery findings

The inspected branch was `feature/mm-testing-phase`, HEAD `216aa7d`
(`Block 06 — Scan continuation, delivery clearance and audit`). The next four
commits were `c974342`, `50d2ec6`, `9481021`, and `82c8a22`. A/B reports,
configuration, tests and migrations were present in the working tree. Partial C
already contained the model/queryset guards, subscription usage field, invitation
coordination, error responses and four additive migrations. Those changes were
retained and completed; nothing was reset, stashed or discarded.
The recovery tracked diff was fourteen files, 356 insertions and 82 deletions,
plus untracked A/B/C reports, helpers, tests, templates and migrations. Those
tracked totals alone do not include the newly added implementation files.

At recovery, the previously recorded 35-test A/B compatibility check had passed,
but the C writer tests and PostgreSQL races had not been completed. The initial C
run found a test attempting the forbidden REGISTERED → IN_TRANSIT transition.
The fixture now uses the existing permitted RECEIVED transition; lifecycle policy
was not relaxed. Subsequent review also closed a bulk-update race in which a
concurrent insertion could enter an unguarded SQL remainder. A real PostgreSQL
reproduction covers that case.

A READ ONLY transaction against the configured **local** PostgreSQL database
found migrations already applied, contrary to the older B checkpoint:

| Migration | Existing database timestamp, UTC |
| --- | --- |
| businesses.0028 | 2026-10-15 00:27:15 |
| businesses.0029 | 2026-10-15 00:27:15 |
| businesses.0030 | 2026-10-15 00:46:31 |
| crm.0017 | 2026-10-15 00:46:31 |
| billings.0013 | 2026-10-15 00:46:31 |
| logistics.0023 | 2026-10-15 00:46:31 |

The provenance of those earlier database operations was not established. This
continuation did not run migrations against that database or reverse them. All
test migrations/writes target disposable SQLite or a separately created PostgreSQL
14 UTF-8 cluster. Development, Staging and Production were not accessed.

A local Business 11 read-only fingerprint was captured and rechecked during this
continuation: Business, subscription/provider fields, assigned plan, all nine user
rows (including password hashes), nine memberships, four locations and twelve
assignments were identical. Only hashes/counts were written to a temporary audit
file; credentials were not printed. This verifies the recovery interval, not the
unknown history of the already-applied migrations. Business 166 was covered by
isolated preservation tests; its deployed database was not accessed.

## Enforced scope and definitions

The existing effective subscription resolver remains authoritative. Guards apply
only to LOGISTICS businesses whose subscription references `logistics-core`,
`logistics-growth`, or `logistics-scale`. Numeric values come from the existing
`PLAN_LIMIT_FIELDS` / `resolve_business_plan_limit` registry, with no separate
entitlement table. Inaccessible or incomplete tier configuration fails closed for
new capacity consumption. Existing approval, local-only bypass, annual interval,
provider expiry, grace and restricted-state policies are unchanged.

| Metric | Core / Growth / Scale | Consuming action |
| --- | --- | --- |
| Staff | 10 / 15 / 25 | New active membership or reactivation; owner included |
| Operating locations | 2 / 4 / 8 | Create active location or reactivate |
| Clients | 250 / 800 / 2000 | Create/reactivate a Client counted by the existing active-client policy |
| Logistics Services | 25 / 50 / 100 | Create active catalog entry or reactivate |
| Parcels / UTC month | 300 / 900 / 1800 | Persist a new Parcel |
| Shipments / UTC month | 80 / 200 / 400 | Persist a new Shipment |
| Invoices / UTC month | 100 / 300 / 600 | Persist a new Invoice, including charge invoicing |

Clients count when `is_active=True` and status is neither INACTIVE nor ARCHIVED,
preserving the original registry definition. Services and locations count active
rows. Staff count active BusinessUser memberships, including an owner whose user
account itself is disabled until the membership is deactivated. Pending unexpired
invitations reserve distinct email seats, case-insensitively, excluding active
members. Refreshing an invitation or accepting its reserved seat does not count
twice. Active membership seats remain the actual account count.

Legacy `logistics` does not enter the new enforcement boundary; its null unlimited
allowances and existing checks remain unchanged. SERVICE retains its original
limits, booking/appointment rules, bulk SQL behavior and billing policy. There is
no Business-ID special case, Test Lab exemption or management-command bypass.

ParcelEvents (3000/9000/18000), email budgets (300/900/1800), and storage planning
GB (1/3/6) retain separate monitoring/planning metadata. They are never passed to
the hard quota boundary. No event, email or storage blocker or new delivery
infrastructure is introduced. Existing operational reports are not represented
as a complete commercial email/storage meter.

## Audited writer inventory

| Entry paths | Shared enforced boundary and behavior |
| --- | --- |
| CRM manual Client creation/edit/reactivation/archive; invoice quick-create; lead-to-Client internal helpers | Client.save plus CapacityQuerySet; existing manual/CSV capacity prechecks preserved |
| Client CSV preview/confirm/replay | Existing locked, atomic Client execution; model guard is the final check; Block A unavailable-vs-unlimited projection retained |
| Service create/edit/reactivation, Service CSV, invoice-line save-to-catalog | BusinessService.save and guarded bulk writes; category/service transactions roll back together; CSV returns capacity_changed with no partial catalog writes |
| Staff invitation create/refresh/accept, inactive membership reactivation, registration and admin/ORM writes | BusinessInvitation.save / BusinessUser.save; invitation services lock tenant before invitation/membership work; reservations avoid double counting |
| LogisticsLocation create/reactivate through location_services, forms/admin and ORM | LogisticsLocation.save and guarded bulk update/create |
| Parcel registration, connected registration UI/JSON, integration/internal calls | register_parcel → Parcel._domain_save; existing idempotency lookup precedes insert; repeated scanner lookups/status actions create no new Parcel |
| Shipment creation and internal/service callers | create_shipment → Shipment._domain_save; existing retry fingerprints and keys preserved; manifests and edits do not consume another creation |
| Invoice creation/manual flow, LogisticsCharge invoice/append/replay, appointment/Client helpers, direct ORM/bulk | Invoice.save / InvoiceQuerySet; new Invoice only; existing invoice identity/line and payment protections retained |
| seed_logistics_demo_data, seed_demo_data, Test Lab dataset/internal fixture writers | The same guarded models/domain services; command rollback tested on quota failure; Test Lab provisioning continues to require the legacy offering |

No separate external integration writer that avoids these model/service paths was
found. Existing ParcelDomainQuerySet still prohibits direct Parcel/Shipment bulk
creation, updates and deletion. No new public endpoint or integration was added.
Model quotas do not substitute for actor, tenant, location or financial permissions.

## Transactions, monthly metering and retries

Writers lock Business first, then its BusinessSubscription with PostgreSQL
`SELECT FOR UPDATE`. The selected plan is read without locking the shared plan
row, avoiding serialization of unrelated businesses on one plan. Guards reload
the persisted row and respect `update_fields` before deciding whether capacity
increases. Managed records cannot be reparented across businesses or have their
creation timestamps changed through the supported ORM paths.

Bulk creation/reactivation executes atomically through the same model checks.
Multi-business batches lock tenant IDs in sorted order. `update_or_create` obtains
tenant locks before its row lock. SQL remainders explicitly exclude managed
tenants, including records inserted after initial row selection. Expression-based
protected bulk updates and conflict-ignoring/upserting managed bulk inserts are
rejected with a clear message; use explicit values or the existing idempotent
service operation. SERVICE conflict/expression paths retain their SQL behavior.

Monthly creation uses the persisted `created_at` supplied by `auto_now_add`, in
half-open UTC calendar months `[month_start, next_month_start)`, independently of
the business timezone. An insertion crossing midnight is checked and metered in
its saved timestamp's month. The subscription's nullable
`logistics_monthly_usage` JSON field stores three integer counters per month.
This is usage state, not another source of entitlements.

On first use of a metric/month, the guard counts only that month's existing rows,
using new `(business, created_at)` indexes. Subsequent checks use the locked
counter rather than recounting history. The insert and increment commit in one
transaction. Rollback consumes nothing; deletion/cancellation never refunds an
already metered creation. Normal subscription saves cannot overwrite the meter
from a stale billing/admin object. Invalid stored counters fail closed. Old months
are retained; growth is three small counters per active month per subscription.

Existing Parcel/Shipment UUID retries and Invoice charge replay/append checks run
before a new insert, so they do not increment twice. Rejected bulk creation also
restores input objects' primary-key/adding/database state for a safe retry. Direct
ordinary Invoice creation remains a new creation on each successful call; callers
needing replay semantics must use an operation with an existing idempotency key.

SQLite supports atomic rollback and serial functional tests, but its
`select_for_update` is ineffective and competing writers can raise database-locked
errors. PostgreSQL is required for the row-lock concurrency guarantee; SQLite
passes are not evidence of concurrent production enforcement.

Only capacity-consuming actions consult the quota. Existing record edits,
deactivation, Parcel events/status progression/cancellation, manifests and Invoice
reads remain subject to their original authorization/subscription rules. No
records are deleted or hidden because an allowance is reached. Existing form
validation/prechecks continue; uncaught QuotaError yields HTTP 409 HTML or JSON
`errors.__all__`, and Service CSV reports a clear atomic execution failure.

## Files and migrations

New C files:

- `src/apps/businesses/usage_limits.py`: transactional model/bulk boundary and UTC metering.
- `src/apps/businesses/quota_middleware.py` and
  `src/templates/businesses/quota_exceeded.html`: understandable HTTP errors.
- `src/apps/businesses/test_logistics_usage_limits.py`: writer, boundary and race coverage.
- This report.

Extended files:

- `businesses/models.py`: nullable subscription meter and guarded membership/invitation saves.
- `businesses/utils.py`: existing usage resolver and invitation locking.
- `crm/models.py`, `crm/client_capacity.py`: shared guards and common lock scope.
- `crm/importing/service_execution.py`: specific atomic quota failure result.
- `billings/models.py`, `logistics/models.py`: guards and indexed bootstrap counts.
- `taskio/settings.py`: quota exception middleware.
- `businesses/test_logistics_capacity_plans.py`: migration preservation tests use
  historical model state when testing schema predating the new usage field.

New additive C migrations:

1. `businesses.0030_logistics_usage_enforcement`: nullable, noneditable JSON field.
2. `crm.0017_logistics_usage_enforcement`: active Client capacity index.
3. `billings.0013_logistics_usage_enforcement`: Invoice business/creation index.
4. `logistics.0023_logistics_usage_enforcement`: Parcel/Shipment business/creation indexes.

These depend on the retained B migrations 0028/0029 where appropriate. They have
no data backfill, customer update, provider call or lab reset operation. Index
creation scans existing tables once during migration, not on hot request paths.

## Validation

| Suite/check | Result |
| --- | --- |
| Final focused A/B/C definitions, model/service/bulk/HTTP/CSV writers and migration preservation, PostgreSQL 14 UTF-8 | 113 tests, OK; all ten concurrency tests executed |
| Same focused suite, SQLite | 113 tests, OK; ten expected PostgreSQL-only skips |
| Final SERVICE regression suite: accounts, businesses, CRM, billings, appointments, notifications | 1022 tests, OK; seventeen PostgreSQL-only skips |
| Broad full Logistics run at earlier C checkpoint | Incomplete: SIGSEGV, exit 139; no full-suite pass claimed |
| Scan module rerun on final code, including the crashing test | 22 tests, OK |
| Final combined local-bypass/Test Lab foundation/dataset/checkout/approval, including all PDF/barcode assertions | 138 tests, OK; two PostgreSQL-only skips |
| Final later Logistics modules including native shipping-label checks | 241 tests, OK; fourteen PostgreSQL-only skips |
| Ruff, Black, Django system checks, migration drift and diff whitespace | Passed |

The focused suite includes 30 C tests. All seven limits exercise N−1/N/N+1 with
small explicit plan fixtures; B tests assert every actual tier capacity, and seat
tests additionally exercise actual 10/15/25 owner-inclusive limits. Seven new
PostgreSQL test methods cover thirteen quota race scenarios, including all seven
last slots, bulk/manual Clients, the concurrent SQL-remainder insertion, same-key
Parcel retries, bulk/service Invoices, invitation versus reactivation, and location
reactivation. The other three PostgreSQL tests preserve A's CSV/manual/replay races.

Other checks cover whole-batch rollback and same-object retries, UTC year/month
rollover (including insertion rollover), deletion without refunds, initial meter
bootstrap, stale subscription saves, malformed meters, unavailable versus unlimited
allowances, restricted subscriptions, charge invoicing replay/append, repeated
scans, over-budget events with a permitted lifecycle transition, tenant moves,
catalog-category rollback, HTTP HTML/JSON errors and a management command failing
atomically without a quota exemption. Migration preservation snapshots include
legacy plan/subscription/provider references, passwords, memberships and locations
for isolated nine-account/four-location fixtures at IDs 11 and 166.

Raw logs: `/tmp/logistics-block-c-postgresql-final.log`,
`/tmp/logistics-block-c-sqlite-final.log`,
`/tmp/logistics-block-c-service-final.log`, and
`/tmp/logistics-block-c-logistics.log`, `/tmp/logistics-block-c-dataset-final.log`,
`/tmp/logistics-block-c-scan-rerun.log`, and
`/tmp/logistics-block-c-logistics-remaining.log`. The first invalid-transition fixture failure
is retained in `/tmp/logistics-block-c-focused-first.log`; no test was disabled.
Regression runners use the established test-only MD5 password hasher, with
faulthandler enabled for the Logistics/native run. The disposable PostgreSQL
server was stopped after final focused validation.

The earlier intermittent crash reproduced in the broad Logistics run during
`apps.logistics.test_scan.ScanWorkflowTests.test_action_creates_one_event_and_returns_next_scan`.
Faulthandler reports garbage collection with the Python stack in
`wsgiref.headers.Headers.__delitem__/__setitem__`, WhiteNoise static responder
construction, middleware loading, and Django's test-client POST. There was no
Python assertion failure or final test summary. The previous A crash had occurred
in dataset/query evaluation, also during GC; the changed stack does not establish
a common native cause. All 22 scanner tests subsequently passed unchanged.

Captured runtime: CPython 3.12.12 (Clang 21.1.4), Django 5.2.11, pypdfium2 5.14.0,
zxing-cpp 3.1.1, Pillow 12.2.0, reportlab 4.5.1, WhiteNoise 6.12.0, brotli 1.2.0,
WSL2 Linux 6.18.54.1/glibc 2.35. Details are also saved in
`/tmp/logistics-block-c-runtime.log`. GDB is unavailable and the host routes core
dumps through `/wsl-capture-crash`; no native backtrace/core artifact was available
in the workspace. Installed PDFium helpers document possible PIL/bitmap buffer
sharing, but that is only an investigation lead, not evidence that it caused
this crash. Dependencies, garbage collection and native barcode assertions were
not changed or disabled. The segmentation fault remains unresolved; isolated
passes must not be interpreted as a full-suite pass or a confirmed runtime fix.
The final 138-test combined dataset run passed in 325.325 seconds, including
`test_missing_and_cross_tenant_ownership_refused` (the previous A failure) and
every-label QR/Code128 decoding at both 203 and 300 DPI. The separate 241-test
later-module run also retained the shipping-label native rendering/decoding
assertions. Neither isolated run reproduced the crash.

Focused SQLite reproduction from the repository root:

```sh
ENV=local DEBUG=False LOGISTICS_LOCAL_BILLING_BYPASS=False \
  DATABASE_URL=sqlite:///:memory: .venv/bin/python src/manage.py test \
  apps.businesses.test_logistics_usage_limits \
  apps.businesses.test_logistics_capacity_plans \
  apps.crm.test_logistics_client_capacity apps.crm.test_client_preview \
  apps.crm.test_client_execution --noinput
```

For PostgreSQL, use these labels against a disposable UTF-8 cluster with its own
test-database creation rights. Do not point QA fixture/seed execution at an
application or provider database.

## Remaining boundaries and rollout

- The boundary covers supported application model/queryset/service writers, not
  privileged raw SQL, `save_base`/raw fixture loading, explicitly invoking base ORM
  methods/managers, historical migration models, or manually overwriting the meter.
  No such operational bypass was found in the audited production writers. New
  integrations must use the guarded APIs; this is not a database-trigger policy.
- Plan/subscription reassignment is not implemented. A future reviewed migration
  must fence tenant writes or acquire the same tenant/subscription locks and check
  usage before switching. Commercial configuration changes must not race bulk
  writer classification. No automatic transition out of legacy is provided.
- Lazy initial monthly baselines can count persisted current-month records, but
  cannot reconstruct records deleted before metering existed. Review the initial
  baseline before any future legacy-to-tier move. No tier customers were moved by
  this code. Preserve existing ledger state across future plan changes/renewals.
- Service CSV preview does not yet project catalog capacity; confirmation performs
  the authoritative atomic check. A ready preview can fail clearly if the whole
  batch does not fit. Improved projection/warnings belong in Block D.
- There is no complete transactional-email delivery meter or measured private
  storage ledger. Monitoring budgets and essential emails remain nonblocking.
- Browser/device interaction and deployed provider QA are not claimed by these
  server-side tests. Development Business 166 compatibility is tested with
  isolated representative fixtures, not by modifying or probing that deployment.

Deployment must be an operator-controlled release: back up the database, inspect
the actual target/migration plan, and apply the additive migrations before the
updated web/workers start. Schedule index creation for the table sizes and lock
window of that environment. Keep all three tiers inactive and Stripe checkout
disabled. Do not run fixture reset/seed commands or change subscriptions as part
of deployment. Verify legacy CSV, SERVICE billing/booking, location permissions,
and an explicitly authorized isolated tier fixture before enabling any commercial
offering. Production activation remains a separate approval/release.

For rollback, stop new-tier capacity-consuming writes while reverting C code;
retain the additive schema and usage counters. Reverting to code without guards
while allowing new-tier writes would permit unmetered usage. Do not reverse the
JSON-field migration after usage exists or reset counters to recover capacity.
Unused indexes can be considered separately during a planned maintenance window.
Legacy/SERVICE plan assignments and Stripe references require no reversal.

Block D prerequisites: reuse these exact UTC periods/active definitions and the
existing capability registry; expose hard usage separately from monitoring and
planning values; add reliable event/email attribution and nonblocking warnings;
measure storage before claiming enforcement; account for deleted historical
records in migration baselines; retain PostgreSQL concurrency coverage and actor/
location authorization. Resource safeguards for exports/manifests must preserve
accepted-work completion. Block E still requires approved annual Price mappings,
currency decisions and provider TEST-mode QA. No D/E/F work is started here.
