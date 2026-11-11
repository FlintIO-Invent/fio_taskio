# Motionmate Project Instructions for Codex

## Current architecture

Motionmate is one existing Django multi-tenant SaaS application with two distinct business verticals:

- **Motionmate Services** (`Business.vertical = SERVICE`): CRM and client management, internal and online bookings, appointments, invoicing, and service business operations.
- **Motionmate Logistics** (`Business.vertical = LOGISTICS`): parcel registration and management, shipments and manifests, locations and staff access, tracking, logistics invoicing, and operational workflows.

Both verticals share platform infrastructure and the Phoenix Bootstrap UI foundation. Their business logic, permissions, navigation, and user journeys remain distinct.

- The internal Django package is `taskio`. Installed project apps are `apps.accounts`, `apps.businesses`, `apps.crm`, `apps.appointments`, `apps.billings`, and `apps.logistics`.
- `accounts.TaskIOUser` is the custom user model. `Business` is the tenant/workspace; `BusinessUser` holds membership and role. Registration, onboarding, current-business resolution, subscription/module access, and tenant-scoped CRM and billing already exist.
- Use the existing current-business resolver and membership checks. Legacy multi-workspace memberships are supported internally; the current MVP does not expose a workspace switcher.
- Reuse existing `Client`, `Lead`, `ServiceCategory`, `BusinessService`, `ActivityLog`, `Appointment`, `Invoice`, and `InvoiceLine` models. Requests remain `Lead` rows with `lead_type = REQUEST`; the Services Appointments workspace combines existing appointments and eligible unlinked requests without creating replacement records.
- `ServiceCategory` has a nullable business relationship and business-scoped lookup. Preserve historical null-business records and existing compatibility behavior; do not make categories globally available across tenants.
- Business Settings handles current workspace and invoice defaults. `SaaSUserProfile` and legacy fallback values remain for compatibility; do not remove, copy, or reinterpret them as part of UI work.

## Scope and preservation

- Read the relevant models, views/services, forms, templates, and project documentation before changing behavior. Historical documentation may lag the code; flag discrepancies rather than restoring obsolete architecture.
- Make small, safe, incremental changes. Preserve existing architecture, models, tenant isolation, permissions, integrations, and operational behavior outside the explicitly requested change. Do not modify unrelated files or existing user edits.
- Never assume a Services change should also apply to Logistics, or vice versa. Keep vertical-specific changes scoped to that vertical.
- Before changing a shared component, assess both verticals: consumers, navigation, role/module/subscription gates, data contracts, and affected workflows. Record the impact and verify the relevant states for each vertical.
- Use **Motionmate** as the canonical customer-facing name. Preserve internal Django package/app/model names, database identifiers, stored enum values, migration history, and compatibility routes; branding is not authorization to rename internals.
- Do not create duplicate CRM or billing apps or replacement models where existing ones can be extended. Do not reuse the removed `CompanyProfile` migration path.
- Do not change application data, create or apply migrations, deploy, push, or modify external services without explicit authorization for those actions. Setup commands and historical rollout instructions are not authorization. Never reset or seed an ordinary local, staging, production, or Test Lab database automatically.
- For explicitly authorized schema work on existing records: add new business relationships as nullable, backfill through data migrations, then enforce non-null constraints only after verification. Do not weaken existing non-null constraints. Any remaining profile-to-Business transition must be incremental and explicitly scoped.

## Workflow contracts

- Scope tenant-owned reads and writes to the resolved active Business. Preserve server-side role, membership, capability, subscription, quota, and location-access checks; hiding UI controls is not authorization.
- Preserve named routes, HTTP methods, query parameters, form field names/prefixes, CSRF tokens, hidden operation/retry keys, DOM hooks, validation errors, and return navigation when changing presentation.
- Preserve drafts during inline client creation, booking availability and confirmation rules, and the distinction between requests and scheduled appointments.
- Keep invoice lifecycle, recorded payments, credits/refunds, accounting review, and Logistics financial clearance distinct. Reuse authoritative billing services and presentation; do not calculate or infer settlement in the UI. Customer invoicing and platform subscription billing are separate concerns.
- Preserve Logistics work-location grants, permitted status transitions, registration/review safeguards, and typed/pasted/keyboard-scanner fallback when camera scanning is available.
- Preserve CSV import steps: Upload → Validate → Preview → Confirm → Result, with server-authoritative previews, tenant isolation, atomic execution, and retry protection.

## Phoenix and UI/UX rules

- Phoenix **1.23.0** is the existing UI foundation. Retain it; do not replace it or introduce a new frontend framework as part of routine UI work.
- Treat `design_references/phoenix/` as a **read-only, Git-ignored component library**. Consult its examples and source; do not edit, build into, or force-add it to Git. If absent in another checkout, report that limitation rather than inventing its contents.
- Prefer existing Phoenix components, Bootstrap utilities, Django template inheritance, and reusable includes over new frontend dependencies or duplicated custom implementations.
- Application templates live in `src/templates/`; application assets live in `src/static/`. `src/staticfiles/` is collected output. Preserve local Phoenix patches and the existing asset-loading order; do not overwrite application assets with reference copies.
- The public site currently has separate Silicon assets under `src/static/public_site/`. Keep shared Motionmate branding consistent without replacing that theme or mixing its CSS into the Phoenix workspace unless explicitly requested.
- Reuse existing theme tokens and component conventions for typography, colors, spacing, icons, and interaction states. Allow vertical-specific operational layouts while keeping shared branding coherent.
- Design and verify mobile, tablet, and desktop layouts in existing light/dark modes. Preserve supported RTL behavior when touching shared theme assets. Check long content, empty/error/loading/restricted states, table overflow, and touch targets.
- Maintain semantic headings, labels, accessible control names, keyboard navigation, visible focus, readable contrast, and validation feedback. Respect reduced-motion preferences; use animation only to clarify interaction.

## Verification and documentation

- Use the project environment (`.venv/bin/python`) for Django commands. Choose checks appropriate to the change; documentation-only edits need diff/consistency checks, not database or browser runs.
- Run data-writing tests and browser fixtures only in an authorized disposable test environment. Identify the target settings and database before execution; never use tests as permission to alter application data or contact live providers.
- For UI changes, verify actual browser behavior at representative mobile/tablet/desktop widths and light/dark states. Shared changes need Services and Logistics coverage, including affected permissions and workflows.
- Report what changed, what was preserved, checks performed, and remaining limitations. Distinguish source inspection, isolated automated tests, browser evidence, and actual runtime/provider verification.
- Consult [Services appointments](docs/services_unified_appointments.md), [Business Settings](docs/unified_business_settings.md), [service pricing/imports](docs/service_pricing_and_imports.md), [invoice/payment vocabulary](docs/invoice_payment_terminology.md), [Logistics location access](docs/logistics_location_access.md), and [Logistics mobile UX](docs/MOTIONMATE_LOGISTICS_MOBILE_UX.md) as relevant. Treat [development workflow](docs/DEVELOPMENT_WORKFLOW.md) and README release notes as historical where they disagree with verified code; deployment still requires explicit authorization.
