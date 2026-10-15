# Scanner continuation and movement clearance

## Audit and policy

The existing manual/wedge and camera inputs already resolved exact tenant/location
scoped tracking codes. Lookup was read-only, with explicit nonce/status guarded
action POSTs. Scanner/detail had financial gates, but direct ParcelEvent and
Shipment propagation could move unpaid cargo. Credit approval was reserved with
no authoritative model. This change closes those service gaps and provides an
audited exception, without another Invoice or payment ledger.

All new `IN_TRANSIT` and `DELIVERED` ParcelEvents now require verified settlement
or valid movement-scoped credit. The guard runs inside the existing Business then
membership lock order. Supported receipt, refund, Invoice/charge and credit writes
use that same Business lock, so clearance and movement cannot race through a stale
scan. Shipment departures invoke the same ParcelEvent guard for every member;
failure rolls back the entire Shipment transition and all child events.

Receiving, arrival, readiness and permitted holds remain governed by existing
lifecycle/location rules. Unpaid, partial, disputed or unknown financial evidence
does not independently block receiving/arrival. Credit never grants route or
location authority, and an administrator's site override is not a financial waiver.

Missing charges, unbilled/draft obligations, legacy manually PAID status, ambiguous
coverage, invalid money/currency/tax evidence and inaccessible/unowned relationships
cannot authorize departure/delivery. Existing historical events are not rewritten.

## Credit records and semantics

- `LogisticsCreditApproval`: immutable Business/Parcel/Client, departure or delivery
  action scope, approver and role at approval, reason/evidence reference, approval
  timestamp, optional review location, required expiry, nonce and exact obligation
  snapshot/fingerprint.
- `LogisticsCreditRevocation`: immutable approval, Business, revoker, reason,
  timestamp and nonce. Revocation never deletes an approval or movement history.
- `ParcelEvent.credit_approval`: nullable protected reference to the approval used
  for that movement. Migration `0022` leaves all historical references null and
  does not fabricate credit or receipt records.

Only OWNER/ADMIN may approve/revoke. Review requires complete verified **issued**
Invoice evidence and positive outstanding debt. Approval is bound to all current
active applicable charges, frozen billed-Parcel membership, exact active line and
Invoice bindings, saved monetary/currency/tax values and full related Invoice
balance limits. Shared balances are not allocated or double-counted per Parcel.
Approval for one Parcel cannot clear another member of a shared Invoice/Shipment.

The review fingerprint must still match when approval is submitted under lock.
Payment can reduce the balance within the approved limits. A refund above a limit,
new/corrected/voided charges, cancelled/reissued bindings or changed Invoice basis
invalidate the approval. Expired/revoked/invalid records never produce
`CREDIT_APPROVED`. Renewal/correction revokes older approvals for the same Parcel
and action scope, retaining the audit and preventing wider-limit fallback.

An approval permits its action type while valid, including a repeated departure
after an authorized hold when the obligations remain identical. Delivery requires
its own approval. Standard lifecycle/location rules still apply at every leg.
Full authoritative settlement remains `PAID`; valid credit against unpaid/partial
debt becomes `CREDIT_APPROVED`, retaining `settlement_state` and outstanding debt.
Approval creates no payment, discount, receipt, collection or refund.

## Entrypoints and privacy

Scanner lookup builds its Parcel and workflow projection in one read snapshot.
It shows current state/site, assigned accessible Shipment/mode, restricted or
detailed clearance, history, outstanding tasks and authorized action buttons.
**Continue Registration** opens the existing resumable registration/billing flow.
Owner/Admin **Review scoped credit** opens
`/logistics/parcels/<parcel_id>/credit/` for exact obligation review and revocation.

Exact successful action retries return the original event even if payment/credit
changes afterwards, while creating no new movement. A fresh action must pass current
state, role, site, operational evidence and financial checks. Wrong payload/actor/
tenant/site and stale expected status are rejected. Scanning never auto-advances.

| Actor | Receiving / arrival | Departure / delivery | Credit authority | Financial display |
| --- | --- | --- | --- | --- |
| OWNER / ADMIN | Existing operation/site rules | Same rules plus settlement or scoped credit | Approve/revoke within tenant | Authorized detailed accounting |
| ACCOUNTANT | No new operating rights | No new operating rights | No approval/revocation | Existing accounting and Parcel read scope |
| Operating STAFF | Accessible Parcel, active reviewed `can_operate` site | Same rules plus fresh clearance | None | Limited clearance, no private Invoice/payment/credit details |
| Read-only location STAFF | No writes | No writes | None | Limited accessible clearance |
| Unassigned STAFF | No access | No access | None | No Logistics finance access |
| VIEWER | No writes | No writes | None | Existing authorized read scope |
| Anonymous tracking | No writes | No writes | None | Operational allowlist only, no finance |

Tracking codes, legacy/V2 normalization, QR/Code128 labels, local camera decoder,
PWA/manual/wedge handling and SERVICE UI/billing are retained. Camera decoding
feeds the same read-only lookup; an action always requires explicit submission.

## Retention, fixtures and rollout

New credit records use existing domain-write protections, tenant inventory and
controlled purge/reset safeguards. Genuine credit attached to seeded records is
protected by the ownership checks. No live/deployed datasets were seeded/reset.

Operational-only unit fixtures now state explicit zero-value issued obligations
instead of silently advancing unbilled Parcels. Financial-policy tests create
their own real ledger evidence and do not use that helper.

New fictional demo/Test Lab runs stage billing before simulated movements and
record labeled Owner-approved scoped credit. No customer receipts are fabricated.
Demo gains an issued freight Invoice for previously unbilled arriving cargo; its
manually marked PAID example remains unverified. Test Lab issues the eight Invoices
needed for moving scenes, keeps four booking Invoices draft, and owns all credit
and audit records for safe reset. Reset additionally requires the seed's explicit
issued-invoice provenance, unchanged digests, owned credit snapshot dependencies,
no email history, no payments and no unowned dependents. Paid/dispatched documents
remain retained; older issued datasets without provenance need a disposable workspace.
Existing seed rows are not rewritten or credited
on migration/replay. Historical null event-credit fields do not change old manifest
digests. No staff assignments or foundation work contexts are added or relaxed.

Apply migration `0022` through the normal deployment process before serving the
new resolver. Physical scanner/device acceptance remains necessary: real USB/
Bluetooth suffixes and focus, autofocus/lighting and QR/Code128 reads, iOS Safari
camera permissions/lifecycle, Android installed PWA, HTTPS/media permissions,
offline reconnect and real receipt/credit operating procedures. Automated camera
adapter checks do not constitute physical camera/scanner verification.
