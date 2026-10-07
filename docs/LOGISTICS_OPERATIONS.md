# Logistics operational tooling (Block 10)

For optional local payment bypass and configuration-only promotion, see
[LOGISTICS_LOCAL_DEVELOPMENT.md](LOGISTICS_LOCAL_DEVELOPMENT.md).

Run commands with the normal deployment settings. Select an existing tenant by
its exact Business ID. `seed_demo_data` retains its existing SERVICE behavior
and dispatches LOGISTICS tenants to the same Logistics seed/reset implementation.

## Demo data and reset

```sh
python3 src/manage.py seed_demo_data --business-id <ID>
python3 src/manage.py seed_demo_data --business-id <ID> --execute
python3 src/manage.py seed_demo_data --business-id <ID> --reset-demo
python3 src/manage.py seed_demo_data --business-id <ID> --reset-demo --execute

# Existing Logistics-specific entry point remains available:
python src/manage.py seed_logistics_demo_data --business-id <ID>
python src/manage.py seed_logistics_demo_data --business-id <ID> --execute
python src/manage.py seed_logistics_demo_data --business-id <ID> --reset-demo
python src/manage.py seed_logistics_demo_data --business-id <ID> --reset-demo --execute
```

The Logistics command accepts LOGISTICS businesses only and defaults to a
read-only preview. Seeding requires normal active workspace/subscription access
and an existing active operator. `--actor-id <USER_ID>` selects that operator;
otherwise the first eligible member by user ID is used. It never creates users,
activates plans, changes subscriptions or overwrites operational records.

The normal command keeps its required `--business-id` / `--business-slug`
selector and preview-by-default behavior; it never guesses the target tenant.
SERVICE count/booking options are rejected for LOGISTICS rather than silently
ignored. Both commands use the same ownership records and reset safeguards.

The fixed Logistics example contains 10 Clients (eight businesses and two
individuals), 20 Parcels, 83 ParcelEvents, and six Shipments, one in each shipment
status. Twelve parcels are assigned to shipments; eight remain unassigned.

| Parcel status | Count |
| --- | ---: |
| Registered | 3 |
| Received | 4 |
| In transit | 3 |
| Arrived | 2 |
| Ready for collection / delivery | 1 |
| Delivered | 3 |
| On hold | 2 |
| Cancelled | 2 |

Every client is linked to two parcels. Metadata varies across sea, air and local
road routes, sender/recipient names and contacts, addresses, country/tax IDs,
content, quantity, weight, structured centimetre measurements, volume, legacy
dimensions, declared value, HS codes, marks, carrier/vessel and voyage details,
ports, bills of lading, issue dates, Incoterms, handling flags, expiry dates and
private notes. Status history follows normal parcel/shipment transitions. Location
checkpoints include origin, en-route and destination locations; two parcels also
have private metadata-edit history. This provides recent deliveries, waiting
parcels, attention items and shipment/dashboard summaries for manual testing.

`DEMO-020` deliberately has only required registration fields and a demo reference:
its optional metadata, measurements and location are unknown. Some other parcels
omit contacts, addresses, declared values, marks or notes to exercise empty states;
legacy-dimension examples omit structured measurements. Sea-only voyage/IMO and
bill-of-lading fields are empty on air/road parcels. Expiry dates are provided only
for the compostable-container examples. Creation/update/event timestamps remain
the real service-write times, preserving immutable history; document/expiry and
shipment schedule dates vary relative to seeding time.

Parcel/Shipment services perform every lifecycle mutation. Tracking codes and
shipment references retain normal random generation; sample content and counts
are repeatable. Seeding fails atomically on validation/access errors. Repeated
execution requires preview/reset first and cannot append another Logistics dataset.

The existing `DemoSeedRun`/`DemoSeedRecord` ownership metadata tracks every new
record. A second seed refuses to append until the existing run is reset. Reset
checks tenant ownership, supported labels, relationships and competing ownership
claims, then removes only tracked events, parcels, shipments and clients, in that
order, atomically. Genuine or untracked dependents abort the entire reset,
including new events on demo parcels and parcels assigned to demo shipments.
Demo parcels attached to genuine shipments also block reset. Review and resolve
dependencies explicitly; reset never deletes or detaches genuine operational
data. Inactive tenants can reset; mixed SERVICE seed metadata is refused.

## Inspection and lifecycle

```sh
python src/manage.py inspect_business_data --business-id <ID>
python src/manage.py inspect_business_data --business-id <ID> --format json
python src/manage.py inspect_logistics_application --application-id <UUID>
python src/manage.py deactivate_business --business-id <ID> --reason-reference <REF>
python src/manage.py deactivate_business --business-id <ID> --execute --confirm-business-id <ID> --reason-reference <REF>
python src/manage.py purge_business --business-id <ID>
python src/manage.py purge_business --business-id <ID> --execute --confirm-business-id <ID> --reason-reference <REF>
```

Business inspection includes vertical, Logistics plan/interval/status, safe
application ID/status linkage, record and usage counts, parcel status summary,
active/completed shipments and threshold review signals. Application inspection
remains focused on enrollment/decision retention and linked business/subscription
state. Neither summary includes application contact details, grants, tracking
codes or raw provider identifiers. SERVICE inspection keeps its existing fields.

Deactivation retains Logistics data and application history, closes operational
workspace access and public tracking, and preserves the existing notification,
subscription and selective session protections. No Logistics-specific deletion
is performed.

The controlled purge deletes demo ownership records, ParcelEvents, Parcels and
Shipments in dependency order before Clients. All existing inactive-business,
exact-ID confirmation, reason-reference, financial-data, Stripe-reference,
cross-tenant, transaction rollback, audit and post-delete verification gates
remain. Users are preserved by default; shared users and users referenced by
retained Logistics application/enrollment history remain protected even when
eligible-user deletion is requested. No Stripe API is called.

**Converted applications and their decision/token history remain retained.**
Block 11 adds the minimum retention policy: after every existing purge gate passes,
the controlled purge replaces the protected Business link with a conversion ID
snapshot and revokes grants. Application inputs, decisions, token history and
the enrolled User survive. Ordinary Business/User deletion remains protected.
Stripe references still block paid-tenant purge; no financial bypass is added.
See [LOGISTICS_PILOT_READINESS.md](LOGISTICS_PILOT_READINESS.md).

Business Admin adds vertical/application-link filters, sortable parcel/shipment
counts and a read-only resource summary. List counts use SQL subqueries with
eager-loaded application/plan links, avoiding per-row count queries. Application
Admin adds linked-business visibility/filtering.

## Resource and pricing review visibility

`apps.logistics.usage.logistics_usage(business=..., now=...)` is an internal,
read-only helper. Callers must authorize access; it also works for inactive
LOGISTICS tenants. It counts active memberships with active users, Clients with
both `is_active` and ACTIVE status, calendar-month registrations and events,
active shipments (excluding completed/cancelled), distinct monthly deliveries,
all-time average events per parcel, totals and parcel status counts. Months use
the Business IANA timezone with inclusive start/exclusive next-month boundaries.
Delivery counts use delivery events, including parcels registered earlier.

`logistics_operational_summary` adds safe subscription/application state and
`logistics_threshold_summary` review signals. Existing
`LOGISTICS_ELIGIBILITY_POLICY` thresholds remain advisory while the pilot default
`LOGISTICS_AUTO_APPROVE_ALL=True` is enabled. False restores strict approval rules: auto-approval,
review and high-resource parcel volumes, staff count and location count.
Locations are explicitly an **application estimate**, not observed usage.
There is no location model yet.

`LOGISTICS_USAGE_APPROACHING_RATIO` (default `0.8`) controls approaching signals.
Optional `LOGISTICS_MONTHLY_EVENT_REVIEW_THRESHOLD` is a separate operational
review threshold; an absent value reports `not_configured`. Exact threshold
values are approaching; values above them are exceeded. Missing location data
reports `unavailable`. No commercial plan limits are inferred from either
policy. These helpers never change approvals, access, pricing, subscriptions or
quotas; there is no overage billing or cost accounting. They are independent of
web/PWA/API presentation.
