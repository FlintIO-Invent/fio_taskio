# Services Appointments · isolated demonstration

Target: `SERVICE`, named route `appointment_list`, GET `/appointments/`.
Purpose: a readable combined work list and deliberate filter/action hierarchy,
using the approved visual language independently of the dashboard layout.
Synthetic fixtures only. No Django process, DB connection, real record or provider.

Open with the [shared lab instructions](../README.md). Use `?scenario=long`,
`viewer`, `request-only`, `appointments-only`, `locked`, `invalid`, `pagination`,
`loading` or `error`, with `&theme=light|dark`. `scenario` is review-only;
`state` retains its actual filter meaning, e.g. `&state=needs_follow_up`.

## Source audit and preserved contracts

Read the actual implementation before designing (15 November 2026):

- [workspace template](../../src/templates/appointments/workspace.html),
  [view and guards](../../src/apps/appointments/views.py),
  [projection/filter form](../../src/apps/appointments/workspace.py),
  [named routes](../../src/apps/appointments/urls.py),
  [navigation](../../src/templates/appointments/includes/workspace_navigation.html).
- [Appointment model](../../src/apps/appointments/models.py),
  [AppointmentForm](../../src/apps/appointments/forms.py),
  [form template](../../src/templates/appointments/form.html),
  [CRM model/route definitions](../../src/apps/crm/models.py),
  [CRM routes](../../src/apps/crm/urls.py),
  [role predicates](../../src/apps/businesses/utils.py),
  [context flags](../../src/apps/businesses/context_processors.py).
- [Shared Phoenix shell](../../src/templates/inheritance/dashboard_parent.html),
  [draft client dialog](../../src/templates/crm/includes/draft_client_modal.html),
  [Services contracts](../../docs/services_unified_appointments.md),
  [financial vocabulary](../../docs/invoice_payment_terminology.md),
  [Logistics financial boundary](../../docs/logistics_financial_access.md).
- Read-only Phoenix table/validation examples and the UI skill's Phoenix map.
  Reference library exists; no reference assets were edited or built.

| Contract | Audited application behavior | Preview treatment |
| --- | --- | --- |
| Combined work | Existing Appointments plus active NEW/CONTACTED REQUEST Leads without any linked appointment; requests ordered first by creation, then appointments by start and ID | Supplied synthetic projection keeps kinds, IDs, ordering and distinct request status. No new entities, calendar or scheduling controls. |
| Classification | Appointment Client classification; request classification only from exactly one same-Business email match; otherwise Unknown | Fixture explicitly supplies label and optional client link. Browser never infers relationships. |
| Entitlements | List accepts either request or appointment reads; each row kind needs its own entitlement | Explicit owner/admin/staff/accountant/viewer, request-only, appointment-only, read-only and unavailable projections. Unavailable is a lab boundary illustration; the actual decorator may redirect rather than render this shell. |
| Writes | New/Edit appointment: manage role AND appointment write access. Create/Edit request: manage-leads role AND request write access | Supplied independent booleans control those links; no browser role evaluator. Owner/admin/staff allow writes in their writable fixtures; accountant/viewer do not. |
| Filter form | GET `q` (max 160), `state`, `source`, `classification`, `staff`, `service`; `status` alias only when `state` is absent; invalid form returns no records | Same names/options and alias; local display filtering over supplied metadata. Staff metadata is blank for requests, preserving that requests have no assigned staff. No server/global-search claim. |
| Detail/edit | `appointment_detail` `/appointments/<id>/`; `appointment_update` same + `edit/`; `staff_lead_detail` `/crm/staff/leads/<id>/`; `staff_lead_update` same + `edit/` | Named-route/path intent retained in local modal. No detail/edit workflow implemented or submitted. |
| Creation | `appointment_create` `/appointments/create/`; `staff_lead_create` `/crm/staff/leads/create/` | Links open local intent review. Existing full forms, inline client drafts, quota, availability, confirmation, CSRF and `operation_key` behavior remain untouched and untested here. |
| History/client/navigation | `staff_lead_list?status_group=all`; `staff_client_detail`; dashboard and list routes | Original destination intent retained. List filters/reset act locally; other destinations show intent review. Only relevant audited Services navigation is composed here; this is not a replacement application shell. |
| Pagination | 50 records/page, retain query values, allow historical status bookmarks | 52-row synthetic case uses 50+2; page links keep filters. No database query engine. |
| Time | Current workspace template uses Django date filters without explicit workspace timezone activation in this path | Preview supplies labels in America/Lower_Princes, with a visible zone and unchanged UTC instants. This is a proposed presentation correction, not a production timezone fix. Request preferred time remains “Preferred”; undated requests say “Not scheduled”. |
| Financial/booking behavior | Existing scheduling/conversion/booking/invoice/payment workflows stay in established detail/forms/services | No approve, schedule, reschedule, status-change, invoice or payment operation is added. No accounting amounts appear in this list. |

## Reuse and independent refinement

`src/input.css` imports the lab's shared theme and compositions, and scans only
this source plus shared components. `render.js` uses shared `shell`, `link`,
`badge`, `icon` and escaping. `mountChrome()` owns ordinary dialogs, focus,
theme and account popup. Fixture decisions stay in this screen; there is no
shared business-policy abstraction. New tokens preserve the Step 4 values.

Desktop combines the original nine information subjects into six semantic
columns: booking/source, client/classification, service/staff, time, state and
actions. Tablet/mobile use labeled cards from the same table rows. This design
does not copy dashboard queues, metric regions or its capped preview policy.
Secondary filters use a disclosure; all submitted values remain present.

The demonstration covers client/company names, known/unknown classifications,
online/internal/unspecified source, assigned/unassigned staff, preferred/undated
requests and all four current appointment statuses. The fixed synthetic clock
is **14 November 2026 at 09:00 UTC**, matching the reference. It is not today.
Loading/error states are explicitly controlled lab states, since this Django
list is server rendered. Retry dismisses only the synthetic error. Theme choice
uses the existing lab-only key; no business record or filter draft is saved.

Rebuild only this screen with `node ui-lab/tools/build.mjs services-appointments`.
The [common capture tool](../tools/capture.py) writes its matrix and fresh
cross-screen comparisons into `evidence/`; [check.py](check.py) exercises this
screen's interactions. Full results, screenshots and limitations are reported
in the [Step 5 report](../../docs/design/motionmate-ui-lab/05-design-system-and-workflow.md).

## Approval boundary

This is ready for design review after evidence completion. A later implementation
would need separate authorization for at least `src/templates/appointments/workspace.html`
and any approved Services-only template/asset boundary. Changes to the shared
`dashboard_parent.html`, app views/forms/routes, static/build configuration or
other screens would expand that proposal and need explicit scope. Do not copy
this JavaScript into production as an authorization, pagination or search layer.
No DB writes, migrations, Logistics edits, commits, pushes or deployment are part
of this demonstration.
