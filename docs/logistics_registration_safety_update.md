# Logistics registration and shipment safety update

## Audit findings and resulting behavior

1. **Shipment permissions.** `SHIPMENT_MANAGE_ROLES` previously reused parcel
   management roles, granting operating staff shipment creation, editing, removal
   and lifecycle changes. Management now requires OWNER/ADMIN in both HTTP
   decorators and the locked shipment services. Read access still uses the existing
   business/location scope. Parcel assignment has its own role check and retains
   work-site, route/mode, billing-client, revision and replay checks. Operating
   staff can assign an eligible parcel through registration or the existing
   assignment screen, but cannot remove cargo or change shipment details/status.
   Shipment actions are hidden accordingly. There is no ordinary shipment delete
   endpoint; Django admin remains inspection-only. Scheduling was not changed.

2. **Explicit payment decision.** The continuation resolver previously resumed at
   Shipment after issuance, and the generic JavaScript Continue skipped payment
   entry. Payment now requires an explicit Paid/Unpaid selection and submission.
   Paid uses `PaymentReceiptForm`, `invoice_settlement` and
   `record_invoice_payment`; amount/method/allocation validation, financial
   authorization, invoice locking and receipt idempotency remain authoritative.
   Unpaid saves navigation intent without creating a receipt, changing invoice
   status or granting financial clearance. A successful submission redirects
   explicitly to the Shipment fragment. Failed submissions stay on Payment and
   retain submitted fields, selection and receipt nonce, including when an earlier
   unpaid decision exists. Back navigation keeps unsaved browser fields.

   The decision is session navigation state scoped to business and parcel, never a
   payment/accounting flag. Another session asks again. Receipt balances always
   come from the existing financial records. Shared invoice amounts remain full
   invoice balances; no parcel allocation system or external collection was added.
   Read-only users see an authorized-colleague message instead of decision controls.

3. **Reusable defaults.** Business Settings now has optional vessel/carrier lists
   (one name per line) and optional matching defaults. Existing owner/admin and
   workspace-write checks govern changes; submitted business IDs do not select
   another tenant. New operational forms offer the configured names and applicable
   defaults. Existing/ad-hoc values remain valid and visible even after settings
   change; an edit never applies a new default to an existing record. Vessel
   defaults apply only to Sea transport. Existing `BusinessService` management,
   saved-service selection and localized price prefill already cover reusable
   service charges, including their existing tax logic and snapshots. Settings
   links make that catalogue explicit; no parallel pricing catalogue was added.
   Configuration changes do not rewrite parcels, shipments, charges or invoice
   lines. Existing local cancellation/refund work was preserved, not extended.

4. **Physical hub receipt.** Both Register Parcel and Register & continue now use
   `register_and_receive_parcel` at an authorized current HUB. That existing
   atomic service records REGISTERED followed by RECEIVED, attributes both events
   to the actor/site, verifies the actual origin facility and reuses a stable
   receipt nonce. A failed receipt rolls back creation and event callbacks; exact
   retries neither repeat receipt nor rewind later movement. Other facility types
   and direct service/API/import paths still use ordinary registration. No
   existing parcel statuses are bulk changed.

   Receiving dependencies were traced through parcel transitions, event-derived
   custody, public tracking, workflow summaries, shipment readiness/eligibility,
   financial movement clearance and billing. Received cargo is already supported;
   shipment readiness requires it. The receipt service has no notification,
   invoice, receipt-payment or external-provider side effect.

## Migration and rollout

`businesses.0034_logistics_transport_defaults` adds four optional Business fields
with empty defaults. It depends on the existing local
`0033_business_cancellation_service_charge`. No data backfill, new tenant FK,
operational-state migration or financial rewrite is required. Include the reviewed
migration chain and refreshed static assets when releasing. Check actual hub work
contexts/origin facilities before operational rollout because both hub buttons now
represent physical receipt. Advance registration remains available outside that
physical hub flow and through the unchanged registration service.

No commit, push, deployment, application database migration, live-data write or
external payment-service call was performed.

## Verification

The focused endpoint/service tests cover staff reads and mutation denial,
registration assignment/retries and tenant/location scope; paid/unpaid submission,
validation and replay; settings permissions/defaults and historical snapshots;
and owner/admin/staff hub registration, event history, receipt retries and rollback.
PostgreSQL tests also exercise competing HTTP registration/invoice/payment/
assignment writes and shipment service retries. A migration round-trip test checks
that existing operational and financial records survive the additive fields.

The optional `scripts/logistics_registration_changes_browser_check.py` exercises
real Chromium at 390 and 1440 pixels, including primary hub registration,
unselected decisions, Back, unpaid continuation, invalid then valid paid input,
refresh counts, settings save, name selectors and saved-service price prefill.
It checks JavaScript errors and page overflow. Screenshots are saved in
`/tmp/clarivo-four-browser/`. Physical devices, Safari and deployed runtime were
not verified.

All tests use disposable local databases. No application database or provider
configuration is used. The local test settings only replace password hashing,
static storage, email and HTTPS/cookie requirements for the disposable server.

Final local results (23 October 2026):

- **149 distinct focused PostgreSQL tests passed** across the main selection
  (126), shipment write/concurrency safety (22), and migration preservation (1).
  After final intake locking and UI review, the affected intake/registration/
  concurrency selection passed again (39), as did staff visibility checks (2).
  These rechecks overlap the 149 and must not be added to that count.
- **Two Chromium scenarios passed**, each at 390 and 1440 pixels. The hub/payment
  scenario passed again after the final locking change. Screenshots were visually
  inspected; no page overflow or JavaScript errors were found.
- Django system checks, migration-drift detection, focused Ruff, changed Logistics
  Python/new migration formatting, and `git diff --check` passed.
- Logs: `/tmp/clarivo-four-postgresql-final.log`,
  `/tmp/clarivo-four-write-final.log`, `/tmp/clarivo-four-migration.log`,
  `/tmp/clarivo-four-intake-final.log`, `/tmp/clarivo-four-staff-final.log`,
  `/tmp/clarivo-four-browser-final.log`, and
  `/tmp/clarivo-four-browser-intake-final.log`.
- An exploratory broader `test_transport_details.py` selection failed on older
  mode/route fixtures (including unconfigured modes and territory/reference
  inputs). That module was not repaired or revalidated in this block. A clean
  full Logistics/project suite is therefore **not claimed**. The focused
  transport/default/history checks above passed. Older browser scripts also
  retain assumptions about the previous optional-payment UI; use the new focused
  browser check for this behavior.
- No unresolved business decision blocks these four changes. Wider legacy test
  maintenance and deployed/physical-device verification remain outside the
  completed focused checks. The disposable PostgreSQL cluster is stopped after
  verification; no application database was used.
