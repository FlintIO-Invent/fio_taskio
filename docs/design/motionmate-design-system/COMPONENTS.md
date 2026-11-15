# Motionmate component patterns

Use with [DESIGN.md](DESIGN.md) and [VERTICALS.md](VERTICALS.md). These are
presentation patterns, not new domain capabilities. Shared executable preview
patterns live in [components.css](../../../ui-lab/design-system/components.css)
and [components.js](../../../ui-lab/design-system/components.js). Step 4 remains
the visual reference; Appointments imports these sources directly. Components
below not exercised by Appointments remain documented patterns, not a tested
production component library.

| Pattern | Purpose and visual behavior | Responsive behavior | Accessibility | Appropriate use |
| --- | --- | --- | --- | --- |
| Workspace navigation | Brand frame, 48px destination rows, indigo current item, vertical descriptor. Callers supply permitted destinations; no shared role evaluator. | 224px desktop sidebar becomes a modal drawer below 1200px. Keep the same destinations and order. | Named navigation, `aria-current`, named Menu/close controls, focus trap/Escape/return. | Services workspace links; a later Logistics preview must supply its own audited navigation. |
| Page header | One `h1`, concise context, primary action and quiet alternatives. Do not insert decorative KPI cards. | Actions align beside title on desktop, wrap into equal or full-width rows on mobile. | Heading hierarchy; explicit action text; no action available solely through hover. | Appointments: New Appointment and Create Request under independent guards. |
| Buttons/action groups | Indigo primary, bounded neutral secondary, quiet link actions; 44px targets, 8px gap, 8px radius. Hover/pressed stay legible. | Keep related actions side by side when readable; stack or wrap at small widths. | Anchors navigate, buttons act; accessible name includes record context; focus ring; disabled reason nearby. | Filter/Reset; View/Edit; existing receipt-recording navigation when separately in scope. |
| Fields/validation | Persistent 14px label, 16px value, 44px field, strong boundary. Show submitted values and errors in place. | Two/three columns only where readable; one column mobile. | Associated label; `aria-invalid`, `aria-describedby`, error text. No placeholder-only names. | Six existing Appointments filters. Preserve field names, CSRF/hidden keys and prefixes in later forms. |
| Table/record list | Semantic table with real column headers; compact border-separated rows; identity, state and actions visible. 14px metadata, 15/16px record titles. | Convert rows to labeled card grids while keeping all fields and DOM order; do not create competing duplicate datasets. | Preserve caption/header associations; test screen readers before release because CSS display changes can vary by engine. Full record names remain available. | Appointments combines service/staff and booking/source visually while retaining all nine original information subjects. |
| Search/filtering | Search operates in the current workspace contract; apply/reset is explicit. Secondary filters can use a labeled disclosure. | Search and state stack; secondary fields become one column. Preserve pending selections on theme changes. | Enter submits; disclosure is keyboard operable; results announced once; retain errors. | `q`, `state`, `source`, `classification`, `staff`, `service`; retain historical `status` alias. No global command palette. |
| Pagination | Previous/Next with page context; retain active query values. Preserve the existing page size. | Wrap controls without hiding page information. | Named page navigation, semantic anchors, focus remains meaningful after local preview update. | Existing 50-row Appointments pagination; synthetic 52-row case proves both pages. |
| Dropdown/disclosure | Quiet surface/popover; use native select for simple choices. An account popup contains ordinary links, not a false ARIA application menu. | Popover stays inside viewport; drawer when navigation needs space. | Explicit expanded state, Escape/return focus, close on outside interaction. Native select semantics. | Account link popup, More filters disclosure. Do not introduce a select library. |
| Status badge | 6px radius, text plus semantic tone, no uppercase tracking. Neutral/indigo for informational state, amber attention, green positive, red error/cancelled. | Wrap long labels instead of compressing adjacent names. | Color supplements text. Do not use an actionable-looking badge for a static status. | Scheduled / Completed / Cancelled / No Show; request “Needs follow-up” and New/Contacted remain distinct. |
| Dialog/drawer | Raised surface, restrained shadow/backdrop, title, body, explicit close. Native dialogs in the isolated lab. | Dialog max 540px with 16px viewport clearance; drawer max 320px and viewport height. | Name, modal containment, visible focus, Escape and return focus. Preserve deliberate production static-backdrop exceptions. | Route-intent review, workspace navigation. A creation form is not silently replaced with a modal. |
| Empty | Calm icon, honest message, existing allowed next step. No fabricated rows or metrics. | Natural height with readable text and full-size action. | Heading and keyboard-accessible allowed action. Distinguish no results from no entitlement. | “No bookings or requests match these filters.” with Reset. |
| Loading | Stable region, busy indication and one announcement; omit invented zeros. | Keep essential context and avoid layout jumps. | `aria-busy`, reduced motion; no shimmer. | Controlled lab presentation only; the Django list has no independent async fetch phase. |
| Error | Inline field error or alert near affected region; retain supplied records when refresh fails. Avoid transient disappearance. | Wrap long error text; provide a 44px recovery control where a real recovery exists. | Text explanation, associated field errors, alert used sparingly. | Synthetic error + Retry preview; not evidence of production network recovery. |
| Locked/read-only | State the existing access condition; omit unauthorized operations and restricted data. No false zero count. | Same meaning in every layout. | Readable notice; any allowed alternative remains reachable. | Request-only plans keep requests; appointment-only plans keep appointments; no-access fixture shows unavailable shell. Actual server behavior remains authoritative. |
| Notification/confirmation | Outcome text near the action; polite live status for noncritical success, alert for failure. Confirm only existing consequential actions. | Do not cover primary controls or require hover; persistent errors wrap. | Announce once, preserve focus, make dismissal keyboard reachable if provided. | Step 4 copy success/denial and Appointments filter results. No new notification center or mutation confirmation flow. |
| Mobile composition | Useful record identity first, readable supporting fields, clearly grouped actions. Keep full content available. | 16px gutters, 44px controls, wrapped names and explicit time/date. Test 320px and tablet separately. | Reading/tab order follows the DOM; no swipe-only or icon-only essential action. | Appointments record cards; dashboard uses its independent three-row disclosure policy. |

## Small reusable examples

```js
import {badge, link} from '../../design-system/components.js';
// The caller receives this permission from a synthetic audited projection.
const create = supplied.canCreateAppointment
  ? link('appointment_create', '/appointments/create/', 'New Appointment', 'btn mm-primary')
  : '';
const state = badge('Needs follow-up', 'attention');
```

```html
<label class="field-label" for="id_q">Search</label>
<input class="input" id="id_q" name="q" type="search" maxlength="160">
```

In previews `mountChrome()` provides theme and ordinary-dialog behavior;
screen code intercepts route intents and forms. In production, existing Django
guards, named routes, form fields and authoritative projections must be bound
through separately approved templates/includes. Copying the lab renderer does
not establish that integration.

## Review every new use

Verify populated, empty, long, invalid, busy/error and restricted states that
actually apply; all affected roles/entitlements; all three viewport sizes and
both themes. Measure names, focus, touch targets, overflow and rendered contrast.
Keep real route methods/query parameters and return behavior in the screen
contract. Reuse components without sharing Services/Logistics permission logic.
