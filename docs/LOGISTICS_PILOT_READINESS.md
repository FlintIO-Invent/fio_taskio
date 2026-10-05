# Logistics pilot readiness (Block 11)

## READY

Blocks 1–10 supply application intake and revision-bound approval, private
single-use enrollment, LOGISTICS Business/owner provisioning, pending annual
subscriptions without trial, server-selected Stripe checkout, signed webhook
activation, Logistics onboarding, tenant-owned Clients/Parcels/Events/Shipments,
public tracking, shipment lifecycle/manifests and controlled operational tooling.

The integration test starts at public application submission and reaches payment
activation, onboarding, parcel registration/tracking, shipment completion,
manifest, inspection, deactivation and Stripe-protected purge planning. Provider
API responses are mocked; webhook requests use real signature verification.
Return pages do not activate access. Approval, currency/Price/interval tampering,
identity matching, tenant isolation, public projection/privacy, unavailable-response
equivalence, SERVICE routes/plans/trials and demo/reset safeguards have regression
coverage. Readiness signals never bill, suspend or enforce provisional quotas.

Real PostgreSQL 14 tests cover simultaneous approved conversion, anonymous
same-grant conversion, competing new-account email inserts, one Business and
subscription per conversion, parcel registration/event retries, competing
shipment assignments/departures, assignment versus departure and purge versus an
inflight event. TransactionTestCase fixtures explicitly restore the migration-seeded
offering after database flush; no domain redesign was required by these races.

Performance sanity compares small/growing datasets for dashboard, parcel
list/detail, shipment detail/manifest, public timeline, inspection and usage summaries.
Queries do not grow per row/event. These are sanity checks, not production load
tests; timeline/manifest response size still grows with their event/parcel count.

## CONFIGURE BEFORE PILOT

- Agree a positive annual Logistics price and supported currency/currencies
  (USD/EUR). Configure matching active, licensed annual per-unit Stripe Prices
  and `STRIPE_PRICE_LOGISTICS_YEARLY_USD` and/or `_EUR`. Activate the `logistics`
  plan through its validated Admin form; the seed remains inactive/unpriced.
  Each enrolled currency needs its own mapping; no cross-currency fallback.
- Configure Stripe keys, webhook signing secret and endpoint delivery. All
  existing SERVICE mappings/checks still apply when Stripe is enabled. Verify
  recurring Price details through Admin activation/checkout; static checks do
  not contact Stripe. Keep Logistics Customer Portal disabled.
- Set `LOGISTICS_SUPPORTED_TERRITORIES` explicitly and review the existing
  eligibility thresholds and rule version. They remain approval rules.
- For shared throttling, install `uv sync --no-install-project --extra logistics-cache` (include
  other deployment extras as needed), then configure:

  ```dotenv
  LOGISTICS_DEPLOYMENT_CHECKS_ENABLED=True
  LOGISTICS_TRACKING_CACHE_ALIAS=logistics_tracking
  LOGISTICS_TRACKING_CACHE_BACKEND=django.core.cache.backends.redis.RedisCache
  LOGISTICS_TRACKING_CACHE_LOCATION=redis://<private-cache-host>:6379/1
  LOGISTICS_TRACKING_CACHE_KEY_PREFIX=clarivo-logistics-tracking
  ```

  Use authenticated/TLS cache configuration appropriate to the deployment;
  keep cache URLs/credentials private. The dedicated alias leaves the SERVICE
  default cache unchanged. Memcached backends are also recognized by checks,
  but require their own client dependency. LocMem, file and database caches
  do not establish a shared atomic counter. All workers/dynos must use the same
  cache, prefix and Django SECRET_KEY. Cache failures deny lookups with 429.
- Verify the proxy/server supplies a trustworthy client `REMOTE_ADDR`.
  Forwarded headers are intentionally ignored. An unadjusted proxy peer groups
  customers under one limit. Test different clients and multiple workers; do
  not enable arbitrary forwarded-IP parsing. The limit remains 30 attempts per
  peer/minute and allows bursts across window boundaries.
- Configure normal subscription email delivery, sender address and SMTP/provider
  credentials. Application decision notifications and private enrollment-link
  delivery remain a reviewer responsibility; no automatic application mailer
  is introduced. Enrollment secrets expire after seven days, are single use,
  revision-bound and stored only as digests. Never log request bodies/grants.
- Apply migrations, including `logistics.0005_application_purge_retention`,
  which backfills existing conversion Business IDs. Then run:

  ```sh
  python src/manage.py migrate
  python src/manage.py check
  python src/manage.py check --deploy --tag logistics --database default
  ```

  Pilot checks are opt-in so SERVICE-only deployment checks keep their current
  behavior. Resolve all Logistics errors; reviewer-delivery/proxy warnings
  identify required manual deployment verification. Configure ordinary HTTPS,
  SECRET_KEY, allowed hosts and production settings through the existing flow.

## MINIMUM RETENTION POLICY

The existing controlled `purge_business` remains the only supported tenant purge.
Inactive Business, exact-ID confirmation, reason/reference, cross-tenant checks,
Stripe references, test-financial confirmation, rollback and post-delete checks
remain mandatory. Paid tenants with provider/webhook references remain blocked;
this block introduces no Stripe cleanup or real-customer financial bypass.

After those gates pass, converted LogisticsApplication inputs (including contact
and operational data), immutable decision snapshots and enrollment token history
survive. The protected Business FK is released into `business_id_snapshot` and
grants are revoked. Conversion revision/time and the protected enrolled User FK
remain. Users referenced by application/enrollment history and shared users are
preserved even with eligible-user deletion requested. Ordinary ORM/Admin
Business/User/application deletion remains protected. Purged conversions cannot
enroll or checkout again; email matches cannot recover tenant ownership.

Tenant-owned demo metadata, Clients, ParcelEvents, Parcels and Shipments may be
deleted in the existing dependency-safe order. BusinessDataOperation audit rows
survive with IDs, reason/reference, counts/status/timestamps, without customer
names, emails, grant secrets or provider IDs. Retention release and grant revocation
roll back if purge fails; its failed audit persists. Reversing migration 0005
after a converted-tenant purge is refused to prevent loss of retained identity.
There is no automatic retention expiry or broader compliance framework.

## MANUAL QA

- Submit a real pilot application; confirm identical public receipt for approval
  and review. Review identity privately, test stale revision rejection and deliver
  a fresh grant to the verified applicant through the agreed private channel.
- In Stripe TEST mode only, check the annual Price, no trial, checkout creation,
  successful test payment, endpoint signature/webhook delivery, persisted customer
  and subscription IDs, active workspace access and duplicate webhook replay.
  Test abandonment/expiry, retry and failed-payment recovery. Return URLs alone
  must not activate access. Never use production payment objects for this QA.
- Complete onboarding; create a Client, register/update a Parcel, check private
  fields are absent from public tracking, and verify invalid/inactive equivalence.
- Assign received parcels, depart/arrive/deliver/complete a Shipment and inspect
  its HTML/CSV manifest. Check roles and another tenant's inaccessible IDs.
- Verify Redis connectivity and a common counter across workers with different
  clients through the actual proxy. Review public messages for private data.
- Preview inspection/deactivation/purge and demo reset. Use explicit execution
  only for approved disposable QA tenants; confirm genuine dependents and
  financial/provider references still block destructive operations.

## KNOWN LIMITATIONS / EXTERNAL VERIFICATION

- Real Stripe TEST payment verification could not run here: Stripe is disabled;
  secret key, webhook secret and both Logistics annual Price mappings are absent.
  All provider steps in MANUAL QA remain externally unverified, including actual
  Price objects, hosted checkout/payment, webhook delivery and recovery.
- A deployed shared cache, proxy chain and multi-dyno counter have not been
  exercised here. Static checks and alias/failure regressions cover the local
  configuration boundary; production cache/proxy QA remains required.
- No PWA, offline support, scanner/native mobile, warehouse, customs or external
  API features. Location counts remain application estimates. Customer Portal
  and automated application/enrollment email delivery remain unavailable.

## FINAL AUTOMATED MATRIX

| Verification | Tests | Result | Skips |
| --- | ---: | --- | ---: |
| Six-app SQLite suite | 1,175 | PASS (444.183 s) | 10 PostgreSQL-only concurrency tests |
| Six-app PostgreSQL 14.24 suite | 1,175 | PASS (468.964 s) | 0 |
| Dedicated PostgreSQL enrollment/operations races | 10 | PASS | 0 |
| Final retention/inventory/readiness/tooling checks, SQLite | 66 | PASS | 0 |
| Final retention/inventory/readiness/tooling checks, PostgreSQL | 66 | PASS | 0 |
| Actual migration backfill and refused downgrade, SQLite | 1 | PASS | 0 |
| Actual migration backfill and refused downgrade, PostgreSQL | 1 | PASS | 0 |

The 66-test focused matrices ran after the final session-independent conversion
integrity correction and expanded inspection query check. The separate migration
matrices exercise the actual migration executor in both directions. Dedicated
and focused totals overlap the broad suite; they are not additional unique tests.

Broad command (with the corresponding SQLite/PostgreSQL test database settings):

```sh
uv run --no-sync python src/manage.py test \
  apps.accounts apps.businesses apps.crm apps.appointments apps.billings apps.logistics \
  --verbosity 1
```

Normal Django checks and `makemigrations --check --dry-run` pass on both database
backends. Black/Ruff pass for all 27 changed/new Python files; `git diff --check`
passes. Fresh migrations also apply successfully to the isolated PostgreSQL
cluster. Opt-in deployment checks on that unconfigured database correctly fail
with E001 (Stripe disabled), E003 (missing territories), E006 (local cache), and
E010 (inactive offering), plus email/proxy warnings. They make no provider calls.

PostgreSQL verification used an isolated ephemeral cluster and disposable test
databases; no existing tenant database or production Stripe objects were touched.
External payment/cache/proxy QA remains outstanding as listed above.
