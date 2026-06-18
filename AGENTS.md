# Clarivo Project Instructions for Codex

This is an existing Django project currently using the internal package name `taskio`. The product is being renamed from TaskIO to Clarivo.

## Existing structure

Installed project apps include:

- apps.accounts
- apps.crm
- apps.billings

The project uses a custom user model:

- accounts.TaskIOUser

There is an existing user-level profile model:

- SaaSUserProfile

There are existing CRM models:

- Lead
- Client
- ServiceCategory
- ActivityLog

There are existing billing models:

- Invoice
- InvoiceLine

Service requests are currently represented by Lead rows where `lead_type = REQUEST`.

## Important architectural direction

Clarivo is becoming a multi-tenant SaaS.

- Business is the tenant/workspace.
- BusinessUser links users to businesses.
- A user may belong to one or more businesses.
- CRM and billing data must belong to a Business.
- Users must only see data for their active Business.

## Important constraints

- Do not rename the internal Django package `taskio` yet.
- Do not create duplicate CRM or billing apps.
- Do not create new Client, Lead, Invoice, or InvoiceLine models if existing ones can be extended.
- Do not reuse the old removed CompanyProfile migration path.
- Do not make broad refactors.
- Make small, safe, incremental changes.
- Add nullable business foreign keys first when touching existing data.
- Use data migrations for backfilling existing records.
- Only make business foreign keys non-null after backfilling.
- Keep ServiceCategory global for now unless explicitly told otherwise.
- Move workspace and invoice defaults from SaaSUserProfile to Business gradually, not all at once.

## Current priority

1. Visible branding cleanup.
2. Add Business and BusinessUser.
3. Add active/current business logic.
4. Add business registration and onboarding.
5. Scope CRM data to Business.
6. Scope billing data to Business.
7. Clean up old user-level workspace assumptions.