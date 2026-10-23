# Logistics annual plans and capabilities — Block B

Implemented 2026-10-15 on top of Block A. This block defines staged capacity tiers
in the existing subscription architecture. It does not implement Block C creation
checks/counters, change existing subscriptions, or enable new Stripe checkout.

## Plan definitions

| Metric | `logistics-core` | `logistics-growth` | `logistics-scale` |
| --- | ---: | ---: | ---: |
| Name | Logistics Core | Logistics Growth | Logistics Scale |
| Annual EUR | 1700 | 2300 | 3000 |
| Accounts/seats, including owner | 10 | 15 | 25 |
| Active operating locations | 2 | 4 | 8 |
| Active Clients | 250 | 800 | 2000 |
| New Parcels / UTC month | 300 | 900 | 1800 |
| New Shipments / UTC month | 80 | 200 | 400 |
| New Invoices / UTC month | 100 | 300 | 600 |
| Logistics Services | 25 | 50 | 100 |
| ParcelEvents / month monitoring budget | 3000 | 9000 | 18000 |
| Transactional emails / month monitoring budget | 300 | 900 | 1800 |
| Private storage planning GB | 1 | 3 | 6 |

The account interpretation follows the original owner-inclusive counting rule.
The existing `staff_account_limit` presentation excludes the owner, so it reports
9/14/24 additional staff accounts for these 10/15/25 total-seat plans.

All rows are `family=LOGISTICS`, `is_active=False`, `allow_invoicing=True`.
Billing metadata permits only `yearly`, has zero trial days and sets
`checkout_enabled=False`. Public SERVICE plan lists remain starter/pro/business.
Existing fields store total users, active Clients and monthly Invoices. Seven new
nullable `ClarivoPlan` fields store the other capacities:

| Central metric key | Model field | Resolution kind |
| --- | --- | --- |
| `users` | `max_users` | `active_records` |
| `locations` | `max_locations` | `active_records` |
| `clients` | `max_clients` | `active_records` |
| `services` | `max_services` | `active_records` |
| `parcels_per_month` | `max_parcels_per_month` | `monthly_creations` |
| `shipments_per_month` | `max_shipments_per_month` | `monthly_creations` |
| `invoices_per_month` | `max_invoices_per_month` | `monthly_creations` |
| `parcel_events_per_month` | `parcel_events_per_month_budget` | `monitoring_budget` |
| `transactional_emails_per_month` | `transactional_emails_per_month_budget` | `monitoring_budget` |
| `storage_gb` | `storage_planning_gb` | `storage_planning` |

Monthly Logistics allowances have `period=calendar_month_utc` metadata. Actual
new-metric counting and UTC period enforcement remain Block C/D work. The existing
usage summary keeps only its already-metered metrics; unmeasured usage is not shown
as zero. Current Clients/users/Invoices retain their existing enforcement paths;
this block introduces no new writer guards, rate limits, operational counters, or
hard ParcelEvent/email/storage limits.

## Included features and resolver

Every tier enables public tracking, QR/barcode scanning, Parcels, Shipments,
manifests, invoice PDFs, multi-location operations, location permissions, Parcel
history and Logistics Services through the existing vertical capability policy.
Feature aliases resolve to existing modules: public tracking/scanning to tracking,
PDFs to invoicing, and multi-location/location permissions/history to Parcels.
Existing module access, actor roles, location assignments and financial authorization
remain independently required. A capability does not grant an employee permission.

`resolve_business_plan_limit()` from Block A is extended in place. Its result keeps
`available` and `limit`, adding `kind`, `period` and an `unlimited` property.
`get_business_plan_limit()` retains its scalar contract. No second quota engine or
entitlement table exists. `get_plan_limit()` supports the same new metric registry.

An accessible legacy `logistics` plan still treats null operational limits as
unlimited, including Clients. Missing/inaccessible subscriptions and unknown keys
remain unavailable. Null event/email/storage budgets indicate no configured
budget, not unlimited infrastructure. SERVICE requests for Logistics-only metrics
are unavailable. Each new capacity tier must have all ten capacity values populated
before effective subscription access is granted; missing values cannot become an
accidental unlimited tier. The guarded local exception still requires DEBUG, local
environment, compatible annual state and no approval hold. It cannot extend to
Development, Staging or Production, and it cannot bypass numeric Client capacity.

The Block A Client CSV projection and atomic execution are reused unchanged.
SERVICE CSV null-limit policy remains unchanged. Tracking/scanning/status mutations,
manifests and PDFs keep their existing behavior; no lifecycle budget blockers were
added.

## Pricing and Stripe staging

The new tiers store proposed EUR annual amounts in `price_yearly` and an explicit
`regional_prices.eur` entry. Their existing non-null monthly database field contains
an unused zero placeholder; the pricing API returns `monthly=None` and displays
"Annual billing only". No USD regional entry or USD amount exists. Requesting USD
for a new tier returns an unconfigured annual amount and "Not configured", without
falling back to EUR or inventing free USD pricing. Existing SERVICE and legacy
Logistics pricing fallback behavior is unchanged.

Subscription compatibility now recognizes annual offering metadata separately from
Stripe billability. This allows deliberately authorized isolated tier fixtures
while preserving the new tiers' inactive commercial state. `BILLABLE_PLAN_SLUGS`
and the generated Stripe Price map still contain only starter/pro/business/logistics.
New tiers are rejected by shared Checkout and price-map resolution even if a plan
row is activated manually or a stray mapping is supplied. Webhooks cannot activate
them through an unapproved Price mapping. Existing enrollment/activation/portal
guards remain in place; they have not been extended into a new purchasing flow.

Block E must deliberately approve and configure each offered tier/currency:

- Keep yearly licensed recurring billing, with EUR 1700/2300/3000 validated against
  actual approved Stripe Prices. No provider IDs were created or supplied here.
- Decide USD prices explicitly before offering USD; do not derive them from FX or
  the EUR values. Disabled currencies must stay unavailable.
- Extend the approved billable allowlist, validated Price mappings and configuration
  inputs together, retaining SERVICE and legacy mappings.
- Extend enrollment, activation, Checkout, webhook identity/price verification,
  grace/recovery, portal and notification behavior with provider TEST-mode QA.
- Keep existing paying customers on legacy `logistics` until an explicit reviewed
  opt-in/renewal migration preserves their contractual limits and accepted work.

## Migrations and legacy preservation

Apply migrations in order before running the updated application:

1. `businesses.0028_logistics_capacity_fields`: seven nullable integer fields on
   `ClarivoPlan`, with null retained on all existing plans.
2. `businesses.0029_logistics_capacity_plans`: insert the three inactive tiers only.

The data migration uses frozen values and never updates an existing plan. Matching
rows are a no-write rerun; a conflicting reserved slug raises for manual review.
It never selects or updates `BusinessSubscription`, customer prices, memberships,
credentials, locations or seed records. The legacy `logistics` row is not reseeded,
renamed or assigned to a new tier. Existing four-location labs remain on legacy.

Rollback should normally revert code and retain the additive schema/catalog. The
seed reverse operation first refuses any subscribed or modified tier, then removes
only unchanged, unused staged rows. It does not repoint subscriptions. Removing
schema fields after real use would lose configuration, so retain schema in a
customer rollback. No migration or seed command was executed against the existing
Local, Development, Staging or Production application databases in this work.

## Changed files

- `src/apps/businesses/models.py`: nullable capacities, staged pricing, complete-tier
  validation and subscription compatibility.
- `src/apps/businesses/plan_catalog.py`: stable tier slugs and required capacity fields.
- `src/apps/businesses/billing_policy.py`: annual metadata and explicit disabled checkout.
- `src/apps/businesses/capabilities.py`: aliases to included existing features.
- `src/apps/businesses/utils.py`: extend the existing registry and structured resolver.
- `src/apps/businesses/stripe_config.py`, `src/taskio/settings.py`: preserve the approved
  billable map and reject staged tier Price mappings.
- `src/apps/businesses/migrations/0028_logistics_capacity_fields.py` and
  `0029_logistics_capacity_plans.py`: additive schema and guarded staged plan seed.
- `src/apps/businesses/test_logistics_capacity_plans.py`: definitions, resolution,
  staging, rollback/collision and exact legacy/lab migration preservation tests.
- `docs/logistics_subscription_block_b.md`: this report. Existing Block A changes
  remain in the working tree and were not discarded.

## Validation and segmentation fault investigation

Tests use disposable SQLite databases and a separate PostgreSQL 14 UTF-8 instance. Provider
interactions are mocked; no real Stripe products, prices or subscriptions change.
Migration tests snapshot every existing plan, subscription/provider reference,
credential hash, membership and location for representative nine-account,
four-location fixtures at Business IDs 11 and 166. These IDs exist only in tests.

| Suite/check | Result |
| --- | --- |
| Tier definitions/resolution/migrations, vertical capabilities, legacy Logistics billing and Client preview/execution, PostgreSQL | 129 tests, OK, including 3 Client concurrency races |
| Same focused suite, SQLite | 129 tests, OK, 3 expected PostgreSQL-only skips |
| SERVICE regressions: accounts/businesses/CRM/billings/appointments/notifications | 990 tests, OK, 10 PostgreSQL-only skips |
| Unmodified full Logistics local-bypass/foundation/dataset/checkout/approval baseline | 138 tests, OK, 2 PostgreSQL-only skips |
| Same full combined Logistics suite with Block B | 138 tests, OK, 2 PostgreSQL-only skips; all dataset/label assertions included |
| Ruff, Black, Django check, migration drift, diff whitespace | Passed; only the two intended new migrations |

Raw final logs are `/tmp/logistics-block-b-postgresql-final.log`,
`/tmp/logistics-block-b-sqlite-final.log`, `/tmp/logistics-block-b-service.log`,
and `/tmp/logistics-block-b-dataset-final.log`. The SERVICE and final full Logistics
runners use the established test-only MD5 hasher for disposable credentials. Actual
password hashes remain unchanged. HTTP/template assertions verify the server-side
import behavior; no new browser UI or deployed provider QA is claimed.

The earlier Block A failure was SIGSEGV during garbage collection in
`LogisticsTestLabDatasetTests.test_missing_and_cross_tenant_ownership_refused`, with
the stack in Python inspect/Django expression/query evaluation and dataset seeding.
The suite also performs PDFium/Pillow/ZXing decoding before that test. No native
library or bitmap-lifetime root cause has been established; the stack alone does
not establish one. The unmodified full combined suite was rerun with faulthandler
enabled and passed 138 tests (2 existing PostgreSQL-only skips), including both
the previous failing test and all label-decoding assertions. No tests, garbage
collection or native checks were disabled. The second full run with Block B also
passed all 138 tests (2 existing PostgreSQL-only skips). The previous segmentation
fault is not reproduced and its cause remains unconfirmed; these passes do not
constitute a confirmed fix to the earlier crash.

Captured runtime: CPython 3.12.12, Django 5.2.11, pypdfium2 5.14.0, zxing-cpp 3.1.1,
Pillow 12.2.0, reportlab 4.5.1, Linux WSL2 6.18.54.1/glibc 2.35. The prior trace is
`/tmp/logistics-block-a-dataset-crash.log`; the clean baseline rerun log is
`/tmp/logistics-block-b-dataset-baseline.log`. A first PostgreSQL attempt used an
accidental SQL_ASCII test cluster and rejected Unicode notification JSON in two
existing billing tests. That test-only cluster was stopped and replaced with UTF-8;
application behavior was not changed to accommodate it.

## Block C prerequisites

- Implement actual UTC half-open monthly counts and consistent active-record
  definitions in the existing registry; reconcile older business-timezone reports.
- Put final capacity checks under the shared Business/subscription lock for all
  writers, including activation/reactivation, invitations, quick-create, imports,
  APIs and direct service calls. Invoice creation through charges also needs coverage.
- Reuse existing idempotency and replay checks before new-record capacity is consumed.
  Keep PostgreSQL races for manual/bulk/service combinations and boundary rollover.
- Decide the active `BusinessService` catalog policy; keep ServiceCategory behavior.
- Preserve existing operational/location/financial permissions, legacy unlimited
  limits and accepted-work lifecycle operations when creation capacity is exhausted.
- Add actual event/email metering and 80%/100% warnings in the later monitoring
  block; essential lifecycle, security and billing notifications must remain safe.
- Measure per-business private storage before advertising technical GB enforcement.

Block C is not started by this change.
