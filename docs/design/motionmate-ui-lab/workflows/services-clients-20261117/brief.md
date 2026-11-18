# Services Clients — design brief v1

Full Redesign, SERVICE only, actual entry `/crm/staff/clients/`.
Intake branch `experiment/motionmate-ui-redesign`; clean worktree.
User: “Automatically complete the audit, design brief, interactive prototype, and validation.”
Authorized task documentation, synthetic prototype, local static/browser evidence
using installed tools. Stop at Gate A. No production edits, database access,
installation, migrations, providers, staging, commits, pushes or deployment.

## Actual Django audit

Source inspection only; no claim of a rendered Django BEFORE. Actual working-tree
interactive BEFORE belongs to separately authorized implementation. Existing port
8000 application and PostgreSQL processes were not accessed.

| Surface | Source and contract | Proposed presentation |
| --- | --- | --- |
| Directory | `src/apps/crm/views.py:1396`, `crm/main/client_list.html`: business queryset; GET q/district/is_active (true/false/1/0); name/email/phone/company search; List.js 10 rows, six sort subjects, View all/less, selection with no bulk mutation. | Single client identity retaining company; contact, locality, activity; visible View/Edit, labeled filters, same pagination/sort/selection. |
| Profile | `staff_client_detail`: business-owned Client, five tab groups, separate invoices and appointments. Legacy `client_detail_view` remains. | Identity and contact first, readable relationship summary, disclosed complete details, notes and separate scheduling/billing sections. No invented activity feed. |
| Create/edit | `PrivateClientForm`, `crm/forms/client_create.html`, `client_update.html`: all existing fields, required name/email/phone/company/street and choice defaults; create returns list, edit returns detail. Country-sensitive create address; business-style edit address. | One form, six sections, jump links and optional disclosures. Same names/values and return paths. Company stays required for Individual. |
| Edit issues | Notes & Consent tab hidden below md; labels often lack for; `form.is_active` referenced but absent from form. | Every section reachable at 320px, associated errors and summary, no invented active/restore control. |
| Archive | POST, OWNER/ADMIN only, CRM+write guard; is_active false; ACTIVE classification becomes INACTIVE, others retained; return list; invoices/appointments retained. | Named confirmation and explicit effects; activity and classification remain distinct. |
| CSV | Existing upload/preview/execute/result and server-owned preview; atomic and retry-protected. Every CSV column optional; supplied values validated. | Upload → Validate → Preview → Confirm → Result with supplied ready/blocked rows; no new parser or browser-authoritative preview. |
| Inline client | `draft_client_modal.html`, `draft-client.js`, QuickClientForm: six required new_client-* fields, POST JSON, preserve appointment/request draft. | Focused inline demonstration with parent draft and focus return; actual scheduling/request workflows stay handoffs. |
| Finance | `client_invoice.html`, `billings/presentation.py`: six invoices per page, lifecycle/payment/review/balance/refund supplied by authoritative services. | Supplied financial labels, no totals calculator, settlement inference or new payment operation. |

All five Services roles read clients; OWNER/ADMIN/STAFF/ACCOUNTANT manage clients;
OWNER/ADMIN archive. ACCOUNTANT manages clients/invoices, not appointments. VIEWER
may read invoices when entitled. CRM, appointment and invoice read/write/module
conditions remain separate. Capacity is checked before creation and in a locked
transaction. Assignees remain active same-business OWNER/ADMIN/STAFF/ACCOUNTANT.
Read `businesses/utils.py`, context processor, CRM models/forms/views/urls, invoice
presentation, import contracts, Services appointments and invoice terminology docs.

## Shared impact and preservation

CRM templates/routes and dashboard parent serve both verticals. Logistics parcel
POST/partials, scoped parcel reads, location-aware financial access and branding
are protected. No production source changes. Shared lab shell/tokens/components,
logo, local Manrope, dashboard and Appointments are read-only inputs. Only one
additive Services entry in ui-lab/previews.json changes a shared lab registry.
12,619 tracked/reference files frozen in preservation-before.json; registry old
entries checked separately. Phoenix reference exists at version 1.23.0, read-only.
No existing review resource is stopped, reset or rebuilt.

## Design direction

Approved Motionmate tokens, Manrope, original mark, restrained indigo/navy light
and dark themes, 224px desktop sidebar, quiet surfaces, 44px controls. Operational
content first; no ornamental metric cards. Desktop semantic table becomes labeled
mobile records retaining every information subject. Profile exposes useful
contact/address/context and separate appointments/invoices. Six-section forms
retain all fields and drafts through theme/disclosure changes. Tailwind/DaisyUI
remain isolated; later production integration must translate to Phoenix 1.23.0.

## Deferred functional choices

- Existing Export button is inert. Explanatory handoff only; no new export or bulk mutation.
- Manual/inline company is required even for Individual; CSV optionality differs intentionally.
- No restore, merge, activity composer, follow-up writer, new query, schema, finance or role policy.
- No new persistence/cancel policy. Prototype data stays in page memory and clears on reload.
- Financial/appointment examples are synthetic supplied projections, not backend verification.

## Validation

Four widths 1440×900/768×1024/390×844/320×844, both themes. Connected list/profile/
create/edit/archive/CSV/inline interactions; empty/long/error/loading/restricted;
role/module/quota projections, errors, 32-field inventory (verified from PrivateClientForm AST),
filter aliases, sorts, pagination, selection, keyboard focus/dialogs, draft continuity,
44px targets, contrast/reflow, reduced motion. Retain raw axe incompletes/failures.
No application tests, real database, live-provider or full WCAG claim at Gate A.
