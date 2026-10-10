# Logistics location-verified operations V1

Block 04 extends the existing Parcel services, immutable ParcelEvent history,
Shipment services/revision receipts, scanner resolver and tenant membership guards.
It does not introduce a state machine, user system or scanner adapter.

## Rollout

Apply additive Logistics migration 0017. It preserves all historical codes,
Parcel/Shipment states, events, actors, free-text locations, memberships and
LogisticsProfile classifications. New historical audit columns stay NULL and
Shipment histories start empty. No operational site or actor is inferred.

An owner/admin must review assignments, register facilities, map historical
origin/destination or CURRENT associations, approve one EXPECTED next stop where
needed, and select an active work site. The location-access settings page then
requires a separate explicit confirmation to enable verified operations. The
server records `location_operations_enabled_at` without changing operating areas
or transport modes. Ordinary UI cannot disable verification afterward.

Before this review, existing route transition rules continue. Staff still require
reviewed operational assignments and a current site; unassigned staff never gain
workspace-wide access. Site/actor context is recorded when available even before
verification is enabled. Once enabled, owners/admins also need a selected site.
Location administration remains accessible so missing mappings can be repaired.

Administrator context reuses the location-assignment table with `is_work_context`
set true. This records the selected site, grants no worker permission, and is
excluded from worker assignments. Demotion therefore cannot convert a former
administrator's self-selected context into a staff grant. Global SERVICE roles
and operations are unchanged.

## Actions

Services re-read active tenant membership, role, subscription, site and assignments
under the existing Business lock on every mutation. The acting membership row
is also locked before authorization, so shared team deactivation cannot race
past an authorized write. The lock targets only that tenant membership and
does not serialize unrelated businesses using the same user account. Client-submitted site IDs or
free-text location descriptions cannot select or authorize the operating context.

* Registration requires the selected origin facility after rollout. Metadata edits
  retain existing optimistic concurrency and route-edit permissions and record
  context. Owners/admins retain workspace-wide administrative visibility.
* Intake and departure require the recorded current handling site or origin. A
  legacy intake can use an explicitly approved single CURRENT/STOP association;
  no free-text geographic value is treated as a company facility.
* Arrival requires one unvisited EXPECTED next site, otherwise the destination,
  including an explicitly approved return to the same facility. Multiple pending expected sites are rejected
  for review. STOP alone grants handling visibility, not arrival permission.
* Readiness requires the current site. Delivery/completion additionally requires
  the destination or an explicitly approved STOP facility.
* Holds require the current site, or the approved next site while in transit;
  they cannot move unreceived cargo to another visible facility. Cancellation
  and tracking notes require a relevant approved handling site. Status guards remain authoritative: location permission never makes an
  invalid lifecycle transition valid.
* Owner/admin movement exceptions require an explicit nonblank private override
  reason (maximum 1,000 characters). Selected site, actor and reason are audited.
  Overrides cannot bypass tenant, active-site, subscription or lifecycle checks.
  No separate manager role is introduced.

Shipment services validate the site, membership integrity, all cargo states and
all cargo source sites before departure/arrival events are propagated. Shipment
arrival may be an intermediate approved site for its cargo. Nested Parcel
services reload persisted Shipment context and enforce the same policy. All
writes roll back if any member fails validation. Existing transitions, including
predeparture cancellation releasing cargo, remain intact.

Scanning alone only resolves a scoped Parcel. Camera, keyboard wedge, pasted
codes and manual actions use the same resolver and authoritative Parcel service.
No arrival/departure is inferred from a scan. Scanner actions do not carry an
administrator override; exceptions use the normal status form with a reason.

## History and privacy

New Parcel events record an optional protected operating-location FK,
previous/resulting state, authenticated actor and server timestamp. Legacy
free-text location remains a separate descriptive field, excluded from public
tracking as before. Historical
NULL values remain unknown. Events retain existing service-only immutability.

Shipment `operation_history` appends private entries for creation, metadata,
assignment/removal and status writes alongside existing revisions and receipts.
Entries include Business, actor ID/name snapshot, site ID/stable-code snapshot,
before/after state, server timestamp, retry key, affected Parcel and override
reason. It is service-owned JSON on the existing Shipment, not a second event
engine. Authorized detail pages show the latest ten entries; all remain stored.

Public tracking's explicit projection is unchanged and excludes actor, structured
site, private notes, audit history and override reasons. Manifests remain read-only.
Shared Client/Invoice permissions, billing and SERVICE behavior are unchanged.
Controlled-purge inventory also detects cross-tenant event-site references.

## Operational boundaries

A work site is an authorized account context, not GPS evidence or proof of
physical presence. EXPECTED associations describe one approved next stop; this
version does not order a full itinerary or plan transportation. To resume a
Parcel after an intermediate arrival, use the existing HOLD/resume transitions
and approve the next expected site; Shipment lifecycles are unchanged.

Use UUID retry keys for replayable requests. Receipts bind the actor and selected
site; switching sites changes the operation and cannot replay a receipt. Existing
status/revision checks and row locks reject competing writes. New administrative
site mappings remain deliberate management actions, rather than status events.

Existing demo seeding remains unchanged before rollout. After rollout, use
`seed_logistics_demo_data` (or the delegating `seed_demo_data`) with explicit `--origin-location-id` and
`--destination-location-id`, alongside the existing Business/actor arguments.
Both facilities must be active in that Business. A single operating facility
can serve both contexts for local or return workflows. The selected
current site must match the origin. A worker must have operational permission
at both sites. Preview describes the facilities without writing anything.
Execute switches work context through the normal service for the synthetic
scenarios and restores the origin at completion. No sites are created or
inferred, no guard is disabled, and no administrator transition override is used.
Demo counts, lifecycle scenarios, transport-mode compatibility, invoice lines,
profile settings and durable ownership/reset behavior are preserved. Existing
seeded rows remain intact; reset never uses a tracking-code prefix.
Direct database writes remain outside the application service authorization
boundary. Historical audit rows cannot be reconstructed from geographic text.

## Changed files

* `docs/logistics_location_operations.md`
* `scripts/logistics_location_operations_browser_check.py`
* `src/apps/businesses/business_data_inventory.py`
* `src/apps/businesses/context_processors.py`
* `src/apps/businesses/management/commands/seed_demo_data.py`
* `src/apps/logistics/demo.py`
* `src/apps/logistics/forms.py`
* `src/apps/logistics/location_access.py`
* `src/apps/logistics/location_access_services.py`
* `src/apps/logistics/location_access_views.py`
* `src/apps/logistics/location_operations.py`
* `src/apps/logistics/management/commands/seed_logistics_demo_data.py`
* `src/apps/logistics/migrations/0017_verified_operations.py`
* `src/apps/logistics/models.py`
* `src/apps/logistics/parcel_services.py`
* `src/apps/logistics/scan.py`
* `src/apps/logistics/scan_views.py`
* `src/apps/logistics/shipment_forms.py`
* `src/apps/logistics/shipment_services.py`
* `src/apps/logistics/shipment_views.py`
* `src/apps/logistics/test_location_migrations.py`
* `src/apps/logistics/test_location_operations.py`
* `src/apps/logistics/test_location_operations_concurrency.py`
* `src/apps/logistics/test_location_operations_demo.py`
* `src/apps/logistics/views.py`
* `src/templates/logistics/includes/scan_panel.html`
* `src/templates/logistics/includes/work_location.html`
* `src/templates/logistics/location_access.html`
* `src/templates/logistics/parcel_detail.html`
* `src/templates/logistics/shipment_detail.html`
