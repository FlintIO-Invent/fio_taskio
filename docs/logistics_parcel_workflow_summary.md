# Logistics Parcel workflow summaries

Block 04 uses the existing Parcel, ParcelEvent, Shipment, LogisticsCharge,
LogisticsChargeParcel, Invoice, InvoiceLine and InvoicePayment records. It adds no
models, migrations, credit approvals, Parcel status flags or payment copies.
Blocks 01–03 remain the financial foundation; SERVICE billing uses its existing
views, transitions and services.

## Resolver contract

```python
from apps.logistics.workflow_summary import (
    resolve_parcel_workflow, resolve_parcel_workflows,
)

summary = resolve_parcel_workflow(business=business, actor=user, parcel=parcel_id)
batch = resolve_parcel_workflows(
    business=business, actor=user, parcel_ids=parcel_ids,
    include_history=False,  # List/dashboard use this compact projection.
)
```

Both methods reread persisted authorization and records. A supplied model instance
is only an ID input, never trusted for its status or associations. All requested IDs
must belong to the active LOGISTICS workspace and be readable by the actor; one
inaccessible ID denies the entire batch. Inputs deduplicate and sort by Parcel ID;
a batch accepts at most 100 positive IDs. No partial unauthorized projection is
returned. An empty batch still checks workspace/module access.

The batch has `contract_version=1`, `as_of`, `summaries`, `by_parcel_id` and
`financial_totals`. Each immutable summary wrapper contains:

| Field | Meaning |
| --- | --- |
| `parcel_id`, `tracking_code`, `internal_reference` | Internal Parcel identity |
| `operational` | Persisted state/label, evidence completeness, owned origin/destination/current/next/work site; restricted Shipment indicator |
| `shipment` | Current accessible Shipment ID, reference, state and transport mode, or `None` |
| `financial` | Visibility, state, clearance, applicable charges, accessible Invoice references, currency totals and explicit balance scope |
| `completed_steps` | Steps supported by actual events, financial records, or current derived settlement; settlement has no invented completion timestamp |
| `outstanding_tasks` | Unfinished operational work and financial/evidence review |
| `candidate_actions` | Potential lifecycle or accounting steps, independent of execution rights |
| `executable_actions` | Read-time authorized subset; never a capability token |
| `history` | Chronological source records with source ID, timestamp, actor and location where recorded |
| `issues`, `as_of` | Reconstruction gaps and observation time |

`to_dict()` returns native Decimal and timezone-aware datetime values. API consumers
must serialize deliberately (money as decimal strings). Summaries and attached
`parcel.workflow_summary` attributes are request-local projections, never saved.

## Financial coverage and clearance

Direct charges and frozen Shipment freight membership use the shared coverage
validators. Current Shipment assignment does not redefine a saved charge's billed
Parcels. Removal, reassignment and newly added cargo cannot silently move financial
obligations. Cancelled Invoice bindings and voided/corrected charges remain in
history; only non-void charges with an active, valid binding contribute obligations.

Invoice currency, tax and money are the saved billing basis. The existing receipt
ledger calculates net verified payment after refunds/reversals. Invoice status alone
cannot prove payment, and legacy manually marked PAID records remain unverified.

| State | Required evidence |
| --- | --- |
| `PAID` | Every proven active obligation invoiced and settled by valid ledger evidence (including a valid issued zero-total basis) |
| `PARTIAL` | Proven invoiced obligations with positive net payment but remaining balance, or a mixture of settled and unsettled obligations |
| `UNPAID` | Valid invoiced obligations with no verified net payment; an unpaid draft remains unpaid |
| `UNINVOICED` | At least one proven active charge has no active Invoice binding |
| `UNKNOWN` | Missing obligations, ambiguous/malformed coverage, unlinked financial history, inconsistent snapshots, legacy paid evidence, or required missing credit evidence |
| `CREDIT_APPROVED` | Reserved; never returned in this block |

Missing/ambiguous evidence takes precedence (`UNKNOWN`), followed by unbilled work
(`UNINVOICED`), then ledger settlement. `clearance.complete` describes whether the
financial evidence is reconstructable; `clearance.cleared` requires `PAID` now.
`UNKNOWN` is always uncleared. No obligation is not proof of a free Parcel.

`require_credit_evidence=True` is an optional stricter read condition. With no
credit-approval source it returns UNKNOWN/uncleared even when payment evidence
otherwise exists. Notes, Client type, Invoice status, audit messages and user role
never establish approved credit. Block 06 will implement creation, authorization,
expiry, revocation and auditing; this block introduces none of those records.

Shared freight appears once per related Parcel, identified by the same charge ID.
Shared Invoice payment and outstanding balances remain **full Invoice balances**,
not estimated per-Parcel allocations. Per-Parcel amounts must not be summed across
a list. `batch.financial_totals` deduplicates charge and Invoice IDs and keeps
currencies separate. Charge totals are pre-tax; Invoice outstanding includes saved
tax. Cancelled and unverified Invoice evidence is excluded from verified aggregate
payment/outstanding totals. An UNKNOWN projection may therefore have incomplete
aggregate evidence; consumers must check clearance before treating totals as final.
All charge sources on a shared Invoice are validated, including sources outside
the requested Parcel batch. Missing sibling coverage cannot produce clearance.
An authorized direct InvoiceLine reference survives a missing charge link, with
its recorded ledger balance available for review. Unlinked evidence cannot clear
the Parcel. Current Shipment membership never establishes a missing historical
Invoice allocation.

## Access projection

| Actor | Journey access | Financial projection | Executable actions |
| --- | --- | --- | --- |
| OWNER / ADMIN | Existing authorized operational scope | Detailed authorized related accounting records | Existing module/site policy plus evidence checks |
| ACCOUNTANT | Existing assigned operational Parcel scope | Existing authorized accounting scope | Financial permissions; operational actions still require operational role/grant |
| Location STAFF | Only accessible Parcels | Clearance only: complete/cleared and generic review message | Existing scoped charge/Invoice entry at an active work site with `can_operate`; no private Invoice or receipt links |
| Unassigned STAFF | Denied | Denied | None |
| VIEWER | Existing readable operational scope | Existing authorized read-only billing scope | None |
| Anonymous / other tenant / SERVICE resolver call | Denied | Denied | None |

Staff financial summaries have no charge/Invoice IDs, descriptions, currencies, amounts,
receipt references, payment actors or financial history. Parcel detail hides its
older detailed billing panel for this projection. Existing explicit Invoice view
permissions remain governed by the shared Invoice policy. Anonymous public tracking
continues using its separate sanitized DTO and never invokes this resolver.

## Operational consumers and history

Parcel detail, list, dashboard attention/recent-delivery records and authenticated
scan use the resolver. The UI separates operational state from financial clearance.
The scan action adapter and Parcel update form recheck new departure/delivery under
the existing Business/member locks. Exact event replay still goes through the
existing idempotent event service; it does not execute movement again. A refund
in transport changes clearance immediately without rewriting operational status.

Executability is advisory. Other direct operational/Shipment command callers retain
their existing lifecycle policy and must integrate a fresh summary under the domain
locks when they need these new clearance checks. No automatic departure, delivery,
repair, payment, reissue or credit approval is performed by resolution.

History combines actual creation/events, accessible persisted Shipment assignment,
removal and transport events, charge creation/voiding, InvoiceLine bindings, Invoice
creation/audits and receipt adjustments. Equal timestamps sort by fixed source order,
source ID and revision. Old actor names are retained in Shipment audit snapshots;
missing actors remain unknown. Missing events, malformed timestamps or unowned
location attribution are flagged rather than repaired or invented. `Invoice.updated_at`
is not presented as an invented status-change or payment timestamp.

## Performance and consistency

Bulk related loads, cached shared validators and preloaded site policy keep query
count bounded as requested Parcel count increases. List pages resolve 50 records
once; dashboard lists share one batch. `include_history=False` skips the accounting
history and former-Shipment JSON search. The automated 1-versus-20 shared freight
fixture measured 50 queries for both 1 and 20 Parcels and checks flat query growth
(at most two extra queries and fewer than 60 total),
no INSERT/UPDATE/DELETE and deduplicated ledger totals.

Standalone PostgreSQL calls run in a repeatable-read, read-only transaction. Calls
inside an existing transaction inherit that caller's isolation; mutating UI adapters
hold the same Business/member locks as supported financial writes and reread evidence.
The `as_of` value records observation start, not a promise that the data remains current.

Detailed former-Shipment history uses a tenant-filtered JSON text search, which may
scan a large tenant's Shipment history; no new index or history table is introduced.
Batch count is bounded, but an Invoice or Shipment with very large related history
can still produce a large in-memory graph. Measure large production tenants before
using full history on high-volume dashboards. Compact views omit historical steps
whose only source is a former Shipment outside the current financial graph.

## Verification

Unit/integration cases cover interrupted registration, missing Invoice/payment,
partial/full settlement, refunded payment in transit, shared freight/Invoices,
several Invoices per Parcel, frozen membership after removal/reassignment,
cancel/correction/reissue history, stable ordering, location attribution,
read-only grants, tenant/SERVICE/anonymous denial, staff privacy, credit fail-closed
behavior, action adapter rechecks and bounded read-only queries.

`test_workflow_summary_concurrency` uses real PostgreSQL: a refund commits before
the reader's receipt query without tearing its snapshot, and a queued delivery scan
is denied after a refund clears the Business lock. Existing billing permission,
charge identity/coverage and customer payment concurrency suites are also run.
The optional `scripts/logistics_workflow_summary_browser_check.py` checks desktop
and mobile journey/history, list/dashboard/scan rendering and restricted staff
output using Chromium. Test execution results belong in the implementation handoff;
this document defines behavior, not deployed-provider readiness.

Local verification on 2026-10-13: the 451-test PostgreSQL regression run passed,
including SERVICE billing. After final audit changes, 161 focused PostgreSQL tests
passed, including the resolver, snapshot/scan races, financial permissions,
coverage and location policy. The 26-test financial concurrency run and the final
Chromium test at 390/1440 pixels passed. Ruff, Black, diff whitespace checks and
`makemigrations --check --dry-run` passed; no migrations were generated. Test suites
overlap and their counts must not be added as a unique-test total.
