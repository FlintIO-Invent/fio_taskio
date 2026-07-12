# MotionMate User Testing Plan

## Purpose

This plan covers the current MotionMate private-testing product in this repository. It is intentionally limited to the features that already exist and are safe to evaluate.

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
- Service CSV imports
- Public request form per business slug
- Public booking request form per business slug
- Booking settings and weekly availability
- Appointment creation, editing, status changes, and request linking
- Invoice creation, editing, and status changes
- Invoice service type selection for new versus saved services
- Invoice PDF download
- Invoice email with PDF attachment
- Subscription and plan visibility
- Plan/module gating for invoicing, appointments, public requests, and public booking
- Transactional email smoke testing
- Admin support smoke testing

## Out of scope

- Memberships
- Stripe billing
- Online payment collection
- Background jobs, scheduled reminders, and webhooks
- Automatic appointment confirmation without staff review
- Major new product features

Use [docs/APPOINTMENT_STAGING_QA.md](/home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio/docs/APPOINTMENT_STAGING_QA.md) as the deeper regression gate for appointment, booking, and appointment-to-invoice changes.

## Test data and accounts

Prepare these before testing:

- A PostgreSQL-backed environment with migrations already applied
- One brand-new owner email for business registration
- One invited admin or staff email
- One invited accountant or viewer email
- One Django superuser for `/admin/`
- One active default trial plan
- One plan that allows invoicing, appointments, public request forms, and public booking
- One business slug to test public request and public booking forms
- At least one bookable service and one weekly availability block

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
- `/accounts/password-reset/`
- `/crm/public_request/<business_slug>/`
- `/crm/thanks/`
- `/book/<business_slug>/`
- `/book/<business_slug>/thanks/`

Workspace routes:

- `/crm/agent/dashboard/`
- `/businesses/settings/`
- `/businesses/settings/booking/`
- `/businesses/subscription/`
- `/businesses/team/`
- `/crm/staff/clients/`
- `/crm/staff/clients/create/`
- `/crm/staff/leads/`
- `/crm/staff/leads/create/`
- `/crm/settings/service-categories/`
- `/crm/settings/services/`
- `/crm/settings/services/import/`
- `/appointments/`
- `/appointments/create/`
- `/appointments/create/from-request/<lead_id>/`
- `/billings/`
- `/billings/create/`
- `/billings/from-client/<client_id>/`
- `/billings/from-appointment/<appointment_id>/`

Support route:

- `/admin/`

Important note:

- Public testers should use `/crm/public_request/<business_slug>/`.
- The generic `/crm/public_request/` route is not the external public entrypoint. It only redirects when a current workspace is already known in session.
- Public booking testers should use `/book/<business_slug>/`.
- `/accounts/customer_registration` is now a legacy compatibility route and should redirect users to business registration.

## First deployment smoke pass

Run this quick pass on the deployed PostgreSQL-backed app before the deeper UT-01 through UT-18 walkthrough.

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
- Verify `Staff` can work with CRM, service-request, and appointment flows but not billing, settings, or subscription management
- Verify `Accountant` can reach client and invoice flows and view appointments/service requests, but cannot manage service requests or appointments
- Verify `Viewer` remains read-only where allowed, including invoice PDF access

Expected result:

- Role boundaries match the current MotionMate permission design

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
- Confirm the service can be marked bookable online
- Import services from CSV when using the import flow
- Confirm both appear only inside the active workspace

Expected result:

- Service categories and services behave as business-scoped setup data for invoicing, appointment, request, and booking workflows

### G. Public request flow

Checks:

- Open `/crm/public_request/<business_slug>/`
- Submit a valid `REQUEST`
- Submit a valid `INTEREST` if that path is enabled in the form
- Confirm client upsert behavior is safe and does not overwrite richer existing data incorrectly
- Confirm plan gating works when the workspace should or should not expose the form

Expected result:

- Public request intake works for the active business slug and remains protected by current plan rules

### H. Public booking flow

Checks:

- Open `/businesses/settings/booking/`
- Confirm booking settings can be saved
- Add at least one weekly availability block
- Confirm at least one active service is bookable online
- Open `/book/<business_slug>/`
- Submit a booking request for an available time
- Confirm redirect to `/book/<business_slug>/thanks/`
- Confirm a service request and matching client are created for the correct business
- Confirm plan gating blocks the public booking route only when expected

Expected result:

- Public booking creates a reviewable service request and remains protected by plan, service, booking setting, and availability gates

### I. Appointment flow

Checks:

- Open `/appointments/`
- Create an appointment manually
- Create an appointment from a service request
- Update an appointment
- Change appointment status
- Confirm invalid times are blocked
- Confirm appointment visibility from dashboard, client detail, and service request detail pages

Expected result:

- Appointment scheduling works and remains scoped to the current business

### J. Billing flow

Checks:

- Create an invoice from a client
- Select a saved business service
- Add a new service line with the service type dropdown
- Save an on-the-fly invoice line as a saved service
- Verify totals update correctly
- Download the invoice PDF
- Email the invoice PDF to the client
- Move the invoice through `DRAFT`, `SENT`, and `PAID` as allowed
- Confirm staff and viewer roles cannot perform restricted invoice actions

Expected result:

- Billing works on the deployed app and respects tenant scoping, role permissions, service selection, PDF generation, and email delivery

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
- `/appointments/`
- `/billings/`
- `/businesses/subscription/`
- `/businesses/team/`

Checks:

- Verify `Owner` can access everything in current scope
- Verify `Admin` can manage clients, leads, services, appointments, billing, and team
- Verify `Staff` can manage clients, service requests, and appointments but not billing, settings, team, or subscription
- Verify `Accountant` can manage clients and billing, view service requests and appointments, and avoid lead/appointment management actions
- Verify `Viewer` can view allowed CRM, appointment, invoice, and PDF pages but not management pages

Expected result:

- Permission boundaries match the role rules
- Unauthorized actions are blocked or redirected safely

### UT-08 Business settings and subscription page

Routes:

- `/businesses/settings/`
- `/businesses/settings/booking/`
- `/businesses/subscription/`

Checks:

- Update editable business settings
- Update invoice prefix, start number, currency, locale, and tax defaults
- Update booking settings
- Add and deactivate weekly availability
- Review current plan details
- Change plans through the current non-Stripe plan selector
- Confirm current trial messaging is accurate

Expected result:

- Workspace settings save successfully
- Plan changes update the subscription record
- Module access reflects the selected plan

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
- Configure online booking fields when needed
- Import services from CSV
- Download the sample CSV

Expected result:

- Services are scoped to the business
- Imported services are usable in invoicing, appointment, and booking flows

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
- `/billings/create/`
- `/billings/from-client/<client_id>/`
- `/billings/from-appointment/<appointment_id>/`
- `/billings/<invoice_id>/`
- `/billings/<invoice_id>/edit/`
- `/billings/<invoice_id>/pdf/`
- `/billings/<invoice_id>/email/`
- `/billings/<invoice_id>/change-status/`

Checks:

- Create an invoice from a client
- Create an invoice from an appointment
- Add service lines from business services
- Add a new service line from the service type dropdown
- Save an on-the-fly service into the service catalog
- Edit a draft invoice
- Download the invoice PDF
- Send the invoice email with PDF attachment
- Change status through valid transitions
- Verify plan gating for invoicing when using a plan without billing access

Expected result:

- Invoice creation and editing work
- Service selection reflects business-scoped services
- PDF and email flows work without exposing internal notes
- Invalid status changes are blocked

### UT-15 Appointments

Routes:

- `/appointments/`
- `/appointments/create/`
- `/appointments/create/from-request/<lead_id>/`
- `/appointments/<appointment_id>/`
- `/appointments/<appointment_id>/edit/`
- `/appointments/<appointment_id>/change-status/`

Checks:

- Create an appointment manually
- Create an appointment from a service request
- Confirm service, client, and staff member must belong to the current business
- Confirm linked service names are snapshotted
- Update appointment details
- Change appointment status
- Confirm accountant and viewer roles are read-only

Expected result:

- Appointment workflows are usable, role-aware, and tenant-scoped

### UT-16 Public booking

Routes:

- `/businesses/settings/booking/`
- `/book/<business_slug>/`
- `/book/<business_slug>/thanks/`

Checks:

- Enable booking requests in booking settings
- Add active weekly availability
- Mark at least one service as bookable online
- Submit a valid public booking request
- Validate minimum notice, booking window, availability, and service validation
- Confirm customer receipt and internal alert email behavior
- Convert or schedule the booking request as an appointment

Expected result:

- Public booking creates a service request and client for the correct business and can flow into appointment scheduling

### UT-17 Transactional email smoke test

Routes and flows:

- `/accounts/password-reset/`
- `/businesses/team/`
- `/crm/public_request/<business_slug>/`
- `/book/<business_slug>/`
- `/appointments/create/from-request/<lead_id>/`
- `/billings/<invoice_id>/email/`

Checks:

- Password reset email uses the expected app URL
- Team invitation email uses the expected app URL
- Public request customer confirmation and internal alert are sent
- Public booking customer receipt and internal alert are sent
- Appointment confirmation is sent when a booking request is scheduled
- Invoice email includes an opening PDF attachment
- Failed sends are logged safely without exposing secrets

Expected result:

- Current transactional email flows work with the configured email backend

### UT-18 Admin support smoke test

Route:

- `/admin/`

Checks:

- Confirm admin login works for the superuser
- Confirm core models appear
- Confirm businesses, plans, subscriptions, team memberships, invitations, clients, leads, services, appointments, and invoices are manageable

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
8. Booking settings and availability
9. Public request form
10. Public booking form
11. Clients
12. Service requests
13. Appointments
14. Invoices
15. Transactional email pass
16. Role-permission pass
17. Admin smoke test
