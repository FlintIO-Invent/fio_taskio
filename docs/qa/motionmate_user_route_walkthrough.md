# MotionMate User Route Walkthrough

Original walkthrough date: 2026-06-26

Repository refresh date: 2026-07-12

## Summary

This document records a role-based route walkthrough against the MotionMate Django app using an isolated SQLite database and local in-memory email backend. The walkthrough covered public visitor routes, workspace roles, tenant isolation, and the public booking request to appointment to invoice workflow.

The capability notes have been refreshed to match the current repository state: appointments, public booking, booking settings, availability, invoice PDFs, invoice email, service imports, and signup payment setup are active repository features. Memberships, customer portal, webhook-driven subscription activation, background jobs, and instant auto-confirmed bookings remain out of active scope.

Overall result: 118 of 118 route/workflow checks matched the expected status codes after disabling the test harness HTTPS redirect so requests reached the actual view logic.

No application behavior was changed. No migrations were created. No real user, profile, business, client, lead, appointment, invoice, or external email was touched.

## Current SaaS Product Capability Map

MotionMate currently supports one active workspace in session on top of a multi-tenant `Business` and `BusinessUser` model. A user can have memberships in more than one business, but the MVP still has no exposed workspace switcher. The product can be used as an operations workspace for service businesses that need public intake, booking requests, customer management, appointment scheduling, invoicing, PDF generation, and email notifications.

| Product area | What can be done now | Primary roles |
| --- | --- | --- |
| Business registration | Create a new owner account, business workspace, owner membership, trial subscription record, and SaaS profile defaults. | Public visitor, owner |
| Business login/logout | Sign in with email/password, attach the active business from membership, and enter the dashboard. | All workspace users |
| Workspace setup | Create or finish workspace setup when a user has no current business. | Owner |
| Business settings | Manage business name, contact details, address, country, currency, timezone, locale, tax label/rate, and invoice numbering defaults. | Owner, admin |
| Team management | View team members, invite users, assign roles, and accept invitations. | Owner, admin |
| Plan/module access | Select or inspect plan/module flags that control invoicing, appointments, public request form, and public booking access. | Owner |
| Dashboard/reporting | View workspace metrics for clients, service requests, public booking review, appointments, invoices, paid totals, unpaid totals, and recent follow-ups. | All roles, with role/module-specific visibility |
| Service categories | Create, edit, list, and archive service categories inside a workspace. | Owner, admin |
| Business services | Create, edit, list, archive, and CSV-import services with prices, tax rates, online bookability, default duration, booking buffer, public description, and manual confirmation flag. | Owner, admin |
| Public request form | Let public visitors submit general service requests or interest leads for a specific business. Service requests can auto-create or update a client. | Public visitor |
| Public booking form | Let public visitors choose a bookable service, preferred date/time, contact details, location, and notes. The form creates a service request and client, then sends local notification emails. | Public visitor |
| Booking settings | Enable/disable public booking, set default duration, minimum notice, maximum days ahead, buffer time, confirmation mode, public instructions, cancellation text, and reschedule text. | Owner, admin |
| Weekly availability | Add and deactivate business availability blocks used by the public booking validator. | Owner, admin |
| Clients/CRM | Create, list, search, filter, view, and edit clients with contact, business, relationship, address, communication, consent, notes, priority, status, source, and assignment fields. | Owner, admin, staff, accountant; viewer read-only |
| Service requests/leads | Create, list, filter, search, view, and edit leads/service requests. Convert service requests to clients when required. | Owner, admin, staff; accountant/viewer read-only |
| Appointments | Create appointments manually or from service requests, view appointment lists/details, edit appointments, assign staff, track location/notes, and change scheduled appointments to completed/cancelled/no-show. | Owner, admin, staff; accountant/viewer read-only |
| Appointment confirmations | Send an appointment confirmation email when a public booking request is turned into a confirmed appointment. | Staff/owner/admin via appointment confirmation flow |
| Invoices | Create invoices from clients or appointments, add line items from business services, view/list/edit draft invoices, change allowed invoice statuses, and scope invoices to the current business. | Owner, admin, accountant; viewer read-only |
| Invoice PDFs | Generate and download invoice PDFs using business branding/contact details, client information, appointment context, line items, totals, and notes. | Owner, admin, accountant, viewer |
| Invoice email | Email an invoice with PDF attachment through the configured email backend and record email metadata/count. | Owner, admin, accountant |
| Notifications | Send business invitations, public booking receipt emails, internal booking notifications, appointment confirmations, and invoice emails through templated email helpers. | System-triggered |
| Tenant isolation | Keep clients, leads, appointments, services, invoices, settings, and route lookups scoped to the current business. | All roles |

Current known non-capabilities or held areas:

- Memberships are not active product scope.
- Customer portal, in-app plan-change checkout, SaaS billing automation, and webhooks are not connected.
- Public booking is request-first/manual confirmation, not instant auto-confirmation.
- The MVP still uses first active membership fallback when a user has multiple businesses; there is no exposed workspace switcher yet.

## Environment

| Item | Value |
| --- | --- |
| Repository | `/home/mzero/main/repo/fio_projects/caribbean_automated_systems/fio_taskio` |
| Django app DB used for walkthrough | `/tmp/motionmate_route_walkthrough.sqlite3` |
| Email backend | `django.core.mail.backends.locmem.EmailBackend` |
| Test business slug | `flintio-demo-qa` |
| Public booking date used | `2026-06-30` |
| HTTPS redirect note | First harness pass returned 301s to `https://testserver/...`; route checks were rerun with `SECURE_SSL_REDIRECT=False` so view permissions and workflow logic could be exercised. |

## Data Setup

The expected `seed_flintio_demo_data` management command is not available in this checkout:

- `python src/manage.py seed_flintio_demo_data --create-demo-owner` returned `Unknown command: 'seed_flintio_demo_data'`.
- `src/apps/businesses/management/commands/` contains only `__pycache__`, no `.py` command source files.

Because the seed command source is missing, I used direct ORM setup in the isolated SQLite QA database only. All fake data used `[DEMO]` labels and belonged to `flintio-demo-qa` or `other-tenant-qa`.

Seeded QA data included:

- A full-access MotionMate plan with invoicing, appointments, public request, and public booking enabled.
- One business: `[DEMO] FlintIO Demo QA`.
- One separate tenant: `[DEMO] Other Tenant QA`.
- Owner, admin, staff, accountant, and viewer users.
- Booking settings with public booking enabled.
- Weekday availability from 08:00 to 17:00.
- Bookable online services.
- Clients, service requests, public booking requests, appointments, invoices, and invoice lines.

## Test Accounts And Roles

| Role | Email | Expected access shape |
| --- | --- | --- |
| Owner | `owner.qa@flintio.example` | Full workspace access, business settings, subscription, team, services, CRM, appointments, invoices |
| Admin | `admin.qa@flintio.example` | Workspace operations/settings except subscription |
| Staff | `staff.qa@flintio.example` | CRM and appointment operations, no billing or business settings |
| Accountant | `accountant.qa@flintio.example` | Clients and billing, read-only appointments/service requests, no business settings |
| Viewer | `viewer.qa@flintio.example` | Read-only workspace, clients, service requests, appointments, and invoice/PDF viewing |

## Public Visitor Routes

| Route | Result |
| --- | --- |
| `GET /accounts/login/` | 200 |
| `POST /accounts/login/` owner credentials | 302 to dashboard |
| Anonymous `GET /crm/agent/dashboard/` | 302 to login |
| `GET /crm/public_request/flintio-demo-qa/` | 200 |
| `POST /crm/public_request/flintio-demo-qa/` | 302 to `/crm/thanks/`; created 1 public request lead/client |
| `GET /book/flintio-demo-qa/` | 200 |
| `POST /book/flintio-demo-qa/` | 302 to `/book/flintio-demo-qa/thanks/`; created 1 public booking lead/client |
| `GET /book/flintio-demo-qa/thanks/` | 200 |

Public booking availability gates observed:

- Business must be active.
- Plan must allow `public_booking`.
- `BusinessBookingSettings.booking_enabled` must be true.
- At least one active bookable `BusinessService` must exist.
- At least one active `WeeklyAvailability` row must exist.

If a real URL such as `/book/<business-slug>/` shows "Booking Requests Unavailable", inspect those gates first.

## Role Route Matrix

Status legend: `200` means allowed, `302` means intentionally redirected away, `403` means hard permission denied.

| Route | Owner | Admin | Staff | Accountant | Viewer |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dashboard | 200 | 200 | 200 | 200 | 200 |
| Business settings | 200 | 200 | 403 | 403 | 403 |
| Booking settings | 200 | 200 | 403 | 403 | 403 |
| Subscription | 200 | 403 | 403 | 403 | 403 |
| Team members | 200 | 200 | 403 | 403 | 403 |
| Service categories | 200 | 200 | 302 | 302 | 302 |
| Business services | 200 | 200 | 302 | 302 | 302 |
| Clients list | 200 | 200 | 200 | 200 | 200 |
| Client detail | 200 | 200 | 200 | 200 | 200 |
| Client create | 200 | 200 | 200 | 200 | 302 |
| Service requests list | 200 | 200 | 200 | 200 | 200 |
| Service request detail | 200 | 200 | 200 | 200 | 200 |
| Service request edit | 200 | 200 | 200 | 302 | 302 |
| Appointments list | 200 | 200 | 200 | 200 | 200 |
| Appointment detail | 200 | 200 | 200 | 200 | 200 |
| Appointment create | 200 | 200 | 200 | 302 | 302 |
| Invoices list | 200 | 200 | 302 | 200 | 200 |
| Invoice detail | 200 | 200 | 302 | 200 | 200 |
| Invoice edit | 200 | 200 | 302 | 200 | 302 |
| Invoice PDF | 200 | 200 | 302 | 200 | 200 |

## Tenant Isolation

| Check | Result |
| --- | --- |
| Owner of `flintio-demo-qa` requests other tenant client detail | 404 |
| Owner of `flintio-demo-qa` requests other tenant service request detail | 404 |
| Owner of `flintio-demo-qa` requests other tenant appointment detail | 404 |
| Owner of `flintio-demo-qa` requests other tenant invoice detail | 404 |
| Public booking POST to `flintio-demo-qa` using another tenant's service ID | 200 with form error, created 0 leads |

Tenant scoping behaved correctly in the exercised routes.

## End-To-End Workflow Results

| Workflow step | Result |
| --- | --- |
| Public visitor submits public request form | Passed; 1 public request lead/client created |
| Public visitor submits public booking form | Passed; 1 public booking lead/client created |
| Public booking confirmation emails | Passed; 2 local emails captured: visitor receipt and internal notification |
| Staff confirms appointment from booking request | Passed; appointment `id=3` created |
| Appointment confirmation email | Passed; 1 local email captured |
| Accountant creates invoice from appointment | Passed; invoice `FQA-1001` created |
| Viewer downloads invoice PDF | Passed; `application/pdf`, 3835 bytes |
| Accountant emails invoice | Passed; 1 local email captured, `email_send_count=1` |
| Accountant changes invoice status | Passed; invoice changed to `SENT` |

## End-To-End Product Flows

### 1. New Business Onboarding

1. Public visitor opens `/accounts/register-business/`.
2. Visitor enters owner identity, login credentials, and business details.
3. MotionMate creates the user, business, owner `BusinessUser` membership, default trial subscription when an active plan exists, and legacy SaaS profile defaults.
4. The owner is logged in and redirected into the workspace flow.
5. Owner completes business settings: contact email, phone, country, currency, timezone, locale, tax defaults, invoice prefix/start number, and address.
6. Owner lands on the dashboard and can begin configuring services, booking, team members, clients, and invoices.

### 2. Existing Workspace Login

1. User opens `/accounts/login/`.
2. User submits email and password.
3. MotionMate authenticates the user and resolves their first active business membership or the selected session business.
4. The current business is stored in session as `current_business_id`.
5. User is redirected to `/crm/agent/dashboard/`.
6. Dashboard widgets and navigation are filtered by role permissions and plan/module access.

### 3. Owner/Admin Service Setup

1. Owner or admin opens `/crm/settings/service-categories/`.
2. They create service categories such as septic service, emergency response, or scheduled maintenance.
3. They open `/crm/settings/services/`.
4. They create services with category, price, tax rate, description, online booking flag, default duration, buffer, public description, and manual confirmation behavior.
5. They optionally import services from CSV through `/crm/settings/services/import/`.
6. Services become available to invoices and, when active/bookable, to the public booking form.

### 4. Public Request Intake

1. Public visitor opens `/crm/public_request/<business-slug>/`.
2. Visitor selects request type/category and enters name, company, email, phone, service address, message, and consent.
3. MotionMate creates a `Lead` scoped to that business with `request_source=public_request`.
4. If the lead is a service request, MotionMate creates or updates a matching client.
5. Visitor is redirected to `/crm/thanks/`.
6. Workspace users can review the request in `/crm/staff/leads/`.
7. Owner/admin/staff can edit or convert the request, then schedule an appointment or create an invoice when appropriate.

### 5. Public Booking Request Intake

1. Owner/admin enables public booking in `/businesses/settings/booking/`.
2. Owner/admin creates at least one active weekly availability block.
3. Owner/admin marks one or more active services as bookable online.
4. Public visitor opens `/book/<business-slug>/`.
5. Visitor selects a service and preferred date/time inside the booking window and availability hours.
6. Visitor enters contact details, service location, message, and contact consent.
7. MotionMate creates a service request lead with `request_source=public_booking`, the requested service, preferred start/end time, and business scope.
8. MotionMate creates or updates a matching client.
9. MotionMate sends a visitor receipt email and an internal booking notification through the configured email backend.
10. Visitor is redirected to `/book/<business-slug>/thanks/`.
11. Staff reviews the new request from dashboard public booking review or `/crm/staff/leads/`.

### 6. Booking Request To Confirmed Appointment

1. Staff, admin, or owner opens the public booking service request detail.
2. If no matching client exists, they complete client conversion first.
3. They choose "schedule appointment from request" at `/appointments/create/from-request/<lead-id>/`.
4. MotionMate pre-fills client, service, title, location, notes, and preferred time where possible.
5. Staff confirms staff member, start/end time, location, and notes.
6. MotionMate creates the appointment linked to the source lead.
7. If the source lead is a public booking request, MotionMate sends an appointment confirmation email.
8. The appointment becomes visible in appointment lists, client detail, dashboard upcoming appointments, and invoice-from-appointment flow.

### 7. Manual Client To Appointment Flow

1. Owner/admin/staff/accountant creates or edits a client in `/crm/staff/clients/`.
2. Owner/admin/staff opens `/appointments/create/`, optionally starting from a client.
3. They select client, service, staff member, start/end time, location, and notes.
4. MotionMate validates that the client, service, and staff membership belong to the current business.
5. The appointment is created as scheduled.
6. Owner/admin/staff can edit the appointment or change status to completed, cancelled, or no-show.
7. Accountant/viewer can inspect appointment details but cannot manage appointments.

### 8. Appointment To Invoice Flow

1. Accountant, admin, or owner opens an appointment detail page.
2. They choose invoice from appointment at `/billings/from-appointment/<appointment-id>/`.
3. MotionMate checks that no invoice is already linked to that appointment.
4. The invoice form pre-fills appointment notes and service line item when possible.
5. User confirms service/description/quantity/unit price and notes.
6. MotionMate creates the invoice, generates the next business invoice number, creates line items, calculates subtotal/tax/total, and links the invoice to the appointment.
7. User lands on the invoice detail page.
8. Invoice is available in invoice list, dashboard billing widgets, client history, and PDF/email actions.

### 9. Client To Invoice Flow

1. Accountant, admin, or owner opens a client detail page.
2. They choose create invoice from client at `/billings/from-client/<client-id>/`.
3. They add one or more service or manual invoice lines.
4. MotionMate validates selected services belong to the current business.
5. MotionMate creates a draft invoice scoped to the current business and client.
6. User can edit draft invoice lines and notes until the invoice is no longer draft.
7. User can change invoice status through allowed transitions: draft to sent/cancelled, sent to paid/cancelled.

### 10. Invoice PDF And Email Flow

1. Owner/admin/accountant/viewer opens invoice detail.
2. User downloads PDF from `/billings/<invoice-id>/pdf/`.
3. MotionMate renders a PDF with business name/address/contact, invoice number/date/status, client billing details, appointment context, lines, totals, and notes.
4. Owner/admin/accountant sends invoice email from `/billings/<invoice-id>/email/`.
5. MotionMate validates the client email address.
6. MotionMate attaches the generated PDF and sends a templated email through the configured backend.
7. MotionMate records `emailed_at`, `emailed_to`, increments `email_send_count`, and logs an activity entry.

### 11. Team And Role Flow

1. Owner/admin opens `/businesses/team/`.
2. They review active business members.
3. They invite a new team member by email and role.
4. MotionMate creates an invitation token and sends an invitation email.
5. Invitee opens `/accounts/invitations/accept/<token>/`.
6. Invitee accepts the invitation and receives a `BusinessUser` membership.
7. Their accessible routes are controlled by the assigned role.

Role boundaries observed:

- Owner: full workspace operations, settings, team, subscription, CRM, appointments, invoices.
- Admin: workspace operations/settings/team, CRM, appointments, invoices, but no subscription page.
- Staff: clients, service requests, and appointment operations, but no billing/settings.
- Accountant: clients and invoices, appointment and request viewing, but no appointment/request editing.
- Viewer: read-only clients, requests, appointments, invoices, and invoice PDFs.

### 12. Dashboard And Reporting Flow

1. User opens `/crm/agent/dashboard/`.
2. MotionMate resolves current business and membership role.
3. Dashboard loads counts and follow-ups for clients and service requests.
4. If appointment module and role allow viewing, dashboard shows upcoming/today appointment metrics.
5. If invoicing module and role allow viewing, dashboard shows invoice counts, draft/sent/paid totals, unpaid totals, and recent invoices.
6. Public booking requests needing review appear as dashboard follow-ups.
7. Users drill into clients, service requests, appointments, invoices, or settings based on role permissions.

### 13. Tenant Isolation Flow

1. Every private route resolves `request.current_business` from the authenticated user's active business membership.
2. Querysets filter records by `business=request.current_business`.
3. If a user guesses another tenant's client, lead, appointment, or invoice ID, the route returns 404.
4. Public booking validates that selected services belong to the public business slug.
5. Cross-tenant service IDs fail form validation and create no lead.

### 14. Demo Data Status

The `seed_flintio_demo_data` management command is not present in this checkout.

When that command is restored, expected safe behavior is:

1. Allow seeding into an existing business with `--business-slug <existing-business-slug>`.
2. Allow targeting an existing owner with `--owner-email <existing-owner-email>`.
3. Create a separate demo workspace only when `--create-demo-owner` is provided.
4. Mark fake records with `[DEMO]` or `FlintIO Demo`.
5. Let `--reset-demo` delete only marked demo records for the selected business.
6. Never overwrite login email, password, role, profile, business, or non-demo data.

## Issues Found

1. Demo seed command source is missing.
   - Expected command: `seed_flintio_demo_data`.
   - Observed: unknown command, and `src/apps/businesses/management/commands/` has no source command file.
   - Impact: the preferred safe demo-data setup workflow cannot be used, including the requested `--business-slug`, `--owner-email`, `--create-demo-owner`, and `--reset-demo` behavior.

2. Local QA can be masked by HTTPS redirect.
   - With current secure settings, the first test-client pass received 301 redirects to HTTPS for every HTTP route.
   - Impact: route walkthroughs should either use HTTPS locally or explicitly disable `SECURE_SSL_REDIRECT` in the QA harness.

3. Permission-denied paths are mixed between 403 and 302.
   - Business settings/team/subscription use 403 for blocked roles.
   - Service management, appointment create, and invoice management often redirect with a message.
   - Impact: behavior is secure, but UX may feel inconsistent across modules.

Resolved since the original walkthrough:

- Navigation now links business settings, services, availability, subscription, invoices, clients, service requests, and appointments according to plan and role access.
- Subscription copy now presents in-app plan changes as manual pilot changes and keeps signup payment setup separate from future webhook/customer-portal work.

## UX Notes

- The public booking unavailable page is useful, but it would help owners if the private booking settings page made the four public-booking gates very visible.
- Accountant can create/edit clients but cannot edit service requests or appointments. This matches current role constants, but should be confirmed as the intended accounting workflow.
- Viewer can download invoice PDFs. This matches read-only billing access, but it is still an export action; confirm this is acceptable for viewer-level access.
- Expected 403 checks produce noisy PermissionDenied traceback logs in test output. This is normal in Django tests, but it makes manual QA output harder to scan.

## Recommended Next Refinement Blocks

1. Restore and harden `seed_flintio_demo_data`.
   - Add `--business-slug`, `--owner-email`, `--create-demo-owner`, and `--reset-demo`.
   - Mark all fake records with `[DEMO]` or `FlintIO Demo`.
   - Reset only demo records for the selected business.
   - Never overwrite existing users, profiles, businesses, real clients, real leads, real appointments, or real invoices.

2. Add a public booking readiness panel.
   - Show plan enabled, booking enabled, bookable services count, and active availability count.
   - This directly addresses "Booking Requests Unavailable" troubleshooting.

3. Standardize blocked-role UX.
   - Decide which blocked routes should be 403 versus redirect-with-message.
   - Apply consistently across settings, services, appointments, and invoices.

4. Convert this walkthrough into automated smoke tests.
   - Use a small `[DEMO]` fixture builder or restored seed command.
   - Assert public booking, appointment confirmation, invoice PDF, invoice email, and tenant isolation.

## Validation

| Command | Result |
| --- | --- |
| `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/motionmate_route_walkthrough.sqlite3 EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend uv run --no-sync python src/manage.py migrate --noinput` | Historical walkthrough command; passed |
| `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/motionmate_route_walkthrough.sqlite3 EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend uv run --no-sync python src/manage.py check` | Historical walkthrough command; passed |
| `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/motionmate_route_walkthrough.sqlite3 EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend uv run --no-sync python src/manage.py makemigrations --check --dry-run` | Historical walkthrough command; passed |
| `DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/motionmate_route_tests.sqlite3 EMAIL_BACKEND=django.core.mail.backends.locmem.EmailBackend uv run --no-sync python src/manage.py test apps.accounts.tests apps.businesses.tests apps.crm.tests apps.appointments.tests apps.billings.tests apps.notifications.tests --noinput` | Use this shape for a current full local validation pass when PostgreSQL is unavailable |

## Explicit Non-Changes

- No migrations were created.
- No app behavior was changed.
- No memberships feature was built.
- No Stripe, SaaS billing, checkout, or payment work was built.
- No real external email was sent.
- No real database records were modified.
