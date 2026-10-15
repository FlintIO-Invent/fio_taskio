# Logistics annual subscriptions — Block A audit and CSV repair

Checkpoint: 2026-10-15. This change implements Block A only. Blocks B–F, including
new plan rows, quota enforcement, Stripe mappings, and financial simulation, have
not been implemented. No deployment, subscription migration, provider request,
or application-data write is part of this block.

## CSV capacity failure

`apps.crm.importing.client_preview.project_client_capacity()` previously rejected
any `None` result from `get_business_plan_limit(..., "clients")`. That scalar API
returns `None` both for an inaccessible/missing subscription and for an accessible
plan whose `max_clients` is null. Manual creation treats the latter as unlimited.
The legacy `logistics` plan seeded by businesses migration 0026 has a null Client
limit. As a result, even a legitimately accessible legacy Logistics subscription,
including the guarded local billing bypass, could never produce a ready CSV preview.

The repair adds a structured result to the existing central plan resolver:

| Resolution | Available | Limit | Logistics CSV behavior |
| --- | --- | --- | --- |
| Compatible subscription with full effective access, numeric limit | Yes | Integer, including zero | Check the whole batch against remaining active capacity |
| Compatible subscription with full effective access, legacy null limit | Yes | Null/unlimited | Allow within existing upload and row safeguards |
| Missing subscription, unknown limit, or no full effective access | No | Null | Block with `client_capacity_unavailable` |
| Valid finite allowance with insufficient remaining capacity | Yes | Integer | Block with `client_capacity_exceeded` |

`get_business_plan_limit()` retains its scalar return contract for existing callers.
`BusinessSubscription.has_access` remains authoritative for tenant/plan compatibility,
annual-only Logistics billing, active state, provider period expiry, approval holds,
grace/restricted access, and the existing local-only exception. No new bypass exists.
SERVICE CSV null-limit behavior is explicitly unchanged: it still fails closed.

The preview displays active usage, a numeric or Unlimited allowance, and remaining
capacity. Execution uses the same projection again under the existing transaction
and capacity locks. An import never selects just the first rows that fit. Existing
server-bound previews, duplicate classification, rollback, and completed-job replay
remain in place.

### Local configuration observed separately

A transaction explicitly set to READ ONLY inspected the configured local PostgreSQL
database, `taskio_database_dev` on localhost. The legacy plan was inactive with a
null Client limit; local Test Lab Business 11 was pending checkout. The shell's
effective settings had `LOGISTICS_LOCAL_BILLING_BYPASS=True`, `DEBUG=False`, and
environment `local`. Consequently its effective access was `plan_inactive`, not the
local bypass. The repair does not grant access to that configuration. The existing
local bypass requires all three: the flag, DEBUG enabled, and environment `local`,
plus the subscription's existing compatibility and approval checks. A separately
started web process may have different environment overrides.

No settings, plans, passwords, memberships, locations, or operational records were
changed in that database. Development, Staging, and Production were not accessed.
The configured local database role lacks CREATE DATABASE; PostgreSQL tests instead
use a separate disposable cluster, never the Test Lab database.

## Architecture to reuse in subsequent blocks

| Concern | Existing implementation | Required later extension or audit finding |
| --- | --- | --- |
| Tenant and vertical | `Business`, `Business.vertical`, `BusinessUser` | Continue tenant-scoped authorization; do not encode environment-specific Business IDs |
| Subscription and pricing | `ClarivoPlan`, `BusinessSubscription` in `apps.businesses.models` | Extend these models; preserve `logistics` and existing provider references |
| Domain capabilities | `apps.businesses.capabilities` | Vertical features already include Clients, invoicing, services, Parcels, tracking, Shipments and manifests; this module is domain policy, not a numeric quota store |
| Numeric entitlement resolution | `apps.businesses.utils.PLAN_LIMIT_FIELDS`, `get_business_plan_limit`, `resolve_business_plan_limit`, `get_business_usage_count` | Existing fields cover users, Clients, monthly invoices, appointments and public bookings; extend the existing registry for new Logistics metrics |
| Staff seats | Active `BusinessUser` memberships; invitations in `businesses.views` | Central usage includes owner and optionally pending invitations. Serialize invitation acceptance/reactivation as well as creation |
| Locations and assignments | `LogisticsLocation`, `LogisticsLocationAssignment`, `location_services.save_location`, `location_access*` | Count active locations and check creates/reactivations under a tenant lock; keep authorization independent |
| Active Clients | Existing `Client`, CRM views, `crm.client_capacity`, CSV preview/execution | Central active usage excludes `is_active=False`, INACTIVE and ARCHIVED; includes other statuses. Preserve that definition until a deliberate policy change |
| Service catalog | Existing tenant-owned `BusinessService` with `is_active`; `ServiceCategory` unchanged | Define active catalog count and cover manual creation, imports, and saving invoice lines as catalog entries |
| Parcels | `Parcel`, `parcel_services.register_parcel` | Existing business locks and retry keys can serialize new-record checks; resolve retries before consuming capacity |
| Shipments | `Shipment`, `shipment_services.create_shipment` | Reuse business locks, idempotency keys, fingerprints and revisions; count new rows in UTC month |
| ParcelEvents | `ParcelEvent`, `parcel_services.record_parcel_event` | Existing event history/idempotency; add reporting and warnings, never a hard lifecycle quota |
| Charges and invoices | `LogisticsCharge`, `logistics.billing_services`, existing `Invoice` / `InvoiceLine`, `billings.services.create_invoice_for_client` | A charge is not an invoice. Enforce only actual new Invoice creation across direct and charge-to-invoice flows; appending/downloading must not consume another allowance |
| Operational monitoring | `logistics.usage`, existing subscription view/template | Reuse UI; reconcile definitions before presenting commercial usage |
| Billing entry points | `billing_policy`, `stripe_config`, `stripe_checkout`, `stripe_portal`, `stripe_webhooks`, `logistics.billing`, enrollment/approval services | Annual Logistics is currently allowlisted as slug `logistics`; several enrollment/checkout guards explicitly check it. All must be extended together, with options disabled until configured |
| Notification delivery | `SubscriptionNotification`, `subscription_notifications` outbox; `notifications.emails.send_templated_email` | Subscription outbox has deduplication/attempt/sent state; general mail is not a comprehensive per-business metering ledger. Add reliable recipient/attempt semantics without blocking essential security/billing mail |
| Storage | Django storage settings and current upload/preview retention | No reliable per-business private-storage meter found. Default configured storage backend is filesystem; do not claim object storage or enforced GB quotas |
| Test Labs | `logistics.test_lab`, `test_lab_dataset`, setup/seed commands, owned seed records and safety gates | Existing fixture explicitly expects legacy `logistics`; retain nine accounts and four locations, never reassign the lab to Core implicitly |

At this checkpoint the offering/access policy accepts only the existing
`logistics` slug for Logistics subscriptions. Block B must give each new tier its
finite limits explicitly and validate required configuration before granting access;
it must not accidentally inherit unlimited defaults from the legacy plan.

### Gaps to address before declaring commercial quota coverage

- Existing manual Client creation and CSV execution share `lock_client_capacity_scope`:
  lock Business, then subscription (and its selected plan), then import membership/job.
  PostgreSQL row locks serialize cooperating writers; SQLite does not prove this.
- Invoice quick-create Client currently checks capacity without that shared locked
  recheck. Client edit/reactivation also needs coverage. Direct ORM/model saves are
  not a universal quota boundary. Block C must inventory all writers rather than
  claim the CSV repair covers them.
- Manual invoice UI checks monthly allowance before the shared service creates the
  Invoice. The service locks Business but does not itself enforce that quota.
  Charge invoicing and any direct service call must share the final check.
- The central user count uses active memberships, including owner; Logistics
  monitoring additionally requires an active user. Central Clients count several
  non-archived statuses; Logistics monitoring counts ACTIVE only. Reuse consistent
  commercial definitions and do not silently change SERVICE counters.
- Logistics monitoring currently uses the Business timezone for monthly reporting;
  requested commercial quotas require UTC half-open calendar months. Current
  eligibility thresholds are planning signals, not plan entitlements.
- Logistics usage still reports application-estimated location counts despite the
  operational location model now existing. Commercial usage should count actual
  active locations. This block does not change monitoring.
- Public tracking uses privacy-safe fields and an atomic-cache throttle, denying
  lookups on unavailable/invalid cache configuration. Scanning resolves existing
  authorized Parcels. Neither lookup creates a Parcel or consumes creation capacity.
  Preserve native BarcodeDetector, ZXing fallback, manual and keyboard-wedge inputs.
- Manifests and invoice PDFs are generated on demand through existing permissions.
  Manifest generation currently materializes the shipment's Parcels; there is no
  new request-size protection in this block. Resource bounds belong in Block D.
- No hard ParcelEvent, email, or storage cap is introduced. Required arrivals,
  status changes, deliveries and cancellations retain existing behavior.

## Compatibility and staged rollout

This block has no migrations. Its production diff consists of the central resolver,
CSV projection, and Unlimited template labels, plus tests and this report. It does
not alter plan records, commercial amounts, Stripe mappings, or subscription state.

Changed files:

- `src/apps/businesses/utils.py`: structured resolution, preserving the scalar API.
- `src/apps/crm/importing/client_preview.py`: distinguish Logistics unlimited and
  unavailable capacity, retaining the existing SERVICE policy.
- `src/templates/crm/importing/client_preview.html`: Unlimited labels.
- `src/apps/crm/test_logistics_client_capacity.py`: entitlement, UI, execution,
  compatibility and PostgreSQL race coverage.
- `docs/logistics_subscription_block_a.md`: this audit and rollout checkpoint.

The later plan block should create distinct Logistics Core/Growth/Scale identifiers
and preserve `logistics` as legacy. EUR annual proposed amounts are 1700/2300/3000;
they do not authorize Stripe activation. Existing regional USD/EUR handling and
SERVICE plan mappings must remain. USD prices still require an explicit commercial
decision; annual Stripe Price mappings and validation for each enabled tier/currency
remain Block E work. No USD amount or provider identifier is inferred here.

Existing paying customers should retain their legacy plan and contractual limits.
An explicit reviewed opt-in/renewal migration must check current usage, currency,
annual terms and provider mapping before any change. Over-limit workspaces retain
records and the ability to complete accepted work. The four-location Test Lab must
not be assigned a two-location Core plan. Quota fixtures should be isolated.

For this repair: validate Local with isolated fixtures, deploy the same code to
Development and Staging through the usual release process, and verify CSV preview,
confirmation/replay and finite capacity with legitimate test subscriptions. Leave
nonlocal bypass disabled. Verify the actual web-process settings separately from
shell settings. No environment is deployed by this change. Roll back the code only
if needed; there is no data migration to reverse and no seeded data to remove.

Blocks B–F must remain separate reviewable changes, including UTC/concurrency tests,
monitoring, approved price configuration, rollout/rollback, and workbook-assumption
financial sensitivity at 2x/3x/5x infrastructure. No financial conclusion or measured
hosting capacity is claimed at this checkpoint.

## Validation

Tests use disposable databases and test mail; no Production data or real provider
calls are required. HTTP/template assertions verify server-rendered labels and
confirmation behavior; desktop/mobile browser interaction QA is not claimed.

| Check | Result |
| --- | --- |
| Client preview/execution and Logistics entitlement tests, SQLite | 68 tests, OK, 3 PostgreSQL concurrency tests skipped |
| Same focused suite, disposable PostgreSQL 14 | 68 tests, OK, including all 3 concurrency tests |
| SERVICE regressions: accounts, businesses, CRM, billings, appointments, notifications | 975 tests, OK, 9 PostgreSQL-only skips |
| Logistics local-bypass, Test Lab foundation, annual Checkout and approval regressions | 114 tests, OK, 2 PostgreSQL-only skips |
| Targeted Test Lab dataset preservation checks | 3 tests, OK: complete foundation snapshot, existing administrator contexts, normal billing metadata and unrelated financial records |
| Extended combined Test Lab dataset run | Incomplete: Python process terminated with SIGSEGV during garbage collection; no full-suite pass claimed |
| Ruff and Black on changed Python files | Passed |
| Django system check, migration drift, `git diff --check` | Passed; no model changes or migrations |

The three real PostgreSQL races cover two imports competing for the last Client
slot, manual creation competing with CSV for that slot, and concurrent execution
of the same unlimited import. The tests also cover numeric/zero/unlimited capacity,
inactive/historical Client exclusion, absent/incompatible/inactive/expired
subscriptions, expiry or limit changes after preview, local exception conditions,
nonlocal isolation, approval holds, UI labels, atomic execution, and retry behavior.
An absent plan cannot normally remain attached to a subscription because the
existing FK is non-null and PROTECT; no fallback plan is fabricated.

Raw focused logs: `/tmp/logistics-block-a-sqlite-final.log` and
`/tmp/logistics-block-a-postgresql-final.log`. SERVICE log:
`/tmp/logistics-block-a-service.log`. Logistics foundation/checkout log:
`/tmp/logistics-block-a-logistics-final.log`. The extended dataset crash trace is
`/tmp/logistics-block-a-dataset-crash.log`; it occurred while executing
`test_missing_and_cross_tenant_ownership_refused` in a combined run that also
included PDF/barcode decoding. Its cause is unconfirmed, and there was no test
summary for that run. The separate preservation tests passed; raw log:
`/tmp/logistics-block-a-dataset-focused.log`. The regression runners use the existing
test-only MD5 password hasher pattern to speed isolated fixtures; real account
password hashes are untouched. The disposable PostgreSQL server is stopped after
its tests finish.

Reproduce the focused SQLite suite from the repository root:

```sh
ENV=local DEBUG=False LOGISTICS_LOCAL_BILLING_BYPASS=False \
  DATABASE_URL=sqlite:///:memory: .venv/bin/python src/manage.py test \
  apps.crm.test_logistics_client_capacity apps.crm.test_client_preview \
  apps.crm.test_client_execution --noinput
```

Use the same test labels with DATABASE_URL pointing to a disposable PostgreSQL
instance whose role can create its own isolated test database for concurrency.
Do not point provider/seed execution commands at a deployment database for this QA.
