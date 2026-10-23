# Block E4: Logistics tier TEST Checkout and webhooks

Audit and reuse: `businesses.stripe_checkout` serializes Logistics entry points
under application → subscription locks, creates/reuses/expires Checkout Sessions,
and delegates activation to webhooks. `businesses.stripe_webhooks` locks the same
application before its subscription, correlates provider identities, checks Price
dimensions, handles event timestamps and queues transition notifications.
The signed HTTP endpoint, event ledger and existing failure/grace/restricted-access
services remain authoritative. E2 approval snapshots and E3 staged Price validation
are reused; no parallel subscription or payment implementation was added.

## Behavior and security

- Core/Growth/Scale are eligible for **Stripe TEST**, annual EUR, one licensed unit,
  no trial. `checkout_enabled` stays false for ordinary/LIVE eligibility;
  `test_checkout_enabled` marks these offerings explicitly. Actual Checkout and
  tier Price resolution require matching TEST keys in every environment, including
  production. Legacy `logistics` retains its existing LIVE/TEST and USD/EUR rules.
- Staged tier configuration remains separate from legacy/SERVICE mappings. Shared
  Price lookup resolves these tiers only in TEST. All three mappings must be present,
  distinct and unused by legacy/SERVICE. Active/full tier capacity configuration and
  exact approved EUR display amounts are rechecked. Provider retrieval verifies E3
  Price activity, tier metadata, currency, licensed annual recurrence and amount.
- Checkout requires the authenticated enrolled owner and current approved/evaluated/
  converted application revision. Its metadata and subscription metadata bind
  application UUID/revision, decision ID, complete tier slug, selected Price,
  business/subscription/owner IDs, annual interval and EUR. The tier retry key hashes
  this binding plus replacement-session identity; legacy/SERVICE keys are unchanged.
- Open sessions are reused only after identity/approval/Price checks. Reapproval or
  configured Price replacement expires old open authorization before replacement.
  Provider success followed by local rollback retries with the same bound key.
- Tier webhook validation requires the signed envelope, payload and provider
  subscription to be TEST, exact complete metadata, current approval and persisted
  Checkout/Price identity. It checks customer/provider subscription identity, one
  licensed unit, valid billing period, exact tier Price/amount/currency/recurrence,
  and no trial. Checkout completion additionally requires the exact stored session,
  client reference and paid status. Invoice events must match customer/subscription
  identity and EUR, then use the retrieved authoritative provider subscription.
- Mismatches and revoked approvals fail before subscription writes. Existing review
  revocation holds remain in force. Strictly older tier state events are acknowledged
  without updating identity, subscription state or grace. E4.2 reconciles distinct
  same-second events through the existing read-only provider subscription retrieval
  under application/subscription locks and repeats validation. Provider read failures
  remain retryable. Tier event completion commits with state/outbox changes in the
  existing ledger; concurrent duplicate IDs cannot reapply transitions.
- Failed initial payment grants no access. Existing paid subscriptions retain the
  shared past-due grace, restricted mode and recovery behavior. No switching or
  Customer Portal capability was added. Generic pending-subscription provisioning
  cannot create or switch tiers; E2 enrollment remains the tier writer.

## TEST activation prerequisites and boundaries

1. Manually prepare all three TEST annual EUR Prices using the
   [E3 setup instructions](logistics_subscription_block_e3.md): Core 1700.00,
   Growth 2300.00, Scale 3000.00. Price metadata `motionmate_plan_slug` must match.
2. Configure the three `STRIPE_PRICE_LOGISTICS_{CORE,GROWTH,SCALE}_YEARLY_EUR`
   variables and matching `pk_test_`/`sk_test_` keys, `STRIPE_ENABLED=true`, the TEST
   webhook signing secret, and existing shared SERVICE/Portal configuration. Run
   `python src/manage.py check_logistics_tier_prices --verify-provider` in the
   explicitly selected TEST environment. Read-only E3 verification itself is not
   payment activation.
3. Explicitly activate the intended plan with complete capacity configuration and
   the matching approved EUR display amount in that selected TEST environment;
   enroll a fresh approved application selecting that tier in EUR. Do not reassign
   Test Lab or legacy subscriptions. Use its existing application Checkout POST.
4. Deliver signed TEST events to the existing Stripe webhook endpoint. Return URLs
   never grant access. Confirm active access only after a valid accepted event.

No provider objects, plans, existing subscriptions or Test Lab data were changed
by implementation. No migration, deployment, environment update or automatic
product/Price creation was performed. All provider behavior in automated tests is
mocked; real sandbox payment, webhook forwarding and dashboard verification remain
manual. LIVE tier billing remains blocked. E5, switching/proration and Portal work
remain outside this block.

## Files and validation

E4 updates `businesses/{billing_policy,stripe_config,stripe_checkout,stripe_webhooks}.py`,
`logistics/{billing,checkout_approval,stripe_prices}.py`, the read-only tier Price
checker message, and existing capacity/E2/E3 tests. It adds
`logistics/test_tier_checkout.py` and this report. There are no E4 migrations.

- Focused tier/E2/E3, legacy Checkout, Logistics billing/capacity and shared Stripe
  configuration: 145 SQLite tests OK, four PostgreSQL-only skips.
- PostgreSQL tier/enrollment suite: 53 tests passed. Final expanded tier Checkout
  rerun: 19 tests passed, including all three new concurrency tests (parallel
  clicks, duplicate signed delivery, and approval revocation racing payment).
- Final shared/tier configuration rerun, including trimmed Price lookup: 27 passed.
- SERVICE accounts/businesses/CRM/billing/appointments/notifications: 1,022 tests
  OK, 17 PostgreSQL-only skips.
- Ruff, Black, Django checks, migration drift and whitespace checks passed.

The configuration-recovery test exposed direct signed-event SDK Prices using
`to_dict()`; both SDK conversion forms are now supported. It passes alongside
initial-payment failure, paid → past-due/grace/restricted/recovery, all three tier
activation/replay, metadata/identity/mode/Price attacks, malformed display prices,
pre-Checkout events, revocation, stale timestamps and retry key checks.

Raw logs: `/tmp/logistics-e4-focused-final.log`,
`/tmp/logistics-e4-postgresql.log`,
`/tmp/logistics-e4-postgresql-final-verified.log`,
`/tmp/logistics-e4-config-final.log`, `/tmp/logistics-e4-service.log`.
Only disposable test databases were used; the separate PostgreSQL cluster was
stopped after validation. No real Stripe payment or provider readiness is claimed.
