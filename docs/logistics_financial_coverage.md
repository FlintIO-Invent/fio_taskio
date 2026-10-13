# Logistics financial coverage

Logistics uses the existing `LogisticsCharge`, `Invoice`, `InvoiceLine`, shared Invoice services and centralized financial permissions. SERVICE Invoice behavior remains unchanged. There is no separate payment ledger or billing system.

## Additive schema and migration

Apply the three migrations together through Django's dependency graph:

1. `billings.0011_financial_coverage_snapshots` adds nullable Invoice currency, tax rate and monetary-seal timestamps, a legacy flag, and a nullable `InvoiceLine.charge_source` link. This link allows multiple retained Invoice lines for a charge across cancellation/reissue.
2. `logistics.0020_financial_coverage_snapshots` adds nullable charge identity/currency/coverage/void timestamps, occurrence and reason references, a nullable one-to-one correction predecessor, and `LogisticsChargeParcel`. The auxiliary table stores exact covered Parcel IDs, with unique `(charge, parcel)` membership. A conditional unique constraint prevents two active charges with the same business/logical identity.
3. `logistics.0021_backfill_financial_coverage` preserves original Invoice amounts, lines, statuses and references. It captures the currently observable currency and the effective tax percentage implied by saved issued amounts, marking these as legacy observations. Valid direct charges receive their one-Parcel coverage. Existing original line bindings receive their source links. Unambiguous logical identities are populated; historical duplicates retain NULL identities. SERVICE snapshot fields remain empty.

Historical Shipment membership is deliberately unknown: today's cargo cannot establish which Parcels were billed in the past. The migration never infers it. Nullable fields remain supported for that history; new service-created charges require complete snapshots.

Normal charge/coverage writes go through the existing domain services. Covered endpoints and sealed membership are immutable. Charge-linked Invoice lines and Invoices cannot be deleted through normal model/UI paths. The source FK uses `SET_NULL` solely so the existing gated tenant purge can delete Charges before Invoices without an FK cycle. Normal Charge deletion remains prohibited. Inventory, purge, demo reset and Test Lab ownership checks include the new relationships; Test Lab reset validates exact recorded edge IDs and Parcel IDs rather than accepting arbitrary dependents.

## Applicability and totals

- A direct charge covers exactly its Parcel. A Shipment charge freezes all current Parcels at charge creation, before Invoice generation. Shipment freight requires nonempty cargo belonging to one Client and Business.
- Invoice generation and replay use this frozen membership. Existing operational assignment/removal rules remain authoritative, but moving a Parcel never transfers or removes its financial obligation. Newly added cargo does not inherit previously frozen freight. Issuance/correction also rejects a Shipment whose current billing Client relationships have become ambiguous.
- Parcel coverage resolves direct charges and frozen Shipment coverage together. Bulk coverage deduplicates by charge ID. Shipment coverage includes its saved freight and charges applicable to its current cargo, with each charge counted once.
- A shared freight amount is one shared obligation, not a per-Parcel allocation. For example, freight of USD 150 covering two Parcels plus USD 25 handling for one yields USD 175 in the bulk result. Adding the two individual Parcel projections would double-count shared freight; use the bulk service.
- Totals are grouped by saved currency, before tax. Invoice tax and total remain at Invoice level. Different currencies are never added or converted. Dashboard and billing displays retain saved currency labels.
- Multiple Parcels can share an Invoice, and a Parcel can have charges on several Invoices. A charge has at most one active Invoice binding, while its cancelled Invoice lines remain retained history.
- Missing cargo proof, legacy currency/tax, ambiguous identities, corrupt relationships, multiple active bindings, or active Parcel/Shipment Invoice lines without a source charge prevent financial clearance. Unknown historical Shipment lines conservatively require review for the affected Client. Empty or void-only finances never imply free delivery or payment clearance.

## Duplicate, cancellation and correction rules

Logical identity consists of target kind/ID, saved Service ID (or whitespace/case-normalized custom description), and an optional stable occurrence reference. Price, quantity and random retry tokens are not identity. Same-purpose charges with the same occurrence cannot overlap covered Parcels across direct and Shipment targets. An original retry token returns its original snapshots; a fresh token cannot create a second logical obligation. A genuinely separate job/leg uses a distinct stable occurrence reference. Free-text semantic equivalence and operational leg discovery are not inferred automatically.

Cancellation preserves Invoice amounts and line history and leaves the charge outstanding. The existing charge-to-Invoice form can reissue it; the original canonical binding remains unchanged, and the new line receives its own source link. Concurrent reissues return one active Invoice. Reissue preserves saved currency and the original tax rate; incompatible currencies or reissue rates must use separate Invoices.

`void_charge` requires an accounting role, a reason/evidence reference and cancellation of every linked Invoice. Voiding retires an obligation permanently. It cannot be silently recreated through another token. `correct_charge` atomically voids the predecessor and creates one auditable successor with the same tenant, Client, target, currency and exact covered Parcels. Invalid corrections roll back both operations. A retry must match the saved successor; corrections cannot fork. The old charge and all Invoice history remain available.

PAID Invoices cannot be cancelled, voided or corrected through these services. Provider refunds, credit notes and negative adjustments need a separate approved accounting workflow and are not introduced here.

## Monetary history

New Logistics Invoices capture currency and tax rate at draft creation and seal monetary fields on issuance or cancellation. Shared recalculation uses the saved rate and is prohibited after sealing. Issued totals, line values, currency and rate cannot be changed by workspace default/catalog changes. HTML, PDF, list/edit previews, reissue choices, WhatsApp amounts and dashboard groups use the saved currency. SERVICE retains its existing workspace defaults and billing behavior.

Legacy observations are explicitly labelled. `record_legacy_charge_coverage` requires accounting evidence and an exact same-tenant/Client Parcel list; it never consults current cargo as historical proof. `confirm_legacy_charge_currency` and `confirm_legacy_invoice_snapshot` require evidence and confirmation of the observed saved values. Invoice confirmation verifies saved tax arithmetic and totals and changes only the legacy flag. Conflicting documentary currency, unreconciling effective tax, and ambiguous historical duplicate identities require manual reconciliation; these services never rewrite historical amounts. Extremely large effective rates outside the snapshot field's precision remain unconfirmed until reconciled.

## Permissions and reusable integration services

| Role/context | Financial reads | Financial writes |
| --- | --- | --- |
| OWNER / ADMIN | Authorized business-wide Invoice and charge coverage | Existing Invoice management, charges, reissue, void/correction and legacy confirmation |
| ACCOUNTANT | Existing accounting scope | Accounting operations above; Invoice deletion retains its existing OWNER/ADMIN restriction |
| Location STAFF | Accessible Parcel coverage; only complete accessible Parcel-only Invoices | Parcel charges, generation/append and allowed status changes; all affected Parcels must be operable at the active reviewed work location |
| Read-only assigned STAFF | Assigned Parcel read scope and bounded clearance | None |
| Unassigned/unreviewed STAFF | None | None |
| VIEWER | Existing authorized read scope | None |

Active membership/user, tenant and subscription/module checks still apply. Shipment finance, cancellation/correction and generic manual Invoice management remain accounting operations. Every draft append revalidates all existing lines and covered relationships, preventing an accessible charge from granting access to an inaccessible Invoice. Direct service writes lock the Business and persisted actor membership and check current `can_operate` grants; read visibility alone cannot authorize a write.

`financial_coverage.py` exports `coverage_for_parcel`, `coverage_for_parcels`, `coverage_for_shipment` and a narrow `clearance_for_parcel`. Detailed projections honor Invoice visibility and withhold restricted Shipment/shared Invoice details from STAFF. The clearance service evaluates applicable shared freight internally but returns only the accessible Parcel ID, completeness, clearance and generic issues. It exposes no amounts, Invoice IDs or other cargo IDs, and does not grant Invoice access or mutation.

Clearance means every known active charge has one PAID Invoice and all evidence/integrity checks pass. Manual PAID status is not proof of a provider receipt. Future payment/scanner integrations must recheck this result inside the existing Business write transaction together with operational work-location permission before acting. These read services neither collect payments nor release cargo.

## Verification

Final local evidence is recorded below. Suites overlap and should not be summed as unique tests.

- PostgreSQL: 163 Invoice/charge coverage, permission, shared SERVICE billing, dashboard and real concurrency regressions passed, including 19 concurrency tests (6 new coverage races). The concurrency tests cover fresh-token duplicates, direct/Shipment overlap, frozen cargo during assignment/issuance, competing reissues/corrections, and existing authorization races. Log: `/tmp/mm-coverage-finish-postgres-latest.log`.
- SQLite: 212 expanded billing, location/tenant permissions, SERVICE, demo reset, inventory and purge regressions passed. Log: `/tmp/mm-coverage-finish-regressions-latest.log`.
- Final shared billing/SERVICE and coverage rerun after preserving the original SERVICE status-error handling: 101 tests passed. Log: `/tmp/mm-coverage-final-service.log`.
- PostgreSQL historical migrations: 4 tests passed, including financial backfill, historical duplicates, unknown Shipment cargo, original amounts and SERVICE preservation. Log: `/tmp/mm-coverage-migrations.log`.
- PostgreSQL Test Lab/dataset/verified demo and concurrency: 29 tests passed. Log: `/tmp/mm-coverage-final-lab.log`.
- Chromium: 2 browser interaction tests passed within a 55-test PostgreSQL browser/coverage/billing run, exercising issuance/protected-line and shared freight/reissue at 390 and 1440 pixels, including saved currency/tax after workspace defaults change. Log: `/tmp/mm-coverage-final-browser.log`; screenshots: `/tmp/mm-finance-browser/` and `/tmp/mm-coverage-browser/`.
- Django system checks, migration drift, changed-file Ruff/Black and `git diff --check` passed.

PostgreSQL runs use a disposable local PostgreSQL 14.24 cluster. Test settings use a test-only MD5 password hasher for speed. No deployed tenant, provider, subscription or assignment data is changed. Deployment migration execution, documentary historical reconciliation and real payment-provider integration remain outside this verification. Trusted raw ORM/SQL maintenance retains the project's existing bypass capabilities; these changes do not introduce database row-level security.
