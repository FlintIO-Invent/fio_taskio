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
