# Logistics parcels (Block 6)

Parcel registration reuses `crm.Client`. New Parcel and ParcelEvent tables have
required Business ownership from their first migration; there are no existing
parcel records to backfill. Shipment, Manifest, public tracking, PWA, scanner and
external API entry points remain outside this block.

## Services and access

Use `apps.logistics.parcel_services.register_parcel`, `record_parcel_event` and
`change_parcel_status` from any future entry point. Each requires an explicit
Business and authenticated actor. The services reload persisted Business,
subscription, plan and membership rules: LOGISTICS, active workspace/member/user,
parcels and tracking entitlements, and write access. Owner, admin and staff can
write; all existing workspace roles can read through `parcels_for_business`.
Restricted subscriptions keep read access and reject writes under the existing
billing policy. These operations never call Stripe or change billing.

Registration accepts an existing same-business Client and the lean descriptive
fields. Null, unowned, foreign or subsequently reassigned Clients are rejected.
The Client model and SERVICE CRM workflows are unchanged. Weight is in kilograms;
dimensions are optional text including units. Declared value uses workspace
currency and is informational, with no invoicing or payment effect.

Parcel ownership, Client and tracking code are immutable. New codes use
`MM-PCL-` plus 39 cryptographically selected characters (about 193.2 bits),
with a database uniqueness constraint and bounded collision retries. Existing
48-character uppercase hex codes retain their original 192-bit secrets.
They contain no PK encoding. No tracking-code recovery operation is provided.
See [Tracking Code V2](MOTIONMATE_LOGISTICS_TRACKING_CODE_V2.md).

## History and transitions

`parcel_policy.ALLOWED_TRANSITIONS` is the lifecycle authority:

- REGISTERED → RECEIVED, CANCELLED, HOLD
- RECEIVED → IN_TRANSIT, CANCELLED, HOLD
- IN_TRANSIT → ARRIVED, HOLD
- ARRIVED → READY, HOLD
- READY → DELIVERED, HOLD
- HOLD → RECEIVED, IN_TRANSIT, ARRIVED, READY, CANCELLED
- DELIVERED and CANCELLED are terminal.

A STATUS event records the resulting status, server timestamp, actor, optional
location, public message and a separate internal note. Registration creates the
initial REGISTERED event. NOTE events append tracking information without changing
status, including after terminal statuses. Never project internal notes into future
public tracking responses. The staff templates escape messages as plain text.

Business and Parcel locks serialize writes and protect against concurrent purge.
Client ownership is rechecked under a Client lock. Updating current_status and
inserting its event share one transaction. PostgreSQL provides the row locks;
SQLite tests verify rollback and sequential replay, not concurrent row locking.
Ordinary model saves, QuerySet updates, bulk writes and deletion are blocked.
Private persistence helpers belong to the services and gated purge workflow only;
raw SQL and Django base managers are privileged maintenance escape hatches.

Supply an optional UUID `idempotency_key` for retryable operations. The unique
Business/key constraint and Business lock ensure the same key/payload returns the
original result. Reusing a key for another operation or payload is rejected.
Replaying a status event after further transitions does not rewind the parcel.
Without a key, a repeated same-status transition is invalid. `expected_status`
provides an optional stale-write check; a matching retry is recognized first.
Staff forms always supply both retry keys and expected status for event writes.

## Staff and lifecycle tooling

`/logistics/parcels/` lists current-workspace parcels, with detail, registration
and update forms. The sidebar exposes Parcels through the existing capability and
subscription context. Admin provides tenant-scoped read-only parcel/event
inspection, search and filters; registration and status changes use the staff UI.
Even superusers need an active workspace membership and appropriate subscription.

`inspect_business_data` inventories parcel/event counts, both directions of
Client/Parcel tenant relationship corruption and creator/actor references.
Purge registers these protected dependencies and explicitly deletes events, then
parcels, before Clients. Only the existing gated purge can remove history. Active
business, exact-ID confirmation, reason reference, audit rollback, converted
application protection, financial and Stripe-reference safeguards remain intact.
Users referenced by another business's parcels/events are conservatively retained.
Actor deletion sets nullable user references to NULL and retains every event.

## Next block

Block 6 provides the domain foundation. Define Block 7 scope before adding new
operations. Shipment/Manifest grouping and lifecycle rules, public tracking's
allowlisted response and abuse controls, and mobile/scanner credentials and
permissions each need their own specification if selected. No implementation
blocker is known; apply the new migration before using parcel operations.
