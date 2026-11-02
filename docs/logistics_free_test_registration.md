# Logistics free-test registration

Core, Growth and Scale use the existing private Services free-test endpoint:

```text
<BASE_URL>/accounts/free-test/logistics-core/<CORE_SECRET>/
<BASE_URL>/accounts/free-test/logistics-growth/<GROWTH_SECRET>/
<BASE_URL>/accounts/free-test/logistics-scale/<SCALE_SECRET>/
```

## Readiness

Each exact `ClarivoPlan` row must already exist, have family `LOGISTICS`, be active,
and have non-null values for every field in `LOGISTICS_TIER_CAPACITY_FIELDS`.
Missing, inactive, wrong-family or incomplete tiers reject both GET and POST
before creating registration records. The migrations seed these tiers inactive;
this change does not activate or rewrite any plan, capacity, price or Stripe mapping.

Normal Logistics plan activation and its Stripe validation remain unchanged.
The existing Django Admin activation path validates configured Stripe TEST prices.
An unavailable tier is a separate readiness dependency, not permission to bypass
activation or Stripe validation. Do not use database updates to circumvent activation.

## Configure and construct links

These are explicit operator steps for a separately authorized environment. No
configuration is applied by installing the code or copying this document.

1. Generate three independent URL-safe secrets in a private terminal, running
   this existing standard-library command once for each tier:

   ```bash
   .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```

2. Store them in the intended environment's secret configuration. Local settings
   can use the repository-root ignored `.env`; exported variables take precedence.

   ```dotenv
   FREE_TEST_REGISTRATION_ENABLED=True
   FREE_TEST_LOGISTICS_CORE_TOKEN=<CORE_SECRET>
   FREE_TEST_LOGISTICS_GROWTH_TOKEN=<GROWTH_SECRET>
   FREE_TEST_LOGISTICS_SCALE_TOKEN=<SCALE_SECRET>
   ```

   The shared flag also controls Services free-test links. All new tokens default
   empty; a tier with an empty token is unavailable. Existing Services tokens are
   independent and remain unchanged.

3. Reload the application's configuration using the environment's normal restart
   procedure, then substitute the public application base URL and corresponding
   secret in the three URL templates above. Share links privately. There is no
   dedicated Logistics/free-test link-generation management command.

4. The recipient completes the existing business registration form with a new
   account email and valid password. The tier and Logistics vertical are determined
   by the validated link; a submitted different tier or vertical is rejected.

## Result and lifecycle

Registration atomically creates the user, `LOGISTICS` business, `LogisticsProfile`
with its normal defaults, owner membership, user profile and subscription. The
existing success path logs in the owner and selects the current business session.
Location review/operations permissions retain their normal defaults.

The exact tier subscription is `ACTIVE`, `FREE_TEST`, `LOCAL`, with
`billing_interval=yearly`. There are no Stripe identifiers, trial dates or access
deadlines. Yearly is a compatibility marker; it does not limit access to one year.
Existing tier features, capacities, quota enforcement and free-test restrictions
apply. Owners cannot change tiers through the subscription form. Checkout is not
started; Logistics Customer Portal and payment recovery remain unavailable.

Links are reusable across new accounts and have no time-based expiry. To stop new
registrations, disable the shared flag or clear the tier token. To rotate one link,
replace only its token and reload configuration. Existing accounts remain unchanged.
Deactivating the business/plan or manually changing its subscription still affects
access under the existing access policy.

Any separately sent Stripe payment link remains separate from account conversion.
An administrator must explicitly review and update the account later; collecting
payment does not automatically convert this local free subscription. No agreements,
installments, renewals or expiry automation are introduced.

## Local validation (2026-11-02)

- A fresh disposable PostgreSQL 14 run passed **336 tests**, including all **15
  new tests**. Coverage includes Services/Beta registration, password/account
  protections, Logistics provisioning, all tier capacities, actual client quota
  enforcement, link reuse/rotation/disabling, tampering/unavailable plans,
  transactional rollback, access after 800 days, reconciliation, billing
  restrictions, ordinary enrollment/Checkout/webhooks, and PostgreSQL concurrency.
  External Stripe HTTP was prohibited by a mock during the regression runs.
- Ruff, Black, `manage.py check`, `makemigrations --check --dry-run`, and
  `git diff --check` passed. No schema migration is needed.
- An expanded 390-test run was not green: 17 errors and one failure. Portal
  fixtures create staff without an accessible subscription; two Test Lab fixtures
  violate current subscription/transport rules; an onboarding scope guard rejects
  an already-existing invoice-payment migration. Representative cases reproduce
  on untouched HEAD (three errors and one failure across five tests).
- The existing `LogisticsCapacityMigrationTests` followed by
  `PlanFamilyMigrationTests` also reproduces a restoration error on untouched
  HEAD: the guarded Services allowance migration finds its canonical plan rows
  missing after a preceding transaction test flush. In the expanded run, this
  left CRM columns absent and caused later concurrency errors. The passing
  336-test matrix excludes these migration round-trip cases and the unrelated
  failing fixture/scope cases; those tests were not modified.
- A separate read-only transaction against this checkout's configured loopback
  `taskio_database_dev` found all three tiers in family `LOGISTICS`, with complete
  capacities, but **inactive**. These remain readiness blockers. This observation
  does not establish deployed or currently serving-process configuration. No
  application records, real secrets, activation settings or Stripe resources
  were changed.
