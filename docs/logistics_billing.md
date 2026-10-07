# Logistics billing with shared Services and Invoices

## Architecture audit and choices

- Catalogue: `crm.BusinessService` is Business-owned and contains name, description,
  category, external code, decimal unit price, tax rate, active/archive status, and
  booking fields. `ServiceCategory` already supports workspace categories. No new
  catalogue, pricing engine, applicability enum, or category migration is needed:
  Business ownership distinguishes each Logistics catalogue from SERVICE catalogues.
- Currency and localized money entry/display come from Business. There is no
  per-Service currency. Existing invoices calculate tax using the workspace rate;
  this block retains that behavior, including for Logistics. Catalogue tax fields
  remain available. There are no existing default-quantity, internal-notes, or
  per-line discount fields to expose.
- Services currently become invoice charges through the shared invoice editor,
  optionally via appointments. InvoiceLine stores Service, description, quantity,
  unit price, and line total. Invoice belongs to Business and Client and optionally
  references an Appointment. Prices are snapshots, not live catalogue calculations.
- Parcel belongs to Business and an immutable Client. Shipment belongs to Business
  and can group Parcels from several Clients; it has no direct Client or Invoice FK.
- Reuse unchanged: catalogue CRUD/archive/import, categories, localized prices,
  Client records, invoice numbering, totals/tax, invoice status, PDF/email behavior,
  workspace roles, subscriptions, and dashboard components.
- Generalize: enable Services for LOGISTICS. Existing Services forms/screens omit
  booking fields, booking columns and booking guidance in that context. A separate
  `booking_availability` capability retains the original SERVICE availability access
  even for plans without public booking. Appointment/public booking remain isolated.
- Extend InvoiceLine with nullable Parcel and Shipment FKs. Old lines remain valid
  without either relation. Each Logistics line references exactly one operational
  target. Existing records need no backfill because they had no target relationship.
- Add `logistics.LogisticsCharge`, a pending charge snapshot, not an invoice or
  catalogue: Business, Client, one Parcel/Shipment, optional existing BusinessService,
  description, quantity, charged unit price, frozen target reference, actor, retry
  token, and an optional unique protected InvoiceLine link.
- Custom pricing: no Service required. Saved services use their description/name and
  current price at charge creation; an explicit amount overrides the price without
  changing the catalogue. Quantity and unit price must be positive/nonnegative,
  finite decimal values within the existing financial field limits. Target references
  and prices remain fixed when parcels or services are subsequently edited.
- Duplicate protection: tenant locks, transactions, a unique tenant/retry token, and
  one-to-one InvoiceLine attachment. Several charges for the same Parcel are allowed.
  Exact service-layer invoice retries return the existing invoice; web forms reject
  already-invoiced selections without creating more records.
- Integrity: targets, Services, Clients, invoices, and lines share one Business;
  Parcel Client equals Invoice Client. Invoice creation accepts one Client per batch;
  an existing invoice must be a draft for that Business and Client. Shared invoice
  creation and mutation use the same Business lock order.
- Shipment charging requires one unambiguous Client from its Parcels or already saved
  charges. Empty unbilled or mixed-client shipments cannot be billed. Once charges
  exist, another Client's Parcel cannot be assigned. Explicit parcel removal remains
  possible; the saved charge Client retains the billing relationship. Shipment
  billing never copies or automatically bills member Parcel charges.
- Permissions: existing billing view/manage roles govern financial visibility,
  custom charges, price overrides and invoice attachment. Catalogue management stays
  owner/admin only. Services and operational/invoice subscription gates remain active;
  read access does not imply write access. An accountant may bill existing parcels
  without acquiring permission to register or move them.
- Financial retention: charge amounts and invoice links cannot be edited. Inactive
  Services remain readable, are excluded from new selections, and may be invoiced
  from previously saved charges. Services with Logistics charges are protected from
  deletion. Generic invoice editing/deletion is blocked for linked Logistics invoices,
  preventing detached charges and accidental rebilling. Additional charges can still
  be added to their draft invoices through Billing. Controlled demo reset/purge retain
  their existing ownership, financial, exact-selection and rollback gates.

## Workflows and files

Parcel/Shipment detail → Billing → Add charge → existing Service or custom charge.
Billing → Create invoice / Add to existing invoice → choose pending charges → select
an existing same-Client draft or create a new draft → existing Invoice detail/PDF/email.
The shared Service list is linked from Logistics navigation and Billing.

Implementation: `logistics/billing_services.py`, `billing_forms.py`, `billing_views.py`,
shared billing templates, catalogue forms/templates, shared Invoice models/services/views,
and tenant inventory/demo reset/purge registration. Migrations:
`billings/0010_invoiceline_parcel_invoiceline_shipment` and
`logistics/0008_logisticscharge`.

## Demo and validation

`python3 src/manage.py seed_demo_data --business-id <ID>` previews without writes;
add `--execute` to seed the selected existing tenant. The Logistics branch retains
explicit selection, existing operator/subscription checks, ownership metadata, and
reset safeguards. It creates eight shared Services, nine charge snapshots, three
shared invoices and five lines: standard price, multiple parcel services, negotiated
price, custom one-off charge, pending charges, several parcels on one invoice, and
single-client shipment billing. No notifications, Stripe calls or payment operations
are triggered. The SERVICE seed dataset remains unchanged.

Tests cover catalogue access/booking isolation, saved/custom parcel and shipment
charges, overrides, history/archive, quantity/money validation, multiple targets,
Client/tenant checks, draft filtering, role/subscription gates, retry safety, protected
history, seed/reset, existing invoice and SERVICE behavior. PostgreSQL concurrency
checks cover retry races, simultaneous charge attachment/totals, invoice numbering,
and shipment Client membership races.

Deferred: editing/removing saved charges, credit notes/refunds, reopening cancelled
charges, automatic allocation of mixed-client shipment fees, per-line tax/discount
redesign, currency snapshots, and dynamic shipping rates. These need separate financial
lifecycle decisions; this block uses the established invoice tax/currency behavior.

## Verified results

- Full PostgreSQL 14.24 UTF-8 suite: 1,323 tests passed across accounts, CRM,
  businesses, billing, appointments, and Logistics, including the five new billing
  concurrency tests and the existing operational concurrency tests.
- Final focused SQLite billing suite: 22 tests passed after the invoice detail UI
  changes, including saved Service CSV import, fractional-price rounding, historical
  retention, protected invoice controls, and links to operational targets.
- Django system checks, migration-drift check, Ruff on changed Python files/new
  migrations, formatting checks on new implementation files, and `git diff --check`
  passed.
- PostgreSQL ran in an isolated local test cluster because the configured application
  database role lacks test database creation privileges. Application database settings
  and data were not changed. No deployed browser/manual or real payment-provider
  verification is claimed.
