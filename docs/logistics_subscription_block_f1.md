# F1: retire legacy Logistics admission

New Logistics applications require an explicit `logistics-core`,
`logistics-growth` or `logistics-scale` selection. Public and administrative
forms list only active, fully configured capacity tiers, with a required empty
placeholder. The shared admission helper also guards model creation, approval,
grant issuance and conversion. Missing, legacy, unknown, inactive, incomplete
and wrong-family selections fail closed. Bulk application creation is rejected
because it bypasses the existing evaluation/revision workflow.

Existing unconverted legacy applications cannot receive approval, a new grant,
or enrollment using an old grant. Selecting a current tier through model/form
save increments the revision and invokes the existing evaluator, revoking old
grants. Strict-policy review still requires approval of that new revision;
pilot automatic approval remains governed by its existing setting. Historical
decisions remain intact. Decline/withdrawal of historical applications remains
available.

Already-converted legacy retries retain their existing authenticated-owner,
grant, expiry, revision and subscription checks. Historical approval snapshots
without a tier key still mean `logistics`. Existing legacy rows may retain their
slug on unrelated edits; changing an enrolled tier remains prohibited.

No migration or historical default changes are needed. Plan activation flags,
legacy unlimited allowances, Business 166, subscriptions, financial records,
Test Lab tooling, Stripe mappings, webhooks and SERVICE paths are unchanged.
Test fixtures now select current tiers explicitly, or reconstruct historical
legacy records in disposable test databases for compatibility checks.

F2 prerequisites: resolve the previously audited legacy/Core Price overlap and
provider-subscription ownership, design retirement-aware legacy configuration
checks and correct tier administration activation validation. No F2 behavior is
implemented here. All inactive tiers remain unavailable until separately approved
activation; signed Core TEST delivery still requires verification.

Changed implementation: `src/apps/logistics/{tier_selection,forms,models,services,
enrollment}.py`. Added `test_registration_retirement.py` and
`registration_test_support.py`; updated current-tier and historical fixtures in
`tests.py`, `test_enrollment.py`, `test_direct_signup.py`, `test_tier_enrollment.py`,
`test_checkout.py`, `test_tier_checkout.py`, `test_classification.py`,
`test_concurrency.py`, `test_operations.py`, `test_pilot_policy.py`,
`test_local_billing_bypass.py`, `test_locations.py`, `test_location_migrations.py`,
`test_retention_migration.py` and `apps/businesses/test_logistics_billing.py`.

Focused validation used only disposable in-memory SQLite databases:

- Admission/enrollment/signup/pilot: 80 tests, 77 passed, three PostgreSQL-only skips.
- Application/classification and legacy/tier billing compatibility: 141 passed.
- SERVICE registration: four passed.
- Additional Checkout, Test Lab and financial-preservation checks: six passed
  (two repeat compatibility cases after the final fixture adjustment).
- Ruff, Black, whitespace checks and Django checks passed. A database-blocked
  migration-state comparison found no changes. PostgreSQL concurrency and broad
  suites were not run. Provider behavior was mocked; no external Stripe calls,
  existing database writes, configuration changes or deployment occurred.
