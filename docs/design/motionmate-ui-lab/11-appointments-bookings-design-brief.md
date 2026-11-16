# Motionmate Services — Appointments & Bookings design brief

**16 November 2026 · Step 2 · Design planning only · Awaiting review**

Use the approved Services dashboard's Manrope typography, restrained indigo actions, calm surfaces and readable operational records across Appointments and booking journeys. Keep one full Appointments workspace for scheduled work and unscheduled follow-up, with clear next actions and consistent business-local times. Retain Phoenix 1.23.0 in the application; use the existing isolated DaisyUI-inspired design system for any subsequently authorized prototypes.

This brief builds on the [Step 1 audit](10-appointments-bookings-audit.md); its implementation map, source references, findings and browser limitations remain authoritative evidence for this planning step. It does not repeat that investigation or claim new browser validation. The user's Step 2 request establishes the booking distinctions below. Proposed presentation, interaction and functional changes remain unimplemented and subject to their stated review boundaries.

Only this file is authorized for writing. No prototypes, application changes, database work, installations, builds, commits or deployment actions form part of Step 2.

## 1. Design goals and principles

| Class | Goal | Design consequence |
| --- | --- | --- |
| V | Make the next task obvious. | One page title and a clear primary task; place schedule, identity, state and relevant actions before audit metadata. Avoid decorative metrics and oversized introductions. |
| V | Make scheduled work unmistakable. | Separate appointment status, request follow-up state and Client classification. Use truthful outcome copy; never depict preferred time as a scheduled appointment. |
| V | Match the approved dashboard without copying its limits. | Reuse its typography, semantic colors, spacing and action language. The workspace retains all results and existing pagination, rather than the dashboard's capped queues or three-row mobile disclosure. |
| V | Keep mobile work complete. | Every existing information subject and allowed essential action remains available at narrow widths, with readable names, wrapping content and deliberate action groups. |
| I | Preserve continuity. | Keep drafts, selected filters, focus and context through disclosures, themes and inline Client creation. Changes to server return paths are separately classified F. |
| V | Show only what is known and permitted. | Unknown, Unspecified, empty, unavailable and read-only remain distinct. Do not invent zeros, provenance, assignments, delivery receipts or financial status. |

**Classification used throughout:** **V** = visual/presentation, including formatting existing values and clearer labels; **I** = interaction, including focus, dialogs, disclosure, wizard and navigation behavior; **F** = functional changes to server context, queries, linkage, scheduling rules or notifications. Where a proposal crosses layers, each part is identified separately. No classification grants implementation authorization.

Design inputs: [AGENTS.md](../../../AGENTS.md), [Motionmate UI skill](../../../.agents/skills/motionmate-ui/SKILL.md), [DESIGN](../motionmate-design-system/DESIGN.md), [COMPONENTS](../motionmate-design-system/COMPONENTS.md), [VERTICALS](../motionmate-design-system/VERTICALS.md), [UI review workflow](PREVIEW-WORKFLOW.md), [reproducibility](REPRODUCIBILITY.md), [approved dashboard integration](07-services-dashboard-integration.md), [frozen Step 4 reference](../../../ui-lab/services-dashboard/daisyui/README.md), and [existing Appointments composition](../../../ui-lab/services-appointments/README.md). Older pending-approval language in historical reports does not supersede the current approved direction.

### Visual foundation — V

Use the existing [semantic tokens](../../../ui-lab/design-system/tokens.css) and [component patterns](../motionmate-design-system/COMPONENTS.md); do not create another palette or token system. Primary actions use `primary`/`on-primary`; body and supporting text use `text`/`secondary`; surfaces use `canvas`, `surface`, `header` and `divider`; control boundaries use `control`. Preserve success/warning/error pairs in both themes. Keep the existing Motionmate mark unchanged, including its approved dark-mode tile.

Apply the documented type scale: 32/40px desktop page title, 28/34px mobile, 20/28px sections, 15–16px record names/body, 14/20px metadata/labels and at least 16px input text. Use Manrope with the existing local licensed asset and system fallbacks. Use the 4px spacing scale, 20px desktop/16px mobile panel padding, 12px panels, 8px controls and 6px badges. Prefer dividers to stacked shadows; avoid sub-14px working text, ornamental gradients and decorative animation.

For eventual application integration, express this direction through Services-scoped Phoenix-compatible templates/assets. Do not import lab CSS, Tailwind Preflight or DaisyUI globals into the application, enlarge the dashboard stylesheet's scope, replace Phoenix breakpoints or change shared tokens as an incidental step.

## 2. Screen-by-screen specifications

The common responsive, accessibility, feedback and access requirements in sections 5–6 apply to every core screen. References to decision IDs point to the unapproved proposals in section 10.

### A. Appointments workspace

Target: `appointment_list`, GET `/appointments/`. Audit: H2–H3, M2–M4, M8–M9.

| Class | Specification |
| --- | --- |
| V | Header: breadcrumb, one `h1` “Appointments”, concise “Scheduled appointments and requests needing follow-up”, and the workspace timezone. **New Appointment** is primary when allowed; **Create Request** is secondary under its independent guard. Do not replace either full form with a modal. |
| V | Lead with **Search** and **State**, then an explicit Filter/Reset action group. Label the current default “All states”; retain Scheduled, Completed, Cancelled, No Show and Needs follow-up choices. Keep the existing result ordering and absence of a date filter. |
| I | Put Source, Client classification, Staff and Service in one keyboard-operable **More filters** disclosure. Automatically expose fields with validation errors and make applied selections visible when collapsed. Keep pending selections through disclosure/theme changes; filtering remains explicit rather than firing on every keystroke. |
| V | Compose six desktop columns from the nine existing subjects: **Booking / source**, **Client / classification**, **Service / staff**, **Time**, **State**, **Actions**. Keep full titles, Client links where supplied, source, service, staff, date range, state and View/Edit destinations. Use restrained row dividers and text-bearing badges. |
| V | Requests say **Not scheduled**, with **Preferred** time only when supplied; display New/Contacted as **Request status**, separate from Needs follow-up. An appointment's Scheduled/Completed/Cancelled/No Show is its **Appointment status**. Unknown classification and Unspecified source stay truthful. For requests without an assignment field, “No staff assigned” describes the display; do not imply a staff-assignment control exists. |
| V | Keep View/Edit visible and named with record context; use one clear title link rather than making the entire row a competing link. Preserve 50-row pagination, page context and active query values. Keep Request history as a quiet, independently permitted destination. |
| V | No active filters and no entitled records: “No appointments or follow-up requests yet”, with only allowed creation actions. Filtered empty: “No work matches these filters”, with Reset. Invalid filters: errors above results, not a success-looking empty state. Read-only/unavailable states explain the actual restriction rather than presenting missing records as zero. |
| I | Filtering/page changes keep a meaningful focus destination; local prototype updates announce results once. Use a stable busy state only while an actual action is pending. The Django list has no independent async loading phase; do not invent live refresh or background fetching. |

Search continues to use `q`, max 160, with the existing per-kind searchable fields; do not advertise a new global/phone/service search guarantee. Staff filtering excludes requests, and Service filtering does not infer category-only matches. Explain these constraints concisely near the relevant filter, without changing the query. Date shortcuts, new default ordering, richer search and database pagination are F proposals under D8.

### B. Appointment details

Target: `appointment_detail`, GET `/appointments/<id>/`. Audit: H2–H3, H5, L1.

| Class | Specification |
| --- | --- |
| V | Header: appointment title, status and business-local date/time range. For a permitted manager, **Edit appointment** is the primary navigation action, with nearby explanation that schedule/staff/details can be changed there. Keep Back to Appointments quiet and visible. Do not introduce a separate reschedule endpoint. |
| V | Order content as **Schedule & location**, **Client, service & staff**, **Related request / invoice**, **Internal notes**, then subdued Created/Updated metadata. Preserve service-name snapshot and any currently supplied linked-service information; distinguish service snapshot from current catalog data where both appear. Preserve multiline notes. |
| V | Keep existing **View Client**, **View Service Request**, **View Invoice** or **Create Invoice** available under their own guards. Finance remains a secondary action group, not a new payment panel. Do not invent invoice balances or show hidden financial information. |
| V | Keep **Mark Completed**, **Mark No Show** and **Cancel Appointment** together in a clearly labeled status area, with destructive tone reserved for cancellation. Only the server's allowed transitions appear. For terminal records, explain the current status and lack of further status transitions; editing details does not reopen them. |
| I | A proposed cancellation confirmation would identify the appointment/time and state that cancellation does not itself cancel an invoice, issue a refund or send a change notification. This is an optional interaction requiring D2 approval; do not present it as existing behavior. A confirmation for every harmless edit is unnecessary. |

Desktop uses a main reading column and compact adjacent action area; tablet/mobile puts schedule and the primary action first, then related information and clearly separated status actions. Avoid a long non-wrapping header toolbar or essential actions available only in a menu. No activity timeline, new status, undo, customer portal or self-service cancellation is proposed for the baseline.

### C. Create/edit appointment

Targets: `appointment_create`, `appointment_update`, `appointment_create_from_request`; retain their full-page forms. Audit: H2, H6, M1, M6, M8.

| Class | Specification |
| --- | --- |
| V | Use a focused page title: **New appointment**, **Edit appointment** or **Schedule appointment from request**. Show business and optional source Client/request context before the fields; label preferred request time as preferred. |
| V | Section 1: **Client & appointment** — required Client and Title; optional Service and Staff member. Keep existing native selectors and the selected historical/inactive values the form currently permits. Show **Add a new client** beside Client under its existing guard. |
| V | Section 2: **Schedule & location** — required Start and End, explicit business timezone, optional Location. Show both date and time and let cross-date values remain readable; preserve existing validation rather than adding public-booking rules. |
| V | Section 3: **Internal notes**. Replace the large standalone status card with compact **Status on save** context: Scheduled for creation, existing status for editing. Do not make it an editable field or imply that saving reopens terminal work. |
| V | A consistent bottom action group contains **Create appointment** or **Save changes**, plus **Discard changes** for the existing cancel/return destination. This wording distinguishes leaving a draft from Cancel Appointment. Do not change return behavior under a label edit. |
| I | Preserve every entered field while the inline Client dialog opens, errors, closes or succeeds. Return focus to the relevant Client control and announce selection. Keep “Client is saved now; your appointment draft stays in place” visible; cancelling the appointment draft does not delete that Client. |
| I | On validation failure, retain bound values, show a linked summary and field messages, and move focus to the summary. Pending save uses text such as “Saving…” and prevents accidental repeat activation without replacing the hidden retry key or rejecting a legitimate retry. Restore control state on a recoverable failure. |

At desktop, pair Client/Title, Service/Staff and Start/End where readable; optional notes/metadata must not dominate required inputs. Tablet can use readable two-column field groups; mobile stacks in the same logical order with a full-width primary save action and a visible discard link. Avoid a second persistent save bar initially; add one only if a later review demonstrates a need and focus/viewport clearance remain sound.

No automatic duration/title changes, new searchable-select dependency or internal Individual-client schema change is implied. The current quick-Client form requires its existing fields, including company name. Preserve that validation in baseline prototypes; broader internal client-type parity is F/D9.

### D. Public booking, review and confirmation

Targets: `public_booking` `/book/<business_slug>/` and existing thanks route. Audit: H1–H2, H4, H6, M7–M8.

| Class | Specification |
| --- | --- |
| V | Customer-facing heading: **Book with {business}**, existing Motionmate mark, concise purpose and time-zone information. Replace the oversized decorative auth introduction with a compact business introduction. Retain supplied booking instructions without allowing them to obscure the form. Keep public booking separate from the staff workspace and Silicon marketing CSS. |
| V | Keep explicit **Book an appointment now** and **Contact me before booking** choices. Book now helper: “Choose a staff member and an available time to schedule your appointment.” Contact helper: “Send your details and the team will contact you to arrange a time. No appointment is scheduled yet.” |
| I | Retain the four-step sequence for the initial design: **Service → Availability → Contact → Location & review**. Add a compact review section within the final step, rather than a fifth mandatory step. This is a proposed local summary interaction, not a manual approval stage. |
| V | Service step contains booking intent and the existing service selector, retaining its supplied price label/currency. Do not turn catalog price into a promised invoice total, deposit or payment obligation. |
| I | Availability shows staff, named day/time choices, selected date/time and duration context. Keep selection visibly and programmatically identifiable; changing selection preserves usable focus. Use the supplied notice/window/availability rules and clearly explain no slots, missing staff or stale availability. Do not promise a reservation before a successful server response. |
| V | Contact retains Company/Individual, conditional company name, contact fields and current required values. Location retains country-specific labels/controls, address, message and consent. Use persistent labels and clear optional markers; preserve server-side stale-company handling. |
| I | Final review summarizes intent, service, staff/time only when relevant, contact and service location. Provide short **Edit** links back to the appropriate existing step while preserving the rest of the draft. Review occurs before the submission, with an explicit **Book appointment** or **Send request** label. |
| V | Book now outcome design: “Your appointment is scheduled”, with trusted service, date/time/zone, location and staff when supplied. Contact outcome: “Request received”, with “The team will contact you to arrange a time. No appointment is scheduled yet.” Include available business contact information for changes; do not promise self-service management or email delivery. |
| F | Outcome-specific rendering needs trusted server context after redirect/retry, since the current thanks view receives Business only. This is D6, not a template-only fix. Prototype variants may illustrate the design; the application must never select a success claim from an untrusted query parameter or infer it solely from client-side intent. |

For Contact before booking, the baseline keeps the existing Availability step with its short explanation, rather than silently skipping it. Mode switching, clearing/disabling hidden time values, step skipping and non-JS fallback are I/F proposals under D5. The design must not depict their server behavior as resolved. Public readiness still requires the existing setup/availability conditions; changing those is also F.

Desktop uses a comfortable form column with a compact adjacent selection summary where useful; the summary is not a second editable form. Tablet/mobile use one column, visible step text, wrapping names and 44px slot targets. Keep service/intent and selected time understandable without scrolling through decoration. On the last step, show the review above submit so customers can check it without navigating backward.

Use persistent inline feedback for slot errors; for a slot rejected at submission, retain customer details and return attention to Availability if authorized interaction work supports it. Distinguish validation, unavailable booking, rate/quota restrictions and uncertain network outcomes. Do not clear the draft or suggest a new operation key when the result may already have been saved. A contact request is an alternative chosen by the customer, not an automatic substitution for failed Book now.

### E. Request follow-up and scheduling handoff

Targets: existing `staff_lead_detail`, client completion and request-linked scheduling. Audit: M1, M4–M6.

| Class | Specification |
| --- | --- |
| V | Title the REQUEST screen **Request details** with customer identity, **Needs follow-up** only when eligible, Request status, source, requested service/category and preferred time clearly labeled **Not scheduled / Preferred**. Keep Client classification separate. Historical closed/INTEREST records must not be relabeled as active work. |
| V | Put the next permitted task beside the service/time context: **Schedule appointment** when existing readiness and appointment-write guards allow it; **Complete client details** when completion is necessary and the actor may do it; **View appointment** when one is already linked and entitled. This is clearer labeling/grouping of current destinations, not a new writer or automatic conversion. |
| V | Retain contact `mailto:`/`tel:` links, Client link/match explanation, message, multiline notes and guarded Edit request. For a linked appointment show its actual supplied status; do not call a cancelled link “Confirmed”. Keep invoice guidance truthful to the currently exposed controls. |
| V | Client completion clearly lists required missing details and explains that saving creates/matches a Client. Until a return-flow change is approved, use **Save client details** rather than implying the next screen will finish scheduling. Preserve the current Client Details redirect. |
| I | Reuse the appointment form composition for request-linked scheduling, keeping source request context and the distinction between preferred and selected time visible. No new confirmation stage is inserted between review and the existing appointment save. |
| F | A direct return from Client completion to the original request scheduling form, with reliable `source_lead` retention, is D4. The desired handoff may be illustrated separately in a prototype but cannot be claimed as the current application journey. |

Desktop pairs contact/service context with a compact next-action area; mobile puts the actionable context before long messages/notes, with the primary task visible in normal reading order. If appointment access is unavailable, retain allowed request follow-up/edit actions and explain the scheduling restriction. Do not invent assignment, reminder dates, a Mark contacted endpoint or an invoice action currently hidden from the interface.

### Supporting surfaces — explicit boundary

| Surface | V recommendation | Scope decision |
| --- | --- | --- |
| Booking Settings and share include | Replace misleading request-first claims with wording consistent with both intents; align copy feedback/labels and effective-rule explanations with the approved language. | Supporting follow-up proposal only: no rules/availability layout redesign or shared include edit in the five-screen baseline. Buffer/confirmation semantics remain F/D3. |
| Historical Request list | Keep its entry labeled **Request history**; propose heading/action wording that distinguishes history/requests from scheduled appointments. | No new table, export, bulk-action, filter or pagination redesign. Existing history and compatibility routes stay intact. |
| Create Request form | Apply the terminology matrix when separately scoped; keep the existing full form destination and REQUEST/INTEREST choice. | No sixth standalone form prototype, added scheduling fields or automatic appointment creation. |
| Client, invoice and dashboard destinations | Preserve contextual links and existing read/write guards. | Show route intent at prototype boundaries; no redesign of these destinations. The approved dashboard is frozen reference material. |

## 3. Navigation and information architecture

| Class | Navigation decision |
| --- | --- |
| V | Appointments remains the single Services operational destination. Preserve All Bookings & Requests, Needs follow-up and guarded Booking Settings navigation, using the existing URLs and `state=needs_follow_up` meaning. Do not add a competing Bookings workspace, calendar module or workspace switcher. |
| V | Keep breadcrumbs **Dashboard → Appointments → Record / task**. Request history is a supporting destination, not an alternative daily queue. Public pages use a customer-facing business frame, without staff navigation. |
| I | In prototypes, View/Edit/New Appointment/Client completion form a connected journey rather than route-intent dialogs for every core screen. Client, invoice, settings, history and dashboard links outside the prototype set show a review-only destination explanation without contacting Django. |
| I | Keep explicit Back/Discard links and keyboard-operable mobile navigation. Any proposed list-context preservation should restore the existing filters/page, not introduce new query semantics. Its application return-parameter behavior is F/D8. |
| I | Specify a page-scoped replacement or omission of the audit's unsupported mobile search trigger; the in-page search remains available. Do not implement a global search modal or change the shared shell by implication. |

The baseline task paths stay: **Appointments → New Appointment → Appointment Details**, **Appointments → Request Details → existing scheduling form → Appointment Details**, and **Public booking → truthful submission outcome**. D4 marks the incomplete-client diversion; D6 marks the outcome-context gap. Their improved variants are design proposals, not completed workflows.

## 4. Terminology and outcome matrix

The record distinctions in this table are established constraints from the Step 2 request. Proposed visible labels/helper text are **V**; dynamic review/submit-label behavior is **I**; truthful post-redirect outcome binding is **F/D6**.

| Entry / concept | Existing result to preserve | Proposed wording and next action |
| --- | --- | --- |
| Public Book now | Lead + Client synchronization + Scheduled Appointment. No later manual-confirmation stage. | “Book an appointment now” → **Book appointment** → “Your appointment is scheduled.” Changes go through the business contact; no new self-service route. |
| Public Contact before booking | Unscheduled REQUEST follow-up; no scheduled Appointment. | “Contact me before booking” → **Send request** → “Request received. No appointment is scheduled yet.” |
| Internal New Appointment | Scheduled Appointment directly. | **New Appointment** → **Create appointment** → “Appointment created.” Open existing Appointment Details. |
| Internal Create Request | REQUEST follow-up; no automatic scheduling. | **Create Request** → **Create request** → “Request created.” Return through the existing Appointments flow. |
| Needs follow-up | Operational eligibility over active open unlinked requests, not an appointment status. | Keep **Needs follow-up**; show New/Contacted as **Request status** and time as Not scheduled. |
| Appointment status | Scheduled, Completed, Cancelled, No Show. | Keep these labels and authoritative transitions. Do not rename Cancelled to “Available”, or editing to “Reopened”. |
| Request status / Client classification | Separate existing concepts. A scheduled appointment may retain a New source Lead; a Client may be classified Lead or Active. | Label each subject explicitly; no automatic status/classification rewrite to make labels match. |
| Request preferred time | Customer preference, possibly absent. | “Preferred: {business-local time}”; never display it as the appointment's confirmed start. |
| Source / matching | Online/Internal/Unspecified projection and unambiguous Client match. Direct internal appointments may remain Unspecified. | Keep truthful supplied source and Unknown classification. Do not infer origin or a Client FK in the UI. |
| Client created inline | Client persists independently of outer draft. | “Client saved and selected. Continue your appointment.” Discarding the draft is not Client deletion. |
| Invoice / communication | Invoice lifecycle, payment and notification delivery remain separate from appointment status. | **Create Invoice / View Invoice** retain existing destinations. Never say Paid, emailed/delivered, refunded or invoiced merely because booking/scheduling succeeded. |

If a successful submission is known but its intent is unavailable, a neutral **Submission received** is preferable to guessing that work is Scheduled or awaiting manual confirmation. If no successful submission is known, use an outcome-unavailable explanation rather than claiming receipt. Exact fallback copy/behavior belongs to D6. Missing/expired outcome context must not expose another customer's record or encourage duplicate submission as the first recovery step.

## 5. Responsive layouts, themes and time

### Layout specification — V

| Width | Workspace | Detail / follow-up | Appointment / public form |
| --- | --- | --- | --- |
| Desktop, ≥1200px lab composition | Six-column semantic table, compact search/state row and disclosed secondary filters. | Main reading region plus modest action/context region; no full-width toolbar of competing actions. | Readable paired fields; public selection summary may sit alongside the form. Avoid a mostly empty status sidebar. |
| Tablet, 768–1199px | Labeled two-column record grids; search and State remain apparent, other filters wrap. | Reading/action regions stack when side-by-side would squeeze labels; essential actions stay visible. | Two-column fields only where values remain readable; public steps and review remain in one task column. |
| Mobile, <768px | One record sequence: identity/state, Client/service/staff, time/source/classification, then View/Edit. All nine subjects retained. Search/state stack; Filter/Reset share a row if readable. | Schedule/request context first; primary action nearby, related links wrap, terminal actions remain distinct. | One column; 16px gutters, readable inputs, named steps and slot controls. Full-width save/submit, visible secondary navigation. |

Use the approved lab shell dimensions (224px sidebar/64px header, 32/24/16px gutters) for prototypes. They are not authorization to change the application's existing Phoenix navigation breakpoint or shell. Preserve the application shell and binding through a later scoped integration decision.

Prefer one semantic dataset/DOM order when table rows become cards, retaining headers/caption and explicit field labels. Verify assistive-technology behavior before release; CSS display changes do not prove table accessibility. Do not hide essential data behind hover or collapse arbitrary list rows. Long names, addresses, timezone names, buttons and error text must wrap without horizontal document scrolling; do not shrink working text to force a fit.

### Themes and business-local time — V/I

- **V:** Both themes use the existing semantic pairs and identical information/action hierarchy. Verify control boundaries, destructive states, badges and overlays independently; dark mode is not a palette inversion or reduced-information view.
- **I:** Theme changes preserve drafts, filters, step position, open overlays and focus. Prototypes use the existing lab-only theme preference; eventual application work retains Phoenix theme state. No preference migration is proposed.
- **V:** Format appointment, preferred and review times using the resolved Business timezone and label that zone near the relevant region. Keep canonical instants unchanged. Date/time controls retain their existing business-local parsing and DST validation.
- **V:** Prototype examples may retain the existing Appointments lab's 24-hour format; leave the approved dashboard's format unchanged. Show date on each time range and per-record UTC offset when needed for repeated DST hours; an offset taken from “now” must not mislabel a different appointment date.
- **F:** Changing scheduling arithmetic, stored timezone/instants, preferences or business-day boundaries is outside this visual proposal. Client-side slot calculations must not become authoritative scheduling rules.

## 6. Accessibility, feedback and restricted states

### Accessibility and interaction requirements

| Class | Requirement |
| --- | --- |
| V | One page `h1`, ordered section headings, named main/navigation regions, persistent field labels, textual states and record-specific action names. Decorative icons must not supply the only accessible name. |
| I | Provide a skip link, visible keyboard focus, logical DOM/tab order and operable disclosures. Navigation overlays/dialogs need a name, containment, Escape/close and return focus; preserve any separately established production static-backdrop exceptions. |
| V | Aim for 44×44 CSS-pixel controls, 8px action spacing, readable wrapping labels and no hover-only essential task. This project target is distinct from WCAG's minimum target-size criterion. |
| I | For invalid forms, associate messages with fields, set invalid state, focus a linked error summary and preserve values. Hidden/disclosed areas containing errors open automatically; public errors take the user to their step without clearing later valid data. |
| I | Public steps retain visible/mobile accessible names. Use a valid step-navigation pattern rather than incomplete ARIA tabs; if tabs are retained, implement the expected keyboard behavior. Slot selection needs announced selection state and focus that survives rendering. |
| V | Target WCAG 2.2 AA: 4.5:1 normal text, 3:1 qualifying large text and meaningful control/focus boundaries. Measure rendered light/dark/hover/error/overlay states later; this document does not certify contrast or accessibility. |
| I | Respect reduced motion; use only useful short state transitions and no shimmer/count-up effects. Screen-reader announcements should occur once, not on every re-render or focus movement. |

### Feedback contract

| Class | State | Required presentation / boundary |
| --- | --- | --- |
| V | Initial list/page load | Useful content or honest unavailable state. No fabricated zero counts or simulated live data. |
| I | Submission pending | Keep context; show “Saving…”, “Booking appointment…” or “Sending request…” and busy semantics. Do not announce success before acknowledgment or replace retry protection. |
| V | Validation failure | Specific field/non-field errors and retained draft; keep server-authoritative conflicts/limits distinct from browser validity hints. |
| I | Uncertain network outcome | Retain draft and explain uncertainty; do not encourage creating another booking blindly. Recovery must respect the same operation/retry contract; new server recovery behavior is F/D5. |
| V | Successful write | Describe the saved record and next step accurately. Do not claim email delivery; current email failures can occur after the booking is saved. Outcome-specific context remains F/D6. |
| V | Quota/rate/unavailable | Explain the actual limit or restriction without presenting it as an empty list. Do not promise automatic retry or move a user to another intent. Retaining a draft across the current replacement 409/429 responses would require F work. |
| I | Clipboard/dialog feedback | Where a supporting sharing change is separately approved, announce copy success or give manual-copy guidance on denial; do not silently fail. Preserve the exact supplied URL. |

### Permission and restricted-state matrix — V over existing server guards

| Actor / entitlement state | Design requirement |
| --- | --- |
| Owner/Admin/Staff with relevant writes | Expose only independently permitted appointment/request/client/finance operations. Staff scheduling access does not imply permission to manage every booking rule. |
| Accountant | Appointment/request reads under entitlement; no appointment/request mutation controls. Preserve allowed Client/billing management under its own guards. |
| Viewer | Relevant record reads only; no creation/edit/status operations. Services invoice read links may remain permitted; do not impose Logistics' staff financial policy. |
| Request-only | Show requests and permitted follow-up actions; no appointment rows/details or schedule/create control. State the limitation without a false appointment count. |
| Appointment-only | Show entitled appointments; no request queue/history disclosure. Source-request detail links must remain subject to request entitlement, not presumed authorized by appointment access. |
| Restricted subscription | Retain allowed reads and explain read-only access; no writable-looking form or active mutation action. |
| No access / inactive membership | Respect existing denial/redirect behavior. A prototype unavailable illustration does not promise a new production shell or disclose records. |
| Public visitor | Show only the tenant's bookable services/staff/slots and allowed booking intents. No staff workspace, private records or cross-tenant choices. |

Synthetic fixtures supply these conditions; a prototype must not introduce a client-side role/authorization evaluator. Any mismatch between current markup visibility and authoritative route checks is an integration issue to resolve within a separately approved scope.

## 7. Visual, interaction and functional scope

| Class | Proposed work for later review | Audit basis / limit |
| --- | --- | --- |
| V | Unified typography/surfaces, headers, grouped records, responsive layout, action hierarchy and truthful terminology. | H1–H3, M4, M9, L1. Existing dashboard/design tokens are references, not files to redesign. |
| V | Display existing instants in Business time with explicit date/zone; readable labels/notes and empty/restricted explanations. | H2, M6, L1. No scheduling calculations, query changes or new data. |
| I | Filter disclosure, accessible labels/selection/focus, inline Client continuity, pending/error feedback and compact review within the final public step. | H4, M6–M8. Approval concerns interaction design; not a new server stage. |
| I | Optional cancellation confirmation, wizard mode/fallback improvements and back-context navigation. | H5, M1, M7. Pending D2/D5/D8; baseline must not imply these are implemented. |
| F | Notification/reopening policy, effective buffers/internal conflicts, request-link/resume changes, server outcome context, hidden-value handling and query enhancements. | H1, H5–H6, M1–M3, M5, M7. Decision register below; no feature approval inferred. |

Within each section, V/I requirements define proposed design behavior only. F dependencies must be shown as conditional when they affect a flow; relabeling an F dependency as “UX polish” does not place it within presentation-only implementation.

## 8. Protected behavior and cross-vertical boundaries

- Preserve existing Business resolution, membership, role, module, subscription, capability, quota and tenant checks. Visual availability is not authorization. Appointment/request entitlements stay independent.
- Preserve named routes, methods, query keys `q`, `state`, `source`, `classification`, `staff`, `service`, legacy `status`, and 50-row pagination. Preserve `client_id`, service-link context, CSRF, operation/fingerprint keys, `new_client-` prefixes, `form_kind` and DOM hooks described in [audit section 7](10-appointments-bookings-audit.md#7-recommended-improvements-and-protected-functionality).
- Preserve existing models, service snapshots, source Lead links, legitimate historical multiple appointments, category compatibility, Client matching/classification and Unknown/Unspecified values. Do not create replacement booking/CRM/billing records or backfill origin in a visual redesign.
- Preserve inline Client draft behavior and immediate Client persistence; public Company/Individual handling; server availability, confirmation, concurrency/retry, quota and notification behavior unless a separately approved F item changes it. Do not invent manual confirmation or auto-schedule requests.
- Keep invoice lifecycle, recorded payments, credits/refunds, accounting review and subscription billing separate. Use the established [invoice/payment vocabulary](../../invoice_payment_terminology.md) and existing guarded navigation/services. No automatic invoice, payment collection or refund behavior is proposed.
- Protect Logistics completely: navigation, locations, assignments, staff grants, parcel/shipment/manifests and financial policy remain unchanged. Shared parents, theme/assets, branding, context processors and Client/billing components are dependencies with other consumers, not blanket redesign scope.
- Protect the approved Services dashboard and frozen Step 4/5 references/evidence. A future page-scoped solution is preferred; any shared change needs a consumer/vertical impact review and both verticals' regressions before release.
- No ordinary local/staging/production/Test Lab data, credentials, uploads, provider configuration, schema or running previews may be changed under this brief. Production implementation and release actions need separate explicit scope/authorization.

## 9. Proposed Step 3 interactive prototypes

**Recommendation: one connected Services review with five reusable screen compositions, not five independent builds.** Reuse the existing [Appointments list composition](../../../ui-lab/services-appointments/README.md), [UI Lab server/build/capture methodology](../../../ui-lab/README.md), shared tokens/components, local Manrope and pinned toolchain. A separately authorized screen package can host the connected views; preserve existing packages, frozen distributions and evidence rather than rebuilding the dashboard. No files, registry entries or prototypes are created in Step 2.

### Minimum set

| Composition | Useful interactive journey | Minimum synthetic variants |
| --- | --- | --- |
| P1 Workspace | Search/state/More filters → View/Edit; New Appointment; follow-up entry; pagination. | Mixed work, no results, invalid filter, long content and 52-row/50+2 pagination. |
| P2 Appointment details | Schedule/client/service/staff → edit form; status action intent; invoice destination intent. | Scheduled assigned, unassigned/no service, terminal Cancelled and linked invoice. Any confirmation dialog is explicitly D2 proposal. |
| P3 Shared appointment form | Create, edit and from-request modes; open inline Client, demonstrate retained draft, simulate validation/save. | Existing Client, new Client success/error, invalid time range, long notes and terminal-status edit. Reuse one form composition. |
| P4 Public booking + outcome | Both intents through the four steps, compact final review, back/edit selection and supplied outcome variants. | Book now scheduled, contact request unscheduled, Individual/company, no slots, conflict/validation, pending/uncertain result and unavailable. Outcome variants are F/D6 illustrations, not Django confirmation evidence. |
| P5 Follow-up journey | Request details → completion/scheduling → P3 → P2. | Matched Client, missing details, request-only access, historical linked/closed request and preserved request context. Show the existing Client Details diversion; label any proposed direct resume separately as D4. |

Current-contract and proposal-only variants must be clearly identified in review controls outside the mock product UI. Open F decisions are not silently simulated as approved features. Domain mutations, invoices, notifications and server validation are local demonstrations or destination intents only; no real endpoint is contacted.

### Scenario data and coverage

- **V — Fixtures:** use synthetic names/businesses, Individual/company, long service and Client names, assigned/unassigned staff, all four appointment statuses, online/internal/unspecified origins, unknown/ambiguous matching, preferred/undated requests and linked versus unlinked work. Use one declared fixed clock and workspace timezone, such as `America/Lower_Princes`; never call a historical fixture “today” without its fixed date visible in review metadata. Include a separate DST repeated-hour example with distinct supplied offsets.
- **V — Access variants:** reuse fixtures with Owner/Admin/Staff, Accountant, Viewer, independent request/appointment entitlements, read-only and unavailable projections. Supply flags from the audited contract; do not invent role policies or hide Services finance solely by role title.
- **V — Capture plan:** the five populated compositions at 1440×900, 768×1024 and 390×844, each in light/dark, make a 30-case core visual matrix. Capture viewport/full-page evidence for these cases; add targeted state captures rather than multiplying every fixture by every viewport blindly. Test 320px reflow and long-content cases separately.
- **I — Task checks:** keyboard-only creation with inline Client, filter disclosure/error recovery, mobile navigation, theme/draft preservation, slot selection/focus, public forward/back/review in both intents, incomplete-client handoff and terminal-action intent. Test reduced and normal motion. Track no-JS fallback as D5 candidate behavior, not a passed application guarantee.
- **I — Evidence:** retain actual failures, missing assets, accessibility incompletes and focus/reflow observations. Use existing Chromium/axe tools where available under the later prototype authorization; no new dependency installation is implied. Other browsers, AT and real devices remain separately stated coverage limits.

Step 3 should deliver a connected prototype, scenario/gallery index, scope/preservation check, contract map and review report. It must stop for design approval. These are future outputs, not completion claims. Synthetic prototypes do not replace the real working-tree Django BEFORE/AFTER review required before later implementation acceptance; authorized disposable setup must follow the existing workflow and runbook.

## 10. Acceptance criteria and unresolved decisions

### Design/prototype acceptance criteria

| Class | Acceptance criterion | Evidence expected after later authorization |
| --- | --- | --- |
| V | Scheduled appointments and unscheduled requests are distinguishable; Book now never displays a manual-confirmation stage. | Both public-intent scenarios and mixed workspace review against section 4. |
| V | Every workspace subject, full name, time/state and allowed essential action remains available; 50-row pagination is preserved. | Desktop/tablet/mobile and 52-row scenario; no dashboard-style row cap. |
| V | Business-local time agrees across list/detail/form/public review; preferred time stays distinct. | Fixed-clock/zone comparisons and repeated-hour example with offsets; stored instants unchanged. |
| V | Readable Manrope, approved tokens, deliberate mobile layout and both themes. | 30-case primary matrix, 320px reflow and long content; no horizontal document overflow. |
| I | Keyboard users can navigate, filter, open/close overlays, select slots, correct errors and reach review/save without focus loss. | Recorded task checks, named controls/selection state and error-focus results. |
| I | Drafts and selected context survive inline Client, step/back navigation, disclosures and theme changes. | Before/after values and focus checks using synthetic state. |
| V/I | Empty, invalid, pending, uncertain, unavailable and read-only states are truthful and recoverable within the current contract. | Relevant scenario review; no guessed success, email delivery or entitlement. |
| V | Permission-specific rows/actions and independent entitlements match the audited projection. | All supplied role/access variants; note synthetic checks do not prove server authorization. |
| I/F | Any proposal dependent on D1–D9 is labeled and excluded from claims of current application behavior. | Decision register linked from candidate variants; no unapproved writer or policy hidden in the prototype. |
| V | Dashboard, prior lab evidence, Logistics and shared application behavior are preserved. | Future protected-file/scope comparison; Step 2 itself only has document/scope checks. |

Rendered contrast/accessibility, task usability, backend preservation and real Django behavior remain unverified at Step 2. Link/consistency checks on a document cannot satisfy these later criteria.

### Approval decision register

All items below are **open**, with the current server behavior preserved. The recommendations identify what to decide, not features accepted by approving visual direction.

| ID / class | Decision requiring explicit approval | Recommendation for review / unchanged baseline |
| --- | --- | --- |
| D1 — F | Cancellation and rescheduling notifications: triggers, recipients, failures/retries and user feedback. | Define separately; existing edit/status paths do not gain email or delivery claims. Preserve save success independently of notification delivery. |
| D2 — I / F | Confirmation before terminal status changes; possible reopening/rebooking. | Consider an I confirmation for cancellation first. F reopening/new transitions remain deferred; Completed/Cancelled/No Show stay terminal and editing does not reopen. Do not add confirmations to every edit. |
| D3 — F | Effective booking buffers, manual-confirmation settings and internal conflict/override policy. | Align policy/control descriptions with authoritative rules in separately scoped work. Keep Book now direct, Contact before booking unscheduled, existing buffer/conflict behavior unchanged. No new scheduling restriction is assumed. |
| D4 — F | Request-to-appointment context through Client completion, matching and scheduling GET side effects. | Prefer preserving the original request and resuming its scheduling flow, after an approved server/return-contract design. Baseline retains the Client Details redirect; do not silently create duplicate/unlinked work. |
| D5 — I / F | Wizard mode changes, hidden stale values, skipping Availability, progressive/non-JS fallback and uncertain-result recovery. | Keep four steps initially. Explore accessible I handling; obtain approval for F stale-value/readiness/recovery semantics. Do not claim a contact request is undated merely by hiding populated fields. |
| D6 — F | Outcome-specific confirmation context after successful submission, retries, refresh and expired context. | Supply a tenant-safe, trusted outcome on the existing route, with neutral fallback and no personal data in URL parameters. Show scheduled versus request summaries only when that outcome is known; no new provider/email promise. |
| D7 — I / F | Invoice shortcut restoration and staff notification destination. | Keep current finance destinations and guards; remove misleading guidance in a later scoped copy change. Any restored action/navigation or notification target is separately reviewed, not automatic invoicing. |
| D8 — I / F | List-context returns, date shortcuts, default ordering, richer search and pagination optimization. | Preserve existing query/result semantics for the first design. Consider context retention separately; defer date/query/performance changes until requirements/evidence justify them. |
| D9 — F | Internal quick-Client Individual/company parity, selector enhancements or service-driven defaults. | Keep current required fields, native selects and explicit start/end/title input. Broader changes require their own form/data/validation scope; do not mirror public rules automatically. |

### Handoff boundary

The next approval can accept/refine the visual direction, five-screen composition plan and specific I proposals, while leaving F items open. Step 3 prototype creation needs explicit authorization; production integration requires a later file/scope/contract proposal and separate authorization. Commit, push, merge, migrations and deployment remain separate release actions.

**Step 2 completion:** only this design brief was added; the Step 1 audit was preserved. Document links, whitespace, classification/contract consistency and repository scope were checked. No prototype, application code, database, Logistics, dashboard, dependency, running preview or deployment environment changed. **Stop here and await approval.**
