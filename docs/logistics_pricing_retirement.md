# Three-tier Logistics pricing retirement

Core, Growth and Scale remain the only choices for new applications and
conversions. Both application and shared Checkout entry points now reject the
retired `logistics` slug, including pending historical subscriptions and session
resumption. Retired pending subscriptions no longer advertise payment buttons;
local entitlements remain intact. Existing authenticated conversion retries still reuse their original
records; they cannot create another legacy payment session.

Tier Price identity comes from the server-controlled mapping and current
subscription/application approval context. Price-level `motionmate_plan_slug`
metadata is ignored. Configured ID, approved EUR amount, active status, annual
interval/count, mode and licensed/per-unit checks remain. Checkout and tier
webhooks remain TEST-only and EUR-only. No Price mapping, activation flag,
capacity, commercial amount or migration is changed. The readiness command checks
only the supported annual EUR tier Price.

Startup and deployment checks no longer require legacy EUR/USD mappings or
legacy display prices. They still require the legacy plan to stay active while
historical subscriptions reference it, preserving local/Test Lab entitlements.
Optional legacy mappings remain recognized for old webhook events and ambiguity
checks. Shared billing policy recognition of legacy is retained for historical
contracts and grace processing; it does not authorize Checkout.

When an old Price has no environment mapping, webhooks can resolve it only from
a locked legacy subscription with exactly matching, nonempty stored Price,
customer and subscription IDs. Existing tenant, metadata, provider, currency,
interval, approval, ordering and deduplication checks still apply. This fallback
never runs for mapped/ambiguous Prices or new tiers. Unbound events remain
retryable; unknown/orphaned contracts are ignored, without tenant creation,
subscription reassignment or tier activation. Incomplete historical bindings
therefore still require operator review or optional mapping repair.

Current Checkout fixtures use Core. Historical tests reconstruct saved
pre-retirement rows directly. Coverage includes metadata-free tier Checkout and
signed webhook activation, rejected legacy sales, missing mappings, legacy
lifecycle/replay, orphan handling, Price reuse isolation, SERVICE regressions and
isolated PostgreSQL concurrency. All Stripe operations in tests are mocked.

Deployment, separately approved tier activation, a fresh fictional payment and
real signed webhook delivery remain operator gates. No Heroku or Stripe changes
are performed by this implementation.

## Validation

- PostgreSQL 18.4: 196 pricing, admission, legacy/tier webhook, approval,
  deployment-check and capacity tests passed, including all ten concurrency
  tests. Database: fresh disposable container with networking disabled and a
  dedicated Unix socket. No existing application database was accessed.
- SERVICE/account regressions: 428 tests passed.
- Final payment-link/entitlement/capacity checks: 22 tests passed.
- Django checks, migration drift, Ruff, Black and whitespace checks passed.
- Supplemental all-app SQLite suite stopped in the slow Test Lab access matrix;
  it is incomplete and is not claimed as a full-suite pass. No failures were
  reported before it was stopped.

Logs: `/tmp/mm-retirement-checks/final-postgres.log`,
`service-regressions.log`, `final-eligibility.log` in the same directory.

## Changed files

- `src/apps/businesses/billing_policy.py`
- `src/apps/businesses/models.py`
- `src/apps/businesses/stripe_checkout.py`
- `src/apps/businesses/stripe_config.py`
- `src/apps/businesses/stripe_webhooks.py`
- `src/apps/businesses/test_logistics_billing.py`
- `src/apps/logistics/billing.py`
- `src/apps/logistics/checks.py`
- `src/apps/logistics/management/commands/check_logistics_checkout.py`
- `src/apps/logistics/stripe_prices.py`
- `src/apps/logistics/test_billing_compatibility.py`
- `src/apps/logistics/test_checkout.py`
- `src/apps/logistics/test_checkout_approval.py`
- `src/apps/logistics/test_readiness.py`
- `src/apps/logistics/test_stripe_prices.py`
- `src/taskio/settings.py`
- `src/templates/logistics/enrollment_complete.html`
- `src/apps/logistics/test_pricing_retirement.py`
- `docs/logistics_pricing_retirement.md`

Development deployment preparation and approval gates are recorded in
[`logistics_pricing_development_release.md`](logistics_pricing_development_release.md).
