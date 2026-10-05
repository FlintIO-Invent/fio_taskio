# Logistics operational tooling (Block 10)

For optional local payment bypass and configuration-only promotion, see
[LOGISTICS_LOCAL_DEVELOPMENT.md](LOGISTICS_LOCAL_DEVELOPMENT.md).

Run commands with the normal deployment settings. Select an existing tenant by
its exact Business ID. `seed_demo_data` retains its existing SERVICE behavior.

## Demo data and reset

```sh
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

The fixed example contains three Clients, eight Parcels, 26 ParcelEvents, and
three Shipments (draft, in transit, completed), with five assignments and a mix
of registered, received, held, cancelled and delivered parcels. Parcel/Shipment
services perform every lifecycle mutation. Tracking codes and shipment references
retain the normal random generation; sample content and counts are repeatable.

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
