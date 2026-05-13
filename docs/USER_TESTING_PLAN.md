# TaskIO User Testing Plan

## Purpose

This document captures the current user-facing routes and the most important user tests for the existing TaskIO SaaS application.

Based on the codebase, the product currently supports:

- A public landing page
- A public lead and service request form
- Internal agent login
- Internal CRM workflows for leads and clients
- Invoice creation and status tracking
- Workspace and billing settings
- Django admin access

## Current URL Inventory

### Public routes --- URL (https://fio-taskio.onrender.com)

| URL | Access | Purpose | Notes |
| --- | --- | --- | --- |
| `/` | Public | Redirects to home | Redirects to `/home/` |
| `(https://fio-taskio.onrender.com)/home/` | Public | Landing page | Main marketing and entry page |
| `/crm/public_request/` | Public | Public lead or service request form | Accepts service requests and general interest submissions |
| `/crm/thanks/` | Public | Submission success page | Shown after public form submission |
| `/accounts/customer_registration` | Public | Customer account registration | Creates a non-staff user account and SaaS profile (Not for you) |
| `/accounts/agent_login` | Public | Internal agent login | Only staff or superusers are allowed through this flow (Not for you) |

### Internal authenticated routes

| URL | Access | Purpose | Notes |
| --- | --- | --- | --- |
| `/crm/agent/dashboard/` | Authenticated | Agent dashboard | Shows invoice-focused dashboard metrics |
| `/accounts/profile` | Authenticated | Workspace settings | Has `basic`, `workspace`, and `invoice` sections |
| `/crm/staff/leads/` | Authenticated | Lead list | Supports filtering by status, type, and search |
| `/crm/staff/leads/create/` | Authenticated | Create lead | Intended for staff lead entry |
| `/crm/staff/leads/<lead_id>/` | Authenticated | Lead detail | Direct detail page exists |
| `/crm/staff/clients/` | Authenticated | Client list | Supports search, district filter, active filter |
| `/crm/staff/clients/create/` | Authenticated | Create client | Main client creation form |
| `/crm/staff/clients/<client_id>/` | Authenticated | Client detail | Includes invoice creation CTA |
| `/crm/staff/clients/<client_id>/edit/` | Authenticated | Edit client | Updates the client record |
| `/crm/staff/clients/all/` | Authenticated | Full active-client detail view | Shows all active clients in expanded format |
| `/billings/` | Authenticated | Invoice list | Supports status filtering |
| `/billings/from-client/<client_id>/` | Authenticated | Create invoice from client | Creates a draft invoice for a client |
| `/billings/<invoice_id>/` | Authenticated | Invoice detail | Shows lines, totals, notes, and status actions |
| `/billings/<invoice_id>/edit/` | Authenticated | Edit draft invoice | Only available for draft invoices |
| `/billings/<invoice_id>/change-status/` | Authenticated, POST | Change invoice status | Supports valid transitions only |

### Admin route

| URL | Access | Purpose | Notes |
| --- | --- | --- | --- |
| `/admin/` | Admin only | Django admin | Admin back office for models and users (Not for you) |

## Main User Roles

### 1. Public prospect or customer

What they can do:

- View the landing page
- Submit a service request
- Submit a general expression of interest
- Register a customer account

### 2. Internal agent or operations staff

What they can do:

- Log in to the internal workspace
- View invoice dashboard metrics
- Create and review leads
- Create, search, review, and update clients
- Create invoices from clients
- Edit draft invoices
- Move invoices through draft, sent, paid, and cancelled states

### 3. Workspace owner or back-office operator

What they can do:

- Update account basic info
- Update workspace and billing details
- Update invoice defaults like currency, due days, and branding color

### 4. System admin (Not for you)

What they can do:

- Use Django admin for direct model management and user administration

## Suggested Test Setup

Before running user tests, prepare:

- One staff user for agent login
- One superuser for `/admin/`
- Seeded `ServiceCategory` records so the public request form has category choices
- One or two sample clients for invoice creation tests
- A clean database or a known test dataset

Recommended sample accounts:

- Staff agent: `agent@example.com`
- Customer account: `customer@example.com`
- Admin: `admin@example.com`

## User Testing Plan

## A. Public Experience

### UT-01 Landing page

Goal:
Confirm a new visitor understands the product entry point and can reach the next action.

Steps:

1. Open `/home/`.
2. Confirm the page loads without missing assets or layout breaks.
3. Confirm the Agent Login link is visible.
4. Confirm branding and headline content render correctly on desktop and mobile.

Expected result:

- Landing page loads successfully.
- Agent login CTA works.
- No broken images, videos, or CSS.

### UT-02 Public service request submission

Goal:
Verify a visitor can submit a request from the public form.

Steps:

1. Open `/crm/public_request/`.
2. Submit a valid form with `lead_type = REQUEST`.
3. Confirm redirect to `/crm/thanks/`.
4. Verify the submitted contact shows up in internal data where expected.

Expected result:

- Form submits successfully.
- Success page appears.
- Internal staff can follow up on the request.

### UT-03 Public interest lead submission

Goal:
Verify a visitor can submit a non-request lead.

Steps:

1. Open `/crm/public_request/`.
2. Submit a valid form with `lead_type = INTEREST`.
3. Confirm redirect to `/crm/thanks/`.
4. Log in as staff and check `/crm/staff/leads/`.

Expected result:

- The interest submission is stored as a lead.
- Staff can find it in the lead list.

### UT-04 Public form validation

Goal:
Confirm validation and error states are usable.

Steps:

1. Submit the public request form with missing required fields.
2. Submit with malformed email and phone values if validation exists.
3. Retry with corrected data.

Expected result:

- Errors are shown clearly.
- Corrected submission succeeds.

### UT-05 Customer account registration

Goal:
Verify a public user can create an account.

Steps:

1. Open `/accounts/customer_registration`.
2. Submit a valid new user.
3. Retry with a duplicate email.

Expected result:

- A new account is created on valid submission.
- Duplicate email is blocked.
- Success messaging is shown.

## B. Agent Access and Navigation

### UT-06 Internal agent login

Goal:
Verify only staff users can enter the internal workspace.

Steps:

1. Open `/accounts/agent_login`.
2. Sign in with a staff account.
3. Sign in with a non-staff customer account.
4. Sign in with invalid credentials.

Expected result:

- Staff login succeeds and lands on `/crm/agent/dashboard/`.
- Non-staff login is rejected.
- Invalid credentials show a clear error.

### UT-07 Internal navigation smoke test

Goal:
Verify the main sidebar paths are reachable.

Steps:

1. From the dashboard, open workspace settings.
2. Open clients.
3. Open leads.
4. Open invoices.

Expected result:

- Every linked screen loads successfully.
- No dead-end navigation paths appear in the main operational flow.

## C. Lead Management

### UT-08 Create a lead internally

Goal:
Verify staff can create a lead manually.

Steps:

1. Open `/crm/staff/leads/create/`.
2. Submit a valid lead.
3. Confirm it appears in `/crm/staff/leads/`.

Expected result:

- Lead is saved.
- Lead is searchable and visible in the lead list.

### UT-09 Filter and search leads

Goal:
Verify lead list filtering works.

Steps:

1. Open `/crm/staff/leads/`.
2. Filter by `REQUEST`.
3. Filter by `INTEREST`.
4. Filter by status.
5. Search by name, email, and phone.

Expected result:

- Results match the selected filters and search query.

### UT-10 Review lead details

Goal:
Verify lead details are readable and useful for follow-up.

Steps:

1. Open a known lead detail route directly at `/crm/staff/leads/<lead_id>/`.
2. Review contact info, category, address, and message.

Expected result:

- Lead detail page displays complete submission context.

## D. Client Management

### UT-11 Create a client

Goal:
Verify staff can create a client record manually.

Steps:

1. Open `/crm/staff/clients/create/`.
2. Fill in basic details, relationship details, notes, and location.
3. Submit the form.

Expected result:

- Client is saved and appears in `/crm/staff/clients/`.

### UT-12 Search and filter clients

Goal:
Verify CRM list filtering works for active client management.

Steps:

1. Open `/crm/staff/clients/`.
2. Search by name, company, email, and phone.
3. Filter by district.
4. Filter by active and inactive.

Expected result:

- The client list responds correctly to search and filter inputs.

### UT-13 Review client details

Goal:
Verify client records provide enough operational detail.

Steps:

1. Open `/crm/staff/clients/<client_id>/`.
2. Review the tabs for basic info, business details, contact info, relationship, and notes.

Expected result:

- All client sections render correctly.
- The record is suitable for sales and service follow-up.

### UT-14 Update a client

Goal:
Verify client edits persist correctly.

Steps:

1. Open `/crm/staff/clients/<client_id>/edit/`.
2. Change status, priority, contact details, and notes.
3. Save and reopen the detail page.

Expected result:

- Updated values are persisted and visible afterward.

## E. Invoice Management

### UT-15 Create invoice from client

Goal:
Verify staff can create a draft invoice from a client.

Steps:

1. Open `/crm/staff/clients/<client_id>/`.
2. Use the Create Invoice action.
3. Confirm redirect to the invoice detail page.

Expected result:

- A draft invoice is created with an auto-generated invoice number.

### UT-16 Edit draft invoice

Goal:
Verify line-item editing and totals calculation.

Steps:

1. Open `/billings/<invoice_id>/edit/` for a draft invoice.
2. Add, update, and remove line items.
3. Add notes.
4. Save.

Expected result:

- Invoice lines persist correctly.
- Subtotal and total update correctly.
- Notes are saved.

### UT-17 Invoice status workflow

Goal:
Verify the invoice lifecycle.

Steps:

1. Move a draft invoice to Sent.
2. Move the same invoice to Paid.
3. Create another draft and cancel it.
4. Attempt an invalid transition if possible.

Expected result:

- Valid transitions work.
- Invalid transitions are blocked.

### UT-18 Invoice list filtering

Goal:
Verify invoice discovery by state.

Steps:

1. Open `/billings/`.
2. Filter by Draft, Sent, Paid, and Cancelled.

Expected result:

- The invoice list reflects the chosen status filter.

## F. Workspace Settings

### UT-19 Update basic workspace info

Goal:
Verify the account owner can update basic profile details.

Steps:

1. Open `/accounts/profile`.
2. Update first name, last name, email, company, phone, and address.
3. Save.

Expected result:

- Changes persist and the success message appears.

### UT-20 Update workspace and billing settings

Goal:
Verify business-facing workspace settings.

Steps:

1. Open `/accounts/profile?section=workspace`.
2. Update workspace name, billing email, support email, website, and tax ID.
3. Save.

Expected result:

- Workspace settings persist.

### UT-21 Update invoice defaults

Goal:
Verify invoice branding and payment defaults.

Steps:

1. Open `/accounts/profile?section=invoice`.
2. Change currency, prefix, due days, accent color, footer note, and payment instructions.
3. Save.

Expected result:

- Settings persist.
- Preview values update correctly.

## G. Admin Back Office

### UT-22 Django admin smoke test

Goal:
Confirm the administrative back office is usable.

Steps:

1. Open `/admin/` with a superuser.
2. Confirm access to users, leads, clients, invoices, and related records.

Expected result:

- Admin login works.
- Core models are manageable in admin.

## High-Priority Risks and Current Gaps

These are important to keep in mind during testing because they appear in the current codebase.

- `REQUEST` submissions on `/crm/public_request/` appear to create or update a client directly and may not persist a lead record first. This is inferred from `public_request()` using `upsert_client_from_lead(Lead(**lead))` without `form.save()` for that branch.
- `/crm/staff/leads/create/` appears to render the wrong form on `GET`. The view uses `PrivateClientForm()` for the page load and `PublicLeadForm()` on submit, so the lead creation page should be tested early.
- The lead list UI has placeholder actions and does not currently link row actions to the existing detail route.
- There is no visible customer self-service login flow beyond registration. Customer accounts are created, but the current login form only permits staff and superusers.
- The dashboard contains some static-looking placeholder sections, so test emphasis should stay on invoice stats and route health rather than chart accuracy unless those charts are explicitly wired later.
- The dashboard layout includes a logout link to `/accounts/employee_login`, but that route is not defined in the current URL configuration.
- Most authenticated views use the default `login_required` behavior, and no custom `LOGIN_URL` setting is present in settings. Direct unauthenticated access to some internal routes should therefore be tested carefully.

## Recommended Testing Order

Run testing in this order to expose the biggest workflow risks quickly:

1. Public request form
2. Agent login
3. Lead creation and lead list
4. Client creation and client update
5. Invoice creation and invoice status flow
6. Workspace settings
7. Django admin

## Success Criteria

The current product is ready for a structured user test if:

- A public visitor can submit interest or request information successfully
- A staff agent can log in and navigate the core CRM screens
- Staff can create and update clients
- Staff can create, edit, and progress invoices
- Workspace settings save reliably
- Admin access works for back-office recovery and support
