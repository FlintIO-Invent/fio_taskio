# Block E2: Logistics tier enrollment

Scope is application selection through pending annual subscription provisioning.
Writer audit: `LogisticsApplication.save` owns material revisions and reevaluation;
`services._record_decision` records approval and revokes enrollment/checkout grants;
`enrollment` owns reviewer grants and both secure and pilot signup conversion paths.
The public signup view reuses session applications only for identical material inputs.
Subscription provisioning previously hardcoded `logistics`. Checkout approval and
the Logistics billing service validate the converted application; shared billing
policy already disables checkout for all three new tiers.

The existing application form now offers explicitly active, completely configured
Core/Growth/Scale plans, preserving complete hyphenated slugs. Missing selection
retains legacy enrollment. Model/service validation rejects unknown, SERVICE,
inactive and incomplete tier configurations. No plan activation is performed.
New tiers remain staged/inactive until deliberately configured elsewhere.

The selected slug is a material application input and part of immutable decision
inputs. Changes before conversion increment revision, reevaluate eligibility and
revoke old grants. Review, grant issuance and conversion recheck configuration.
Grants snapshot the selected slug; conversion requires matching approved revision,
decision inputs and grant identity. Posted enrollment tier/plan fields have no
authority. Converted application tier changes are rejected; switching is excluded.

Conversion uses the existing atomic enrollment service and creates a pending,
annual, trial-free subscription with the selected existing plan FK. Authenticated
retries return that same subscription and reject tier/billing dimension drift;
rollback leaves the grant available for retry. Approval metadata preserves the
selected tier for future Checkout binding. No provider request or Price mapping is
added; all new tier checkout remains disabled by existing policy and admission gates.

Migration `logistics.0025_application_tier_selection` adds application and grant
slug fields with `logistics` defaults, preserving historical legacy records without
changing plan, subscription, price, allowance or Test Lab data. Old legacy decision
snapshots that lack a tier key continue to mean `logistics`. Only disposable test
databases are migrated during validation; no deployed database/configuration changes.

E3 prerequisites: explicitly reviewed tier activation and annual currency/display
pricing; verified environment-specific Stripe Price mappings; extend the remaining
legacy-only Checkout admission/price gates together with provider metadata,
idempotency and webhook approval reconciliation; test those paths before enabling
any payment request. Tier switching, proration and Customer Portal are excluded.

Validation on disposable databases:

- Focused application/enrollment/Checkout/capacity suite: PostgreSQL 135 tests,
  all passed, including three enrollment concurrency tests. The final E2-only
  PostgreSQL rerun passed 11 tests after the approval lock-order adjustment.
- SQLite focused suite: 133 tests passed with two PostgreSQL-only skips; expanded
  E2-only suite: 11 tests passed with one PostgreSQL-only skip.
- SERVICE regression suite (accounts, businesses, CRM, billing, appointments,
  notifications): 1,022 tests passed with 17 PostgreSQL-only skips.
- Ruff, Black, Django checks, migration drift and whitespace checks passed.

Logs: `/tmp/logistics-e2-focused.log`, `/tmp/logistics-e2-new-final.log`,
`/tmp/logistics-e2-postgresql.log`,
`/tmp/logistics-e2-postgresql-final-verified.log`, `/tmp/logistics-e2-service.log`.
The isolated PostgreSQL cluster was stopped after testing. Provider behavior was
mocked; no payment/provider readiness or desktop/mobile browser QA is claimed.
