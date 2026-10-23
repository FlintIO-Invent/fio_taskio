# Internal parcel hub intake

## Decision and scope

The secondary **Register Parcel** button saves and opens parcel details. At an
authorized, active current work location whose type is HUB, it also records
receipt. The operator uses it for physically accepted cargo. Outside that hub
context it retains registration-only behavior. The separate Save & receive
button has been removed.

The primary **Register & continue** button also records RECEIVED at an authorized
current HUB, then opens the existing registration workflow. Both hub actions
represent physical receipt; ordinary registration at other facility types and
direct service/API/import entry points retain their existing behavior. No new
intake fields, confirmation screen, routes or migrations are introduced. See
`logistics_registration_safety_update.md` for the October 23 update and verification.

## Existing receipt behavior traced

- `parcel_services.register_parcel()` writes the parcel and its original
  REGISTERED `ParcelEvent`, with actor, selected operating location and timestamp.
- `change_parcel_status()` delegates to atomic `record_parcel_event()`. It locks
  the Business, membership and parcel; rechecks tenant/client, subscription,
  operating permissions, expected state, route/site rules and lifecycle; and
  records the RECEIVED event and updates `current_status`/`updated_at`.
- Receipt time is the immutable event's `timestamp`; there is no separate
  `received_at` field. `ParcelEvent` is the existing parcel audit history.
- `location_operations.current_site()` reads the operational event history.
  Receipt attributes handling to the employee's selected site. The destination
  does not establish possession, and destination access is not granted by intake.
- Public tracking reads the current status and public event messages from the DB.
  Intake adds the ordinary public message “Parcel received.” Private site IDs and
  employee details remain outside the public projection.
- REGISTERED and RECEIVED parcels are both assignable to eligible shipments.
  Shipment readiness already requires received cargo. Existing departure,
  delivery, settlement and credit checks remain in their original services.
- No receipt-specific email, notification, job, webhook, Stripe call, charge or
  invoice creation was found in the receipt service, model persistence or app
  startup hooks. No billing side effects were added. The movement-clearance
  service only gates IN_TRANSIT and DELIVERED, not RECEIVED.

## Implementation

`register_and_receive_parcel()` wraps the two existing operations in one outer
transaction. A receiving hub must be selected explicitly through the existing
work-location mechanism and must match the parcel's origin facility, including
for administrators in legacy compatibility mode. The established receipt service
still performs its normal validation; this helper supplies no site override.

The original registration UUID stays on its REGISTERED event. Receipt uses a
stable UUIDv5 derived from that UUID, through the existing tenant-scoped event
retry mechanism. Repeating a submission returns the existing operation, creates
no duplicate events/callbacks, and does not rewind a subsequently changed status.
Changed payloads, employee identities and receiving locations fail existing
retry/authorization checks. A failed receipt rolls back parcel creation, both
history writes, status changes and queued `on_commit` callbacks together.

Only `views.parcel_register()` opts into this helper when its explicit
`save_and_receive=1` submit flag is sent by Register Parcel at an eligible hub.
Ordinary registration, edit, scanner, demo and other shared-service callers retain
their existing paths. The
Register Parcel button stays after Register & continue in DOM order, retaining
the existing implicit-submit default. Successful intake opens parcel details;
the continuation workflow is entered only through Register & continue.

## Verification

24 focused tests passed on an isolated PostgreSQL 14 instance, including 19 new
intake tests (one uses real concurrent transactions). Coverage includes employee
and hub attribution, timestamps/history, public tracking, shipment assignment,
no automatic financial/notification effects, full rollback and discarded commit
callbacks, replay after later status changes, duplicate concurrent submissions,
foreign tenants/routes/actors, role and site restrictions, destination access,
ordinary registration and metadata editing. Existing receipt retry/rollback and
structured-route registration/charge checks also passed. Formatting/lint and
`git diff --check` passed.

Desktop and mobile Chromium checks exercised the existing wizard through Review,
verified that only the two intended submit buttons remain, and verified their
distinct submitted actions and primary/secondary styles. Register & continue
still submits without the intake flag; Register Parcel submits it only at an
eligible hub. No additional input fields or confirmation step were needed.

A separate existing metadata suite had 13 passes and seven failures; an older
complete-registration test also failed. All eight failures were reproduced with
original HEAD parcel services, views and creation/edit template loaded in memory,
without altering workspace files. They concern older registration/route-reference
fixtures and are outside this change; they were not counted as passing tests.
The PostgreSQL instances and test databases were disposable and were stopped.

No existing tenant data, historical parcels, provider configuration or Stripe
state was changed. Changes remain local, without commit, push or deployment.
