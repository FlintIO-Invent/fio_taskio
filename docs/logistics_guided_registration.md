# Guided Parcel registration

## Audit and implementation

The existing Parcel form already provided tenant-scoped Client search, shared CRM
inline creation, metadata tabs, explicit route fields and a registration nonce.
The charge, Invoice and Shipment services already provided transactional writes,
locking, immutable financial snapshots and replay checks. The missing part was
navigation: registration stopped at detail, charging returned to detail, Invoice
creation returned to billing, and Shipment creation returned to Shipment detail.

This change adds a Logistics-only continuation page around those forms and
services. It adds no model, migration, payment/credit exception, workflow flag or
session wizard. Shared SERVICE views and services are unchanged.

## Entrypoints and steps

- Existing Register Parcel form: **Register & continue** is the primary action;
  **Register Parcel** retains its existing direct detail redirect. Existing Client
  search, inline **Add Client**, shipping prefill and all metadata fields remain.
- Parcel detail: **Continue Registration** opens
  `/logistics/parcels/<parcel_id>/registration/`.
- The continuation page reconstructs Client/Parcel, charge coverage, linked
  Invoices, settlement and assigned Shipment with `resolve_parcel_workflow`.
  Outstanding registration tasks and a suggested continuation link use persisted
  evidence; operational tracking tasks remain separate.
- Guided charge/Invoice links use the existing forms with `?registration=1` and
  return to the same Parcel. The Invoice form preselects its pending direct
  charges and offers other authorized same-Client Parcel charges. At least one
  selected charge must belong to this Parcel. Existing same-Client authorized
  drafts can receive pending charges from another Parcel's continuation page.
- Issuance calls existing `change_invoice_status(..., status="SENT")`, preserving
  protected lines. Payment entry uses shared `PaymentReceiptForm`,
  `invoice_settlement` and `record_invoice_payment`. Payments are money already
  received, independent of manual Invoice status; they do not collect money.
- Shipment choices are the newest 25 authorized, pre-departure Shipments matching
  the Parcel's explicit facility route (or existing textual route where no facility
  is recorded), excluding Shipments charged to a different Client. **Browse all
  Shipments** retains the existing selection workflow. Direct assignment still
  calls existing `assign_parcel`, with revision and nonce checks.
- **Create Shipment with this Parcel** opens existing `ShipmentForm`, preselects
  Parcel/origin/destination and returns to the continuation page. Substitution or
  omission of that Parcel is rejected. Creation and assignment remain one atomic
  service operation. A stale create link for an already assigned Parcel resumes
  the saved journey rather than creating another Shipment.
- **Assign later** shows the completion summary without creating a deferral flag
  or a Shipment. Summary includes label preview/download, authorized Invoice
  references, verified clearance, assigned Shipment and remaining tasks.

Each successful write uses POST/redirect/GET. Reloading a summary performs no
financial or assignment write. The journey can resume in a new session/device
with an authorized actor; it does not depend on original browser/session state.

## Authorization and accounting

| Actor | Guided finance | Operational steps |
| --- | --- | --- |
| OWNER / ADMIN | Existing tenant-wide accounting; Invoice issuance and authorized receipt methods | Existing role, work-context and operation rules |
| ACCOUNTANT | Existing accounting scope; guided page also requires Parcel read visibility | No new registration/Shipment permission |
| Operating STAFF | Charges, same-Client Invoice generation/append and issuance only for complete authorized Parcel-only Invoices at active `can_operate` site; cash/bank receipts on that scope | Existing registration/assignment services, active approved site |
| Read-only location STAFF | Limited clearance; no finance writes or payment entry | No new operating permission |
| Unassigned STAFF | No Parcel journey or financial access | No bypass |
| VIEWER | Existing authorized read scope | No writes |

STAFF summaries retain restricted finance. A worker with complete writable Invoice
scope receives a generic **Parcel Invoice** review/issuance/payment entry link;
the default continuation summary does not publish amounts, actual Invoice numbers or receipt
history to workers. Selecting payment entry explicitly authorizes and displays
that Invoice's existing balance/form. STAFF forms exclude externally verified
online receipts. Accounting roles retain the existing external evidence method.

Every Invoice action is restricted to a related Invoice and rechecks shared
financial policy. Writes use Business then membership locking and existing
services, reloading scope under lock. Invoice generation checks all selected
charges and all draft siblings, preventing cross-tenant, cross-Client or
cross-location append. A readable location is not a writable work site. Routing
fields never create worker assignments or permission grants.

Exact charge/Parcel/Shipment/receipt nonces reuse saved results. Identical Invoice
charge selections reuse their existing binding, including guided HTTP retries
after issuance. Fresh nonce logical charge duplicates show the existing validation
error; fresh receipt references/tokens cannot overpay. No historical snapshots or
manually PAID Invoices are rewritten. Shared Invoice balances remain full-Invoice
balances, without invented Parcel allocations. Frozen Shipment freight membership
continues to come from charge coverage, never current membership alone.

Missing/ambiguous financial evidence and legacy manually PAID remain uncleared.
`CREDIT_APPROVED` remains reserved and is never inferred or created. Deferring
payment or assignment does not authorize departure/delivery.

## Verification

Automated endpoint/service regressions cover existing/new Client, full registration,
partial/full payment, independent interruption/resume, shared Invoice creation and
draft append, preselected Shipment creation, atomic rollback, existing assignment,
deferred assignment, exact/fresh-token retries, read-only/active-site/cross-tenant
denials, unrelated Invoice IDs, STAFF receipt method restrictions and SERVICE/direct
workflow preservation. Real PostgreSQL HTTP concurrency checks cover registration,
logical charge duplicates, Invoice creation/issuance, receipt replay/overpayment
and competing assignments.

Optional real Chromium check:
`scripts.logistics_registration_browser_check`. It exercises the complete journey
at 390 px with touch/mobile context and 1440 px, including inline Client value
preservation, combined Invoice, partial/full receipts, detail/resume, defer, both
Shipment paths and refresh counts. It checks JavaScript errors and horizontal
overflow. Evidence is written to `/tmp/mm-registration-browser/`.

Tests use disposable local PostgreSQL databases; no deployed workspace/provider
records are modified. Native installed PWA/iOS Safari, real cash/bank custody,
external receipt verification, label hardware and deployed/offline behavior remain
operational checks. Registration and financial writes require a live server;
this block adds no offline write queue or external payment collection.

Final local verification, 2026-10-14 (overlapping runs; do not sum):

- PostgreSQL: 251 regression tests passed, including all three new guided HTTP
  concurrency tests and existing shared/SERVICE billing tests.
  Log: `/tmp/mm-registration-acceptance.log`.
- SQLite: 18 tests run, OK; three PostgreSQL-only concurrency tests skipped.
  Log: `/tmp/mm-registration-sqlite.log`.
- Chromium: one complete interaction test passed at both 390 and 1440 px;
  no JavaScript errors or horizontal page overflow. Screenshots were visually
  inspected. Log: `/tmp/mm-registration-browser-final.log`.
- Screenshots: `/tmp/mm-registration-browser/completion-390.png`,
  `completion-1440.png`, and `inline-client-1440.png`.
- Django system checks, migration-drift check, changed-file Ruff/Black and
  `git diff --check` passed. No schema migration is required for this change.
