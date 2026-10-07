# Logistics shipments and manifests (Block 8)

Shipment is the operational grouping for existing Parcels. There is no Voyage or
persistent Manifest model. Apply Logistics migration 0004 before using this block.
Existing Parcels start with a nullable, empty shipment link; no ownership backfill
is needed. New Shipments require a Business from creation.

## Services and access

Use `apps.logistics.shipment_services` from staff or future PWA/API entry points:
`create_shipment`, `update_shipment`, `assign_parcel`, `remove_parcel`,
`change_shipment_status`, `generate_manifest`, and `shipments_for_business`.
All accept an explicit Business and actor. Services reload the active LOGISTICS
Business, active user/membership, role, plan and subscription, including the
shipments capability and manifests capability for manifest generation. Owners,
admins and staff can mutate; all workspace roles can read. Restricted subscriptions
retain reads and downloads, but cannot mutate. Assignment/removal also require
existing parcels/tracking write access; propagated Parcel status updates recheck
that access through the existing Parcel service.

Shipment details comprise a generated unique immutable `SHP-<UUID>` reference,
origin/destination, optional departure and estimated arrival datetimes, status,
optional internal notes, creator and timestamps. ETA cannot precede departure.
Only DRAFT details may be edited. Ordinary saves, bulk writes and deletion are
blocked using the existing Logistics domain guard. Private persistence hooks are
reserved for services and the gated tenant purge.

## Lifecycle and membership

`shipment_policy.ALLOWED_TRANSITIONS` is the lifecycle authority:

- DRAFT → READY, CANCELLED
- READY → DRAFT, IN_TRANSIT, CANCELLED
- IN_TRANSIT → ARRIVED
- ARRIVED → COMPLETED
- COMPLETED and CANCELLED are terminal.

One nullable `Parcel.shipment` foreign key permits at most one current membership.
Assignment/removal is allowed only in DRAFT or READY; operational status determines
departure, rather than a scheduled datetime. Only REGISTERED or RECEIVED Parcels
can be assigned. HOLD, advanced, delivered and cancelled Parcels are rejected.
Business and Client ownership are rechecked from the database. Repeated assignment
to the same predeparture Shipment is a no-op. An implicit move is rejected: remove
from the old predeparture Shipment, then assign to the new one. A departed Shipment
keeps its membership, including after completion.

READY and IN_TRANSIT require at least one assigned Parcel, all RECEIVED. A new
REGISTERED assignment to READY must be received or removed before departure.
ARRIVED requires every member IN_TRANSIT. HOLD or inconsistent Parcel states block
the transition and require resolution through the established Parcel workflow.
COMPLETED requires every member DELIVERED; shipment completion never delivers
Parcels automatically. Predeparture cancellation releases membership without
cancelling Parcels or changing their histories.

IN_TRANSIT and ARRIVED call `change_parcel_status`, preserving its lifecycle checks
and immutable ParcelEvents with actor/server timestamp. Public messages contain
only the Parcel's operational status; the Shipment reference stays in the internal
note. All member changes and the Shipment transition share one transaction.
Business locks follow the existing Parcel lock order; members lock in stable PK
order. A failure rolls back the entire transition, including earlier member events.
`expected_status` optionally rejects stale writes; staff status forms always send
it. Repeating an already-applied transition is rejected, without duplicate events.
SQLite regression tests verify atomic rollback and sequential operations;
PostgreSQL row-lock concurrency needs separate verification.

## Generated manifests

`generate_manifest` returns a current snapshot as plain allowlisted data:
reference, route, departure/ETA, and each same-business member's tracking code,
Client first/last display name, package description, quantity and optional weight.
Totals report Parcel count, quantity, known weight in kilograms and the number of
Parcels lacking weight; missing weights are never represented as a complete total.
Parcels with corrupt Business or Client relationships are excluded. Lifecycle
mutations reject corrupt inbound memberships rather than silently skipping them.

Staff can view escaped HTML and download UTF-8 CSV. CSV text neutralizes spreadsheet
formula prefixes. Private Client contacts, addresses, notes and registration IDs,
Parcel financial fields, Shipment notes and internal event notes are excluded.
Manifest responses are authenticated, tenant-scoped and marked no-store. No issued
manifest history or immutable snapshots are required for this MVP, so outputs are
regenerated on demand and there is no persistence model.

## UI and tenant tooling

`/logistics/shipments/` provides list, detail, create/edit draft, assignment/removal,
status change and manifest operations. Mutations use POST with CSRF protection.
Foreign URL identities return 404; foreign form objects are rejected. Parcel detail
shows only a same-business Shipment association with shipment read access. The
Parcel registration and public tracking contracts are unchanged.

Admin offers tenant-scoped read-only Shipment inspection. `inspect_business_data`
automatically includes shipment counts/status activity, both directions of
Parcel/Shipment integrity checks, and creator membership/cross-business user
references. Purge explicitly deletes ParcelEvents, then Parcels, then Shipments
before Clients and the tenant. Cross-tenant links block both tenants' purges.
The existing inactive-business, exact-ID confirmation, financial/Stripe retention,
reason-reference, audit rollback and conservative user deletion safeguards remain.

## Block 9 readiness

No implementation blocker is known. Block 9 needs its own scope. Future clients
must call the same services, supplying an authenticated actor and explicit tenant;
client-submitted business/status relationships must never bypass service checks.
No warehouse, customs, carrier integration, external API or PWA/scanner entry point
is introduced here.
