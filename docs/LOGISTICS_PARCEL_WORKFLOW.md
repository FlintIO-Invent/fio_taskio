# Logistics parcel creation, detail and editing

Motionmate extends its existing `Parcel`, `ParcelEvent`, `Client`, and `Shipment`
models. The Caribbean shipping manifest repository was inspected as a read-only
reference; its code, user roles, tracking identifiers and UI were not copied.

## Audit and field mapping

The reference creates parcels with an existing customer or an inline customer
form, generates a location-prefixed tracking number, and presents grouped parcel
details with a metadata edit form and optional status/location events. Quantity
must be at least one and weight positive. The reference's UUID, tracking number
and customer relation are excluded from its edit form. Location access and status
updates are less restrictive than Motionmate's existing tenant and lifecycle
services, so Motionmate retains its own checks.

Motionmate already supports client search/quick-create, parcel registration,
filtered/paginated lists with tracking links and View actions, dedicated detail,
shipment assignment, and immutable status/note history. This change adds metadata
editing and expands the existing creation/detail screens.

| Reference | Motionmate mapping |
| --- | --- |
| `customer` | Existing tenant-owned `Client`; no customer model added |
| UUID / `tracking_number` | Existing parcel PK and immutable random `tracking_code` |
| `description`, `packages_qty` | Existing `package_description`, `quantity` |
| `weight`, `gross_weight_kg` | Existing `weight_kg`; avoid ambiguous duplicate weights |
| `length`, `width`, `height` | Optional `length_cm`, `width_cm`, `height_cm` with explicit units |
| `volume_m3`, `hs_code`, `marks_numbers` | Optional fields with those names |
| `consignor_name`, `consignor_contact`, `consignor_address` | `sender_name`, `sender_contact`, `sender_address` |
| `consignor_country_iso`, `tax_id_number` | `sender_country_code`, `sender_tax_id` |
| Customer delivery contact | Existing Client contact plus optional `recipient_name`, `recipient_contact`, `recipient_address` when different |
| Transport / vessel / voyage / IMO / loading and discharge ports | Optional `mode_of_transport`, `vessel_name`, `voyage_no`, `imo_no`, `port_load_unlocode`, `port_discharge_unlocode` |
| `etd`, `eta` | Existing linked Shipment `departure_at`, `estimated_arrival_at` |
| `master_bl_no`, `house_bl_no`, `issue_date`, `incoterms` | Optional fields with those names |
| `declared_value`, `currency` | Existing declared value and workspace currency |
| `fragile_goods`, misspelled `biodegradbale_goods`, `expiry_date` | `fragile_goods`, `biodegradable_goods`, `expiry_date` |
| `internal_notes` | Optional workspace-only metadata, separate from public tracking messages |
| Status, location, status dates, employee | Existing controlled status transitions and ParcelEvent location/timestamp/actor; existing creator and parcel timestamps |

The reference does not define dimension units. New structured measurements use
centimetres; existing free-text `dimensions` remain intact. Dimensions must be
positive when supplied; volume must be nonnegative. No historical measurements
are inferred or converted. Existing weight validation remains unchanged.

Payment status, shipping charges and insurance bookkeeping are not imported:
they would introduce an independent financial record alongside Motionmate
billing. Hard-coded carriers/locations, independent risk/hold flags and a second
status lifecycle are also omitted. Holds and their reasons use the existing HOLD
transition and internal event note. No automated customs/risk rules are added.

## Routes and safeguards

- Existing registration, listing, detail and tracking-update routes are retained.
- `logistics_parcel_edit`: `parcels/<parcel_id>/edit/`, beside Record Update on detail.
- Registration and editing use the shared dashboard controls, Create Client's
  spacing and vertical tab pattern, field errors and a focused error summary.
- Metadata edits require the existing parcel/tracking write modules and management
  roles. Services recheck active Business, membership, subscription and Client
  ownership, and lock Business, Parcel and Client inside one atomic transaction.
- Client, Business, tracking code, creator, status and Shipment cannot be edited
  through the metadata form/service. Status and assignment keep their own services.
- A hidden timestamp rejects stale edits; an identical retry writes no duplicate
  history. Successful changes append an attributable private event listing changed
  field names. Event failure rolls back the parcel edit.
- New metadata is absent from the existing public-tracking allowlist. Only explicit
  public event messages continue to appear there.
- Migration `0006_parcel_metadata` adds optional strings/dates/measurements and
  false-default handling flags, preserving existing parcel data and relations.
- Migration `0007_reconcile_parcel_handling_column` repairs databases that applied
  an earlier draft of `0006` with `perishable_goods`. It renames that column to
  `biodegradable_goods` without resetting stored values. Databases already using
  the canonical column need no schema change. The migration state already has
  the canonical name, so reversing the repair leaves that name intact.

## Verification and rollout

Focused tests cover creation, optional defaults, validation, bound-value retention,
detail links/metadata, shipment/date/location display, editing, immutable fields,
stale submissions, retry behavior, rollback, tenant and permission boundaries,
CSRF, and public tracking privacy. PostgreSQL concurrency cases cover competing
metadata edits and metadata editing alongside a status transition.

Apply the migration through the normal deployment process. Check the form tabs,
validation focus, client quick-create and detail layout on desktop and mobile in
the deployment browser before release.

Verified locally on 2026-10-06:

- Full seven-app SQLite suite: 1,291 tests run, OK, 12 PostgreSQL-only skips.
- Focused PostgreSQL suite (metadata, parcels, shipments, workflows, public
  tracking, concurrency and migrations): 137 tests, OK, including all ten
  Logistics concurrency cases.
- Final PostgreSQL metadata/migration suite: 22 tests, OK.
- Chromium desktop (1440 px) and mobile (390 px): creation, required/measurement
  validation, revealing tabs with errors, list View navigation, metadata editing,
  and inline Client creation preserving parcel values passed. No JavaScript
  errors or horizontal page overflow were observed.
- Django system checks and migration-drift checks passed on both backends.
  Ruff, formatting of changed Python sections, JavaScript syntax and diff checks
  passed.

PostgreSQL ran in a temporary local instance because the configured development
role cannot create test databases. Browser QA used a separate temporary workspace
and database. Both temporary environments were stopped and removed; the configured
development database and reference repository were not changed.

A subsequent local schema mismatch was repaired with migration `0007`, which is
now applied in the development database. The corrected parcel/event queries and
the Logistics dashboard snapshot render successfully there. Additional migration
regression coverage checks both fresh metadata schemas and the earlier column
name, preserving true/false flags, other metadata and timestamps. The related
SQLite metadata/dashboard/migration suite passed 47 tests, and all three migration
tests passed on isolated PostgreSQL.

The full suite was run with:

```bash
LOGISTICS_LOCAL_BILLING_BYPASS=False DATABASE_URL= \
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
.venv/bin/python src/manage.py test \
  apps.accounts apps.businesses apps.crm apps.appointments \
  apps.billings apps.notifications apps.logistics \
  --parallel 4 --noinput
```

## Changed files

- `src/apps/logistics/models.py`
- `src/apps/logistics/migrations/0006_parcel_metadata.py`
- `src/apps/logistics/migrations/0007_reconcile_parcel_handling_column.py`
- `src/apps/logistics/parcel_services.py`
- `src/apps/logistics/forms.py`
- `src/apps/logistics/views.py`
- `src/apps/logistics/urls.py`
- `src/templates/logistics/parcel_form.html`
- `src/templates/logistics/parcel_detail.html`
- `src/templates/logistics/includes/form_errors.html`
- `src/static/assets/js/logistics-workflows.js`
- `src/apps/logistics/test_parcel_metadata.py`
- `src/apps/logistics/test_concurrency.py`
- `src/apps/logistics/test_retention_migration.py`
- `src/apps/logistics/test_workspace.py`
- `docs/LOGISTICS_PARCEL_WORKFLOW.md`

The existing theme-control assertion now recognizes checkboxes. Migration tests
restore the current migration leaves, including the new parcel migration.
Concurrency workers explicitly close their connections so PostgreSQL test
database teardown also succeeds when persistent connections are configured.
