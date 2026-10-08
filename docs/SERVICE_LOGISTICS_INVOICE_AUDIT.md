# SERVICE / LOGISTICS invoice and isolation audit

## Missing invoice root cause and live verification

The configured database is PostgreSQL `taskio_database_dev` at localhost:5432.
The seeded LOGISTICS workspace is Business **9**. Its original seed run
`408ab78d-d5b6-4785-8ec8-279b18d89d07` was created on 2026-10-06 and planned only
10 Clients, 20 Parcels, 83 ParcelEvents and six Shipments. Ownership contained
exactly those four model labels. There were no owned or persisted Services,
LogisticsCharges, Invoices or InvoiceLines.

The first missing point was **creation in the old seed version**, before invoice
persistence. The current seed's 4-invoice/13-line preview describes a new run; it
does not upgrade an existing run. Existing ownership prevents silently appending
another dataset. Invoice queries do not hide rows by vertical, service or
appointment: they filter by the active Business and an optional requested status.
The appointment join is optional, not a requirement to appear in the list.

There was also a separate access issue. Business 9 remains `pending_checkout`.
Normal effective access redirects invoice requests to subscription setup (HTTP
302); it does not return an empty invoice table. The configured local bypass flag
requires **ENV=local and DEBUG=True**. The default shell settings had DEBUG=False,
so the flag alone did not grant access. No subscription/payment/provider records
were changed to make the demo accessible.

After a reviewed ownership-reset plan, the old demo was reset and the current
dataset seeded inside one database transaction. Existing genuine domain records,
users, memberships, applications/decisions/tokens and subscriptions were compared
before/after and were unchanged. The retained profile now has Transportation with
Sea + Road. The new run owns 152 demo records.

| Measurement | Before refresh | After refresh |
| --- | ---: | ---: |
| Invoice count declared by the persisted seed run | No invoice entry | 4 |
| Persisted invoices | 0 | 4 |
| Persisted invoice lines | 0 | 13 |
| Owned invoices / lines | 0 / 0 | 4 / 13 |
| Local-access Invoice UI rows | 0 | 4 |
| Normal pending-checkout access | HTTP 302 | HTTP 302 |

| Invoice | Business | Client | Status | Lines | Subtotal | Tax | Total (USD) |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| INV-0001 | 9 | 72 | SENT | 3 | 195.00 | 0.00 | 195.00 |
| INV-0002 | 9 | 74 | PAID | 4 | 227.50 | 0.00 | 227.50 |
| INV-0003 | 9 | 75 | SENT | 3 | 43.00 | 0.00 | 43.00 |
| INV-0004 | 9 | 76 | DRAFT | 3 | 190.00 | 0.00 | 190.00 |

All four Clients belong to Business 9. All appointment links and all 13 Service
links are null. Sent/Paid are explicitly labelled simulated demo states; no email,
payment or Stripe operation occurred. Database totals agree with the line totals.
Chromium confirmed four invoice rows on desktop and mobile, the Paid invoice's
four lines and total, with no page errors. Normal access was verified separately
and still respects the pending-checkout gate.

## Shared and vertical-specific architecture

| Component | Current classification | Evidence / assessment |
| --- | --- | --- |
| Business, users, BusinessUser/team | Shared, tenant scoped | Active workspace resolution and membership/role checks are common. Plan families and offerings remain vertical specific. |
| Clients | Shared | One Client model, Business FK and scoped querysets. Both verticals can create Clients and invoice them independently. |
| Invoice / InvoiceLine | Shared | One pair of models, common list/detail/forms/status/totals/PDF/email paths. Business and Client ownership are required; Service/Appointment references are optional. |
| Subscription/payment policy | Shared infrastructure | Central effective access combines business capability, plan entitlement, subscription state and role. Logistics annual/no-trial offering and SERVICE trial policy remain separate. |
| Notifications, settings, layout | Shared infrastructure | Shared email utilities and Business settings/context/navigation. Vertical-specific actions are conditional; no new notification/payment side effects were introduced. |
| Services/categories/catalogue imports | **Currently exposed to both verticals** | Logistics deliberately gained `services` capability for charge-price catalogue reuse. This conflicts with the requested SERVICE-only classification. |
| Service Requests, appointments, availability, online booking | SERVICE operational workflows | Central capabilities and module decorators block normal LOGISTICS routes/imports/booking. Public booking renders unavailable for a Logistics business and creates no requests or appointments. |
| LogisticsApplication, LogisticsProfile | LOGISTICS | Application/enrollment/review is platform/public infrastructure; profiles validate LOGISTICS tenant ownership. SERVICE workspace settings do not expose an operating profile. |
| Parcels/events, Shipments, manifests, tracking | LOGISTICS | Tenant-aware domain services plus centralized capability/plan/access gates; SERVICE operational requests are denied. Anonymous tracking is intentionally scoped by the parcel's bearer code and Logistics business access. |
| Dashboard / onboarding | Vertical-specific presentation | Logistics has parcel/shipment tasks and dashboard queries; SERVICE keeps its service/booking/appointment flows. Selection uses capabilities, with explicit Logistics billing-onboarding branches. |

Relevant sources: `businesses/capabilities.py`, `models.py` subscription access,
`utils.py`, `context_processors.py`, `onboarding.py`; `crm/views.py`;
`billings/models.py`, `views.py`, `services.py`; Logistics domain services.

## Invoice independence and access boundaries

- Shared invoice creation accepts description, quantity and price without a saved
  Service, Appointment or Service Request for **either** vertical. PostgreSQL tests
  create those invoices through the normal form/view. No form field requires a
  Service. Invoice and line model validation protects Business/Client ownership.
- List/detail/PDF/edit/status/email views use shared invoice capabilities and role
  guards. Invoice list uses related-object joins, detail prefetches lines, and both
  scope all rows to the active Business. No cross-tenant invoice visibility was
  found. Invoice numbers are unique within a Business, not across all businesses.
- Logistics billing repeats tenant/role checks at its domain-service boundary but
  delegates entitlement decisions to the same subscription access methods. This
  is additional service-boundary validation, not a conflicting billing policy.
- Client detail includes Logistics parcel sections only with Logistics parcel and
  tracking access; appointments are conditional on appointment access. SERVICE
  Client behavior is preserved. The explicit Logistics test around the optional
  parcel panel is redundant with its capability checks, not a restriction on the
  shared Client route.
- Explicit vertical checks for operating profiles, domain writes, plan-family
  compatibility, public enrollment and billing onboarding are appropriate. Shared
  Clients/Invoices themselves do not require SERVICE or LOGISTICS.

## Remaining cross-contamination and UI/access inconsistencies

These were audited and reported; production workflows were not redesigned.

1. **Catalogue boundary:** `VERTICAL_CAPABILITIES['LOGISTICS']` includes `services`.
   Logistics owners can list/create/edit/archive/import Services and categories.
   Existing capability/billing tests explicitly confirm this historical behavior.
   Logistics forms suppress booking duration/online-booking fields, but the
   catalogue remains accessible. Consequently “LOGISTICS cannot access Services”
   is not currently true. The new seed no longer creates Service objects.
2. **Shared invoice copy:** create/edit templates use
   `module_capabilities.services`, so Logistics currently sees “Add Service Line”,
   “Service name” and “No services found. Add services in Settings -> Services”.
   Manual invoice creation still works; this is misleading copy, not the missing
   invoice root cause. Price/Service selectors are optional.
3. **Appointment invoice entry point:** `invoice_create_from_appointment` checks
   invoicing access but lacks an appointment capability gate. Its queryset is
   tenant scoped, so another business's appointment cannot be used; nevertheless
   same-tenant legacy Appointment rows could expose SERVICE-specific invoice
   actions to Logistics. Standard appointment routes remain blocked.
4. **Navigation access mismatch:** the main Services link uses raw capability and
   role, rather than effective module access. The parcel navigation also checks
   `module_access.services`, which is absent from that context dictionary. Backend
   Service routes still enforce effective access. These conditions can produce
   misleading or missing links.
5. **Client copy:** shared Client detail still shows Interested Services and archive
   confirmation text about keeping appointments for Logistics. Those fields/text
   are not required to create a Client or invoice. The conditional parcel panel
   does not alter SERVICE Client sections.
6. **Common invoice presentation:** status badges use `bg-draft`, `bg-sent`,
   `bg-paid`, `bg-cancelled`; browser inspection showed white status text against
   the light page background. Status data and filter counts are correct. This is
   a shared styling defect affecting either vertical, not missing invoice rows.
7. **Common action mismatch:** the list offers edit/delete for draft/protected
   Logistics invoices even though backend guards retain saved charge history;
   the detail page correctly restricts those actions. Paid detail can also offer
   cancellation although the common status-transition policy rejects it. The
   protections work, but the advertised actions can be misleading.
8. **Scale limitation:** the common Invoice list fetches all matching invoices
   without pagination. Related-object joins prevent per-row Client/Business
   queries, but the unbounded list remains a growth concern. No performance/UI
   redesign was undertaken.

## Seed/reset audit and limited fix

`seed_demo_data` resolves one existing Business. SERVICE executes its unchanged
service/request/appointment/booking workflow; LOGISTICS dispatches to the Logistics
implementation and rejects SERVICE generation/booking options. The Logistics-only
command rejects SERVICE businesses, including for reset.

DemoSeedRun is unique per Business. DemoSeedRecords identify model plus object PK;
reset validates selected-tenant ownership, supported labels, relationships,
genuine dependents and competing claims before deletion. Forged cross-vertical
invoice ownership aborts preview and execution. Resetting one tenant's run leaves
the other tenant's seed/invoices untouched. Genuine invoice lines/activity/history
block destructive reset where appropriate.

SERVICE registers objects it actually creates and does not claim ActivityLogs by
invoice-number matching. Logistics invoice ActivityLogs are scoped to the newly
created demo Client as well as Business and invoice number; number reuse cannot
claim a genuine older log. A regression test preserves such a genuine log.

The limited code change makes Logistics seed charges self-contained description/
quantity/price snapshots, with null Service references. The four shared invoices
and 13 lines keep their existing stories, statuses, quantities, tax calculation
and totals. Zero SERVICE workflow records are created. Older owned Service records
remain supported by reset for backwards compatibility. No Invoice model, production
billing, SERVICE seed, lifecycle or access policy was changed.

Verdict: **NEEDS FURTHER SEPARATION** — operational tenancy and shared invoices are
sound, but the deliberate Logistics Services catalogue and the listed presentation/
appointment-source access gaps do not match the requested boundary.

## Verification

- 26 focused PostgreSQL tests passed, including nine new vertical/invoice audit
  cases and the 17 Logistics seed cases.
- 347 PostgreSQL regression tests passed across shared billing, SERVICE seed/reset,
  capabilities, Logistics workspace/operations/lifecycle/tracking, classification
  and local billing safeguards. Tests used an isolated PostgreSQL database and
  test-only fast password hashing, not the user's development database.
- Actual development database refresh and before/after protection comparisons
  passed. Invoice UI was rendered with the existing operator and verified in
  Chromium at desktop/mobile widths. Temporary browser authentication is removed
  after verification.
- Django system checks, migration-drift check, Ruff, Black and `git diff --check`
  passed. No schema changes are required.

## Exact local commands for Business 9

Business 9 has already been refreshed. Inspection is read-only. Reseeding again
requires reviewing reset first; genuine/manual dependencies will cause refusal.

```sh
export ENV=local DEBUG=True LOGISTICS_LOCAL_BILLING_BYPASS=True

# Verify existing counts/profile/ownership:
.venv/bin/python src/manage.py inspect_business_data --business-id 9 --format json

# Review and execute only the owned demo reset, then preview and execute reseed:
.venv/bin/python src/manage.py seed_logistics_demo_data --business-id 9 --reset
.venv/bin/python src/manage.py seed_logistics_demo_data --business-id 9 --reset --execute
.venv/bin/python src/manage.py seed_logistics_demo_data --business-id 9
.venv/bin/python src/manage.py seed_logistics_demo_data --business-id 9 --execute

# Start the local UI with the same environment:
.venv/bin/python src/manage.py runserver 127.0.0.1:8109
```

Sign in as the existing Business 9 operator and open
`http://127.0.0.1:8109/billings/` in that workspace.
These local environment flags use the existing documented bypass; they do not
activate subscriptions, create payment history or belong in deployed settings.
