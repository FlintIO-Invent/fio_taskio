# F2A: Logistics billing compatibility

Builds on F1; no registration policy, subscription, entitlement or provider
resource changes. Legacy `logistics` remains a recognized annual offering with
its existing unlimited allowances, recovery, approval reconciliation, webhook
ledger and grace rules. No historical defaults or migrations change.

## Operation-specific validation

- Opt-in database deployment checks require an active legacy plan only when
  legacy subscriptions reference it. They require annual Price/display mappings
  for currencies used by persisted legacy Stripe subscriptions, including
  cancelled contracts and historical blank-provider rows with provider IDs.
  Local/Test Lab subscriptions need their active legacy plan but no Stripe Prices.
- Actual legacy Checkout/recovery, activation and webhook processing still fail
  closed on missing, invalid or ambiguous mappings. A missing legacy Price mapping
  during webhook processing records a retryable failure without modifying subscription state; the same
  event ID can succeed after configuration repair.
- Each tier's administration/activation validates its own annual EUR Price,
  approved amount, active plan, LOGISTICS family, complete capacities and TEST
  Checkout eligibility. The admin candidate includes all submitted fields.
  Missing legacy/USD or inactive sibling tier Price settings are not prerequisites.
- Selected tier resolution checks collisions across all configured tier and
  SERVICE/legacy IDs. Reverse lookup also rejects overlaps instead of preferring
  the legacy mapping. A legacy local subscription cannot be reclassified as Core
  when only a Core mapping remains; existing local-plan/metadata checks reject it.
- The E3 `check_logistics_tier_prices --verify-provider` audit still requires all
  three EUR mappings. Shared SERVICE requirements and malformed shared mapping
  checks remain intact. Provider verification remains read-only; LIVE/USD tier
  Checkout and switching remain disabled.
- Active tiers receive a static deployment configuration check (`logistics.E016`),
  without provider calls. Existing signature, tenant, approval, locking, event-ID,
  timestamp and same-second reconciliation mechanisms are unchanged.

## Files and validation

Changed `apps/businesses/{admin,stripe_config}.py` and
`apps/logistics/{billing,checks,stripe_prices}.py`; added
`apps/logistics/test_billing_compatibility.py`, updated
`apps/logistics/test_readiness.py`, and added this document.

Focused SQLite runs: 28 configuration/activation/deployment tests passed (one
PostgreSQL-only case skipped), plus 163 legacy/tier/F1/SERVICE billing tests passed.
The strengthened legacy/Core identity case also passed separately.

PostgreSQL 18.4: nine concurrency tests passed, including same-second distinct
events, duplicate deliveries, stale cancellation ordering, checkout serialization,
and approval-revocation races. The new race test ran without legacy mappings.
The database was empty and disposable, in a network-isolated Docker container
with no published ports; it was removed after testing.

Ruff, Black, whitespace and Django checks passed. A database-blocked migration
state comparison returned no changes. No existing database was accessed, no
external Stripe calls occurred, and no Heroku/configuration/deployment changes
were made. Logs: `/tmp/mm-f2a-config-final.log`, `/tmp/mm-f2a-billing-final.log`,
`/tmp/mm-f2a-pg-tests.log`, `/tmp/mm-f2a-identity-final.log`.

## Remaining operator gates

Previously identified provider subscription ownership and legacy/Core Price reuse
still need explicit reconciliation and distinct, verified mappings. F2A neither
reassigns existing subscriptions nor invents replacement Prices. Fresh signed Core
TEST delivery and separately approved tier activation remain external release
gates. Current deployed configuration/provider state was not audited in this block.

## F3A review and commit record (2026-10-15)

F1 is already committed as `cfbd5cc9cd43eae010ab04332ef0ed3e10e76108`;
F2A is already committed as `31b91d00109a1850fa4aa6201f8817ceb66cd187`.
Both were present on `feature/mm-testing-phase` and its origin tracking ref before
this review. Their combined change from `c9c2adc` contains 31 implementation,
test and documentation files. This review preserves those commits.

The reviewed admission paths reject missing, legacy and forged selections in
public/admin forms, model creation, approval and new enrollment. Unconverted
legacy applications require a current tier and a new evaluated revision;
authenticated converted legacy retries retain their historical approval evidence.
Legacy entitlements, recovery and grace behavior remain supported. Tier admin
validation includes submitted capacities, family and Checkout eligibility, and
verifies only the selected tier's annual EUR Price. Ambiguous mappings fail closed.
SERVICE registration and billing retain their existing policy and mappings.

The existing final test logs above were inspected: 28 F2A configuration tests
passed with one PostgreSQL-only skip, 163 billing tests passed, nine PostgreSQL
concurrency tests passed, and the strengthened identity test passed. F1 admission,
compatibility, SERVICE registration and preservation logs also passed as recorded
in the F1 document. No tests were rerun during F3A. A fresh comparison of Django
model state against the migration graph found no drift, with database connections
blocked. Diff whitespace and added-line secret checks passed; no migrations,
configuration files, generated files or temporary artifacts are included.

The separate F2C configuration procedure completed on Development v67; F1/F2A
code has not been deployed there. Deployment requires separate approval, a fresh
target/configuration and zero-pending-migration check before the existing release
hook, and preservation checks for Business 166 and legacy/SERVICE subscriptions.
The previously observed native GC crash remains a monitored runtime risk; this
review does not establish that it is resolved. Tier activation remains separately
approved work, followed by fresh fictional Core TEST Checkout and signed webhook
verification. LIVE/USD tier Checkout remains disabled.
