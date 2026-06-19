# Clarivo User Testing Plan

## Purpose

This plan covers the current Clarivo MVP that is being prepared for private production testing. It is intentionally limited to the features that already exist and are safe to evaluate.

Private-testing environment rule:

- Use a PostgreSQL-backed deployment before inviting testers.
- SQLite is only a temporary local fallback if a PostgreSQL test database cannot be created during development.

Branch safety rule:

- The live private-test deployment should track `main`.
- Production fixes during the tester cycle should go through `hotfix/*` branches.
- New feature work should stay on `develop` and `feature/*` branches until it passes the release checklist.

## In scope

- Business workspace registration
- Business login
- Invitation-only employee access
- One active workspace per login
- Role permissions
- Tenant-scoped clients
- Tenant-scoped service requests
- Business-specific service categories
- Business-specific services and pricing
- Public request form per business slug
- Invoice creation, editing, and status changes
- Subscription and plan visibility
- Admin support smoke testing

## Out of scope

- Appointments
- Public booking
- Memberships
- Stripe billing
- Major new product features

## Test data and accounts

Prepare these before testing:

- A PostgreSQL-backed environment with migrations already applied
- One brand-new owner email for business registration
- One invited admin or staff email
- One invited accountant or viewer email
- One Django superuser for `/admin/`
- One active default trial plan
- One business slug to test public request forms

Recommended role coverage:

- `Owner`
- `Admin`
- `Staff`
- `Accountant`
- `Viewer`

Before inviting testers:

- Run migrations successfully against PostgreSQL
- Run `check --deploy` with production-style security settings
- Smoke-test the key routes on the PostgreSQL-backed environment

## Route guide

Public and onboarding routes:

- `/home/`
- `/accounts/register-business/`
- `/accounts/login/`
- `/accounts/agent_login`
- `/accounts/invitations/accept/<token>/`
- `/crm/public_request/<business_slug>/`
- `/crm/thanks/`

Workspace routes:

- `/crm/agent/dashboard/`
- `/businesses/settings/`
- `/businesses/subscription/`
- `/businesses/team/`
- `/crm/staff/clients/`
- `/crm/staff/clients/create/`
- `/crm/staff/leads/`
- `/crm/staff/leads/create/`
- `/crm/settings/service-categories/`
- `/crm/settings/services/`
- `/billings/`

Support route:

- `/admin/`

Important note:

- Public testers should use `/crm/public_request/<business_slug>/`.
- The generic `/crm/public_request/` route is not the external public entrypoint. It only redirects when a current workspace is already known in session.
- `/accounts/customer_registration` is now a legacy compatibility route and should redirect users to business registration.

## First deployment smoke pass

Run this quick pass on the deployed PostgreSQL-backed app before the deeper UT-01 through UT-15 walkthrough.

### A. System and admin

Checks:

- Load `/home/`, `/accounts/login/`, and `/admin/`
- Confirm CSS, JS, and favicon assets load
- Confirm no obvious server errors appear on first-page navigation
- Confirm admin login works for the superuser
- Confirm the deployed database already has the expected migrations applied

Expected result:

- The deployed app is reachable, styled correctly, and backed by the migrated PostgreSQL database

### B. Business owner flow

Checks:

- Register a brand-new business from `/accounts/register-business/`
- Confirm the owner is logged in automatically
- Confirm redirect to `/businesses/settings/` or the expected dashboard path
- Confirm `/crm/agent/dashboard/` and `/businesses/subscription/` load

Expected result:

- The owner can onboard successfully and land inside the new workspace

### C. Team flow

Checks:

- Create an invitation from `/businesses/team/`
- Accept the invitation as the invited teammate
- Confirm the invited user lands inside the existing workspace
- Confirm the invited user does not create a second workspace during acceptance

Expected result:

- Invitation-only employee access works and preserves the one-workspace-per-login MVP behavior

### D. Role permissions

Checks:

- Verify `Owner` can access the current full scope
- Verify `Admin` can manage team, CRM, and billing pages
- Verify `Staff` can work with CRM and service-request flows but not subscription management
- Verify `Accountant` can reach client and invoice flows but not lead-management actions
- Verify `Viewer` remains read-only where allowed

Expected result:

- Role boundaries match the current Clarivo permission design

### E. CRM flow

Checks:

- Create a client
- Edit the client safely
- Create a service request from the staff flow
- Convert or update the client safely when the flow calls for it
- Confirm another business cannot see the record

Expected result:

- Client and request data stay tenant-scoped and cross-business leakage is not observed

### F. Services flow

Checks:

- Create a service category
- Create a priced business service
- Confirm both appear only inside the active workspace

Expected result:

- Service categories and services behave as business-scoped setup data for invoicing and request workflows

### G. Public request flow

Checks:

- Open `/crm/public_request/<business_slug>/`
- Submit a valid `REQUEST`
- Submit a valid `INTEREST` if that path is enabled in the form
- Confirm client upsert behavior is safe and does not overwrite richer existing data incorrectly
- Confirm plan gating works when the workspace should or should not expose the form

Expected result:

- Public request intake works for the active business slug and remains protected by current plan rules

### H. Billing flow

Checks:

- Create an invoice from a client
- Select a saved business service
- Add a manual line item
- Verify totals update correctly
- Move the invoice through `DRAFT`, `SENT`, and `PAID` as allowed
- Confirm staff and viewer roles cannot perform restricted invoice actions

Expected result:

- Billing works on the deployed app and respects both tenant scoping and role permissions

## Test scenarios

### UT-01 Business registration

Route:

- `/accounts/register-business/`

Checks:

- Create a new owner and workspace
- Confirm the user is logged in automatically
- Confirm redirect to `/businesses/settings/`
- Confirm a trial subscription is attached when an active default trial plan exists

Expected result:

- Workspace is created successfully
- Owner becomes the active workspace user
- A current business is stored for the session

### UT-02 Business login and logout

Routes:

- `/accounts/login/`
- `/accounts/logout/`

Checks:

- Sign in with the owner account
- Confirm redirect to `/crm/agent/dashboard/`
- Sign out and confirm redirect back to login
- Retry with invalid credentials

Expected result:

- Valid business users can log in
- Invalid credentials are rejected clearly

### UT-03 Legacy customer registration redirect

Route:

- `/accounts/customer_registration`

Checks:

- Open the route directly
- Confirm the user receives a legacy notice
- Confirm redirect to `/accounts/register-business/`

Expected result:

- No standalone customer signup flow is presented

### UT-04 Team invitation creation

Route:

- `/businesses/team/`

Checks:

- Log in as owner
- Create an invitation for a teammate email
- Repeat with an existing pending invitation
- Try the page as a non-owner/non-admin role

Expected result:

- Owner and admin can create or refresh invitations
- Lower roles cannot manage invitations
- Pending invitation token is visible for manual testing

### UT-05 Invitation acceptance for an existing user

Route:

- `/accounts/invitations/accept/<token>/`

Checks:

- Accept the invitation as an existing invited user
- Verify wrong-user protection by signing in as another email first
- Verify already-accepted and expired invitation behavior

Expected result:

- The invited user joins the workspace
- Wrong authenticated users are blocked cleanly
- Invitation state handling is clear

### UT-06 Invitation acceptance for a brand-new user

Route:

- `/accounts/invitations/accept/<token>/`

Checks:

- Open an invitation for an email that does not already exist
- Create the account from the invitation page
- Confirm automatic login and workspace join

Expected result:

- The account is created
- The membership is attached to the invited business
- Redirect lands on `/crm/agent/dashboard/`

### UT-07 Role permissions

Routes to sample:

- `/crm/staff/leads/`
- `/crm/staff/clients/`
- `/billings/`
- `/businesses/subscription/`
- `/businesses/team/`

Checks:

- Verify `Owner` can access everything in current scope
- Verify `Admin` can manage clients, leads, billing, and team
- Verify `Staff` can manage clients and service requests but not subscription
- Verify `Accountant` can access billing but not lead management
- Verify `Viewer` can view billing where allowed but not management pages

Expected result:

- Permission boundaries match the role rules
- Unauthorized actions are blocked or redirected safely

### UT-08 Business settings and subscription page

Routes:

- `/businesses/settings/`
- `/businesses/subscription/`

Checks:

- Update editable business settings
- Review current plan details
- Change plans through the current non-Stripe plan selector
- Confirm current trial messaging is accurate

Expected result:

- Workspace settings save successfully
- Plan changes update the subscription record
- Appointments, memberships, and public booking remain clearly presented as later modules

### UT-09 Service categories

Routes:

- `/crm/settings/service-categories/`
- `/crm/settings/service-categories/create/`

Checks:

- Create a business-specific category
- Edit it
- Archive it
- Confirm it only appears for the current workspace

Expected result:

- Category records stay tenant-scoped
- Archived categories stop appearing where expected

### UT-10 Business services and prices

Routes:

- `/crm/settings/services/`
- `/crm/settings/services/create/`
- `/crm/settings/services/import/`

Checks:

- Create a business service with price and category
- Edit service pricing
- Import services from CSV
- Download the sample CSV

Expected result:

- Services are scoped to the business
- Imported services are usable in invoicing flows

### UT-11 Clients

Routes:

- `/crm/staff/clients/`
- `/crm/staff/clients/create/`
- `/crm/staff/clients/<client_id>/`
- `/crm/staff/clients/<client_id>/edit/`

Checks:

- Create a client
- Edit the client
- Search and filter clients
- Confirm another workspace user cannot reach the record

Expected result:

- Client CRUD works
- Client visibility stays inside the active workspace

### UT-12 Service requests

Routes:

- `/crm/staff/leads/`
- `/crm/staff/leads/create/`
- `/crm/staff/leads/<lead_id>/`
- `/crm/staff/leads/<lead_id>/edit/`
- `/crm/staff/leads/<lead_id>/convert-to-client/`

Checks:

- Create an internal service request
- Edit its details and status
- Convert the request to a client when appropriate
- Create an invoice from a matched lead when applicable

Expected result:

- Lead and request workflows remain tenant-scoped
- Conversion and invoice handoff flows work

### UT-13 Public request form

Route:

- `/crm/public_request/<business_slug>/`

Checks:

- Open the business-specific public form
- Submit a valid `REQUEST`
- Confirm redirect to `/crm/thanks/`
- Confirm client creation or update happens for request submissions
- Submit a valid `INTEREST`
- Confirm it stays as a lead without forced client creation
- Validate required-field errors

Expected result:

- Public request flow works for the testing plan
- The form is tied to the correct business slug
- Plan gating blocks the form only when intended

### UT-14 Invoices

Routes:

- `/billings/`
- `/billings/from-client/<client_id>/`
- `/billings/<invoice_id>/`
- `/billings/<invoice_id>/edit/`
- `/billings/<invoice_id>/change-status/`

Checks:

- Create an invoice from a client
- Add service lines from business services
- Edit a draft invoice
- Change status through valid transitions
- Verify plan gating for invoicing when using a plan without billing access

Expected result:

- Invoice creation and editing work
- Service selection reflects business-scoped services
- Invalid status changes are blocked

### UT-15 Admin support smoke test

Route:

- `/admin/`

Checks:

- Confirm admin login works for the superuser
- Confirm core models appear
- Confirm businesses, memberships, invitations, plans, clients, leads, and invoices are manageable

Expected result:

- Admin remains available as a support back office

## Suggested smoke-test order

1. Business registration
2. Business login
3. Subscription page
4. Team invitation
5. Invitation acceptance
6. Service categories
7. Business services
8. Public request form
9. Clients
10. Service requests
11. Invoices
12. Role-permission pass
13. Admin smoke test
