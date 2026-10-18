# Shared customer Invoice payments

Customer accounting lives in `apps.billings`, using the existing Invoice, InvoiceLine, tenant roles, subscription/module authorization and activity audit. It is independent of Stripe SaaS subscription billing. No customer collection or refund provider API is called.

## Model and migration

`InvoicePayment` is one append-only shared model for receipts, reversals and completed refunds. Every entry records:

- Business and Invoice, positive Decimal amount and currency;
- kind (`RECEIPT`, `REVERSAL`, `REFUND`), method (`CASH`, `BANK_TRANSFER`, Logistics `ONLINE`, `VERIFIED_ONLINE`), stable reference and optional external verification evidence;
- recording actor and server timestamp, idempotency UUID and Invoice total snapshot;
- optional original receipt and a required adjustment/correction reason reference.

A replacement receipt points to the corrected receipt through the same original link. The original receipt and its reversal remain unchanged. Database constraints enforce positive amounts, known kinds, an original for reductions, tenant-scoped retry uniqueness, root reference uniqueness and one correction successor per receipt. Service locks additionally prevent reference duplicates involving corrections and reductions.

`billings.0012_customer_invoice_payments` creates the new table and constraints. Its new tenant FK is required because there are no historical payment rows to backfill. It does not rewrite existing Invoices or create historical receipts. Existing SERVICE and Logistics PAID rows keep their status and monetary amounts. No parallel Logistics Invoice/payment models are added.

## Services and semantics

The public services are `record_invoice_payment`, `adjust_invoice_payment`, `correct_invoice_payment` and the read-only `invoice_settlement`, all in `payment_services.py`.

Receipts are accepted only for issued active SENT/PAID Invoices. New DRAFT or CANCELLED payments are rejected. For Logistics, existing currency/tax/charge integrity checks also apply, and legacy Invoice snapshot confirmation is required before taking a receipt.

Amounts use exact Decimal inputs and ROUND_HALF_UP at the currency's minor unit. Floats, booleans, nonfinite amounts, negative amounts and amounts rounding to zero are rejected. USD, XCD, EUR and ANG are supported at two decimal places, matching the current workspace currency catalog and Invoice monetary schema. Unsupported currencies fail closed. No FX conversion or mixed-currency payment allocation is performed.

The first receipt establishes the Invoice's payment currency and total basis. Later entries preserve that basis. Net paid is receipts minus reversals/refunds; outstanding is the saved Invoice total minus net paid for an active Invoice. A cancelled Invoice has no collectible balance and cannot accept receipts; its original basis and full adjustment history remain available. A positive receipt cannot exceed outstanding. Each reversal/refund must target a receipt on that same Invoice and cannot exceed its unreduced amount. Partial payments and partial reductions are supported.

All writes lock the existing Business, persisted actor membership and Invoice in that order and run atomically. Balance checks, duplicate checks and insertion occur under those locks. Invoice recalculation also takes the Business/Invoice locks and rejects payment history. Exact retries return the original entry after current authorization is rechecked. Changed payloads using the same token are rejected. A fresh token cannot reuse a stable receipt reference within its Business, even on a different Invoice, with a different method or after reversal; refund/reversal references are also checked for duplicate submissions. References normalize whitespace and case. Use stable workspace-unique references, with source/branch prefixes where independent receipt sequences would collide. A genuinely different cash receipt or bank transaction needs its own reference; the application cannot identify an event submitted with both a new token and an unrelated invented reference.

`adjust_invoice_payment` records a reversal of an erroneous entry or a refund already completed outside the app. It reduces the original receipt's remaining amount and recalculates outstanding without editing/deleting either record. It never sends money.

`correct_invoice_payment` atomically reverses an unadjusted receipt and appends one replacement receipt with an audit reason. Invalid replacements roll back the reversal and audit together. Exact retries return the successor, and competing corrections cannot fork. The successor can itself be corrected. Fully reduced, partially refunded or partially reversed receipts require reconciliation rather than an automatic correction, avoiding ambiguity about previously returned money.

Receipt/reduction/correction events also write existing ActivityLog entries. Normal model/queryset mutation, deletion and bulk writes are blocked; the Django payment admin is read-only. Receipted Invoice ownership, monetary totals and lines are protected, even after reversal. Cancellation with net active receipts is rejected until those receipts are reduced. Customer payment history, including fully refunded history, blocks ordinary Invoice deletion, demo reset and the existing tenant purge, including confirmed test-financial purge. No financial-history deletion bypass is added.

## Legacy status, settlement and SERVICE compatibility

Invoice lifecycle status remains independent of payment settlement. Recording a full receipt does not automatically mark an Invoice PAID; reversing/refunding does not silently reopen its lifecycle status. The existing SERVICE transition graph and behavior for Invoices without receipts are unchanged. New receipt-history guards apply only after opting into payment accounting.

An Invoice marked PAID with no receipts returns `LEGACY_PAID_UNVERIFIED`, net paid zero and its full unverified outstanding balance. No synthetic receipt is created by migrations, reads or the old Mark as Paid action. Later real, authorized receipts can establish partial/full settlement. A manually PAID Invoice with partial or refunded receipts remains financially outstanding despite its label. Original PAID terminal lifecycle restrictions remain; receipt adjustment does not introduce credit notes or rewrite the issued Invoice.

Settlement is derived from recorded net payments, saved Invoice basis and integrity checks. A SENT Invoice can be financially settled while retaining its SENT status. Zero-value issued Invoices can be settled without fabricating a payment; legacy manual PAID status without receipts remains unverified. Inconsistent ownership, snapshots or reduction lineage return `REVIEW_REQUIRED` and prevent writes/clearance.

Logistics Parcel/shared-freight clearance now uses this shared authoritative settlement result instead of checking only Invoice.status. Every applicable active charge must have one financially settled Invoice and existing coverage/evidence checks must pass. A refund immediately removes clearance where it restores an outstanding obligation. The bounded STAFF clearance API still exposes no amounts, Invoice IDs or other cargo IDs.

Logistics finance dashboard outstanding balances and net receipts also use the ledger, grouped by saved currency. Manual PAID amounts are not counted as receipts. Legacy/review cases are identified. SERVICE's existing dashboard and Invoice presentation defaults are retained. If a SERVICE workspace changes currency after a receipt, the payment panel and subsequent receipt entries preserve their original currency/basis and explicitly explain the difference from the existing Invoice display defaults; no conversion is implied.

## UI and permissions

Authorized shared Invoice detail pages display settlement, net paid, outstanding and retained receipt/adjustment history. Recording and adjustment forms live under the existing Invoice routes. Invoice read/PDF permissions are not broadened.

| Role | Receipt entry | Reversal/refund/correction | Balances/history |
| --- | --- | --- | --- |
| OWNER / ADMIN / ACCOUNTANT | Authorized accounting Invoice scope, cash/bank and externally verified online | Same accounting scope, with reason/evidence | Existing financial read scope |
| SERVICE STAFF | Existing authorized Invoice scope, cash/bank | Denied | Existing Invoice read scope |
| Logistics STAFF | Only fully accessible Parcel-only Invoices at the active reviewed `can_operate` work location, cash/bank/online | Denied | Existing accessible Invoice scope; bounded accessible Parcel clearance |
| Read-only assigned Logistics STAFF | Denied | Denied | Existing assigned read scope |
| Unassigned/unreviewed Logistics STAFF | Denied | Denied | No Logistics finance access |
| VIEWER | Denied | Denied | Existing read scope |

Active tenant/user/membership and invoicing subscription/module checks apply to both UI and direct services. Logistics STAFF additionally retains Parcel module and complete-Invoice location checks. Accounting roles do not need operational work-site selection for accounting. Externally verified online entry requires an accounting role and an evidence reference checked outside Motionmate. It is an auditable manual attestation, not automated gateway verification. It cannot be selected by STAFF and uses no SaaS Stripe credentials or subscriptions.

Logistics receipt forms offer Cash, Bank transfer and Online payment to authorized
operators, including STAFF. Online payment records an ordinary receipt without
external verification evidence. Receipt references are optional for Logistics;
when omitted, the service generates `RECEIPT-<retry UUID>`, retaining retry and
reference uniqueness. Older open Logistics forms posting `VERIFIED_ONLINE` save
as `ONLINE`. SERVICE receipt requirements and accounting adjustment permissions
remain unchanged. Full payment establishes settlement through the existing ledger.

Cross-tenant Invoice/payment/adjustment relationships are rejected. If trusted maintenance creates inconsistent history, balance projections flag review and suppress unsafe receipt details rather than exposing another tenant's reference or using its amount as the Invoice basis. Trusted raw SQL/platform maintenance remains outside the ordinary domain-write boundary; database row-level security is not introduced.

## Verification and limits

Automated tests cover cash/bank receipts, partial/full payment, exact and fresh-token duplicates, overpayment, Decimal rounding, role/subscription/location denial, correction rollback/lineage, refunds and reversals, legacy PAID, shared Invoice clearance, immutable history, tenant/purge/reset safeguards and SERVICE regressions. PostgreSQL concurrency tests cover overpayment, exact retries, fresh-token duplicates, independent partial payments, competing refunds/corrections and membership deactivation. A historical migration test proves existing PAID amounts/statuses survive without fabricated receipts.

Real Chromium checks exercise payment entry, partial/full balances and refunds at 390 and 1440 pixels, alongside existing protected Logistics Invoice issuance and shared-freight reissue checks. Screenshots: `/tmp/mm-payment-browser/`, `/tmp/mm-finance-browser/`, `/tmp/mm-coverage-browser/`.

The local verification uses disposable PostgreSQL 14.24 and SQLite test databases and a temporary test-only MD5 password hasher. Deployed migrations, actual cash/bank custody, external payment verification and actual refunds require operational verification. Provider collection/refund automation, credit notes, FX, multi-Invoice receipt allocation and currencies beyond the current catalog are not implemented.

Local test evidence (overlapping suites; do not sum as unique tests):

- PostgreSQL financial/SERVICE/location/dashboard regressions: 192 passed, including 26 real concurrency tests (7 new payment races). `/tmp/mm-payment-finish-postgres.log`.
- SQLite expanded financial/SERVICE/demo/reset/inventory/purge regressions: 234 passed. `/tmp/mm-payment-finish-regressions.log`.
- Final payment/reference-identity/concurrency/historical-migration checks after strengthening reference uniqueness across methods: 26 passed. `/tmp/mm-payment-final-schema.log`.
- Final payment/UI rerun after presentation and cancelled-balance refinements: 20 passed, including all 3 Chromium interaction tests at mobile/desktop widths. `/tmp/mm-payment-finish-ui.log`.
- Historical payment and coverage migration rerun: 2 passed. `/tmp/mm-payment-final-migrations.log`.
- Django system checks, migration drift, changed-file Ruff/Black and `git diff --check` passed.
