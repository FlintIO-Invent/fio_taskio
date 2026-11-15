# Shared identity, distinct verticals

Motionmate is one existing Django multi-tenant SaaS application. `Business` is
the tenant; `Business.vertical` distinguishes stored values `SERVICE` and
`LOGISTICS`. Neither the lab nor a shared visual pattern creates a second app,
replacement model, shared operational workflow or workspace switcher.

| Concern | Motionmate Services | Motionmate Logistics |
| --- | --- | --- |
| Work | Clients/CRM, bookings/appointments, invoices/payments, service administration | Clients/parcel registration, shipments/manifests, tracking/delivery, logistics invoicing/administration |
| Operational records | Existing `Appointment`; eligible unlinked `Lead` rows of type REQUEST; existing Client/Service models | Existing Parcel/Shipment/location/assignment models and operational services |
| Work priorities | Scheduling and request follow-up, preserving drafts and availability/confirmation rules | Cargo identity, selected work site, allowed transitions, registration/review and scanning fallback |
| Roles/entitlements | Current Services role/module/subscription/write context; request and appointment reads/writes stay independent | Current Logistics role/module/subscription/location grants plus centralized financial policy |
| Finance | Existing invoice and receipt presentation. All five current Services roles have billing read roles, subject to remaining access checks. Do not impose a blanket hidden-finance STAFF/VIEWER rule. | STAFF financial access is bounded by the existing reviewed assigned-site and complete Parcel-only Invoice policy. No business-wide financial totals/links/amounts from Services components. |
| Navigation | Appointments combines bookings and follow-up; request history remains available under its existing condition | Parcels, shipments, manifests, tracking and operational tools under their existing gates |

Shared visual identity includes the existing mark, semantic colors, typography,
spacing, controls, focus treatment, surfaces and light/dark intent. Shared
appearance never grants access or establishes equal data availability.

## Boundaries that components must preserve

- Resolve the active Business and membership with existing server helpers; scope
  every tenant-owned read/write. Presentation visibility is not authorization.
- Request-only Services plans may read/follow up requests without appointment
  rows or appointment creation/details. Appointment-only access must not reveal
  request rows/history. Owner/admin/staff management and accountant/viewer reads
  follow current source; subscription restrictions still remove writes.
- Services request classification is supplied by the existing projection. Do
  not infer a Client relationship in the browser, create a client while rendering,
  or show preferred request time as a scheduled appointment.
- Preserve Logistics staff financial restrictions, reviewed assignments, selected
  active site and operational grants. A bounded clearance status is not an
  invoice permission, amount, receipt or business-wide financial summary.
- Keep invoice lifecycle, payments, credits/refunds, review and Logistics financial
  clearance distinct. Do not calculate settlement in a reusable badge/component.
- Keep public booking customer-facing and separate from staff scheduling;
  preserve inline client drafts, booking rules and confirmation operations.
- Preserve typed/pasted/keyboard scanning alongside any Logistics camera option.

Authoritative references: [Services appointments](../../services_unified_appointments.md),
[Business Settings](../../unified_business_settings.md),
[invoice/payment vocabulary](../../invoice_payment_terminology.md),
[Logistics location access](../../logistics_location_access.md),
[Logistics financial policy](../../logistics_financial_access.md), and
[Logistics mobile UX](../../MOTIONMATE_LOGISTICS_MOBILE_UX.md).
Recheck source before a future integration; historical reports are not current
authorization or proof of runtime behavior.

## Change impact in Step 5

Only a Services lab demonstration imports the new executable design-system
sources. The existing Step 4 dashboard is a frozen reference and no production
consumer imports them. Shared application templates, assets and navigation,
Services business logic and all Logistics files remain untouched. Logistics
policy was source-reviewed to document boundaries; no Logistics browser or
runtime regression pass is claimed.

A future shared production change must identify consumers in both verticals,
record role/module/subscription/location effects and validate both. A
Services-only redesign requires a Services-only integration boundary and proof
that Logistics presentation, assets and authorization remain unchanged. Design
approval alone cannot authorize either implementation.
