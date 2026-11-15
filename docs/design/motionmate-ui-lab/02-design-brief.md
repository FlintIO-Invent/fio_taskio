# Motionmate UI Lab — Modern & Expressive design brief

> Historical step report. Steps 1–8 were subsequently completed and approved.
> Current setup/approval boundaries: [reproducible workflow](REPRODUCIBILITY.md).
> Complete historical evidence is in the [separate local archive](PRESERVATION.md).

**15 November 2026 · Step 2 · Specification only · Awaiting human review**

Target: **Motionmate Services dashboard**, existing `agent_dashboard` route at `/crm/agent/dashboard/`. Logistics is a separate operational vertical and must remain unchanged. Other Services pages are navigation destinations, not redesign targets.

Define one Motionmate design direction and two independently implementable experiments: **A — Tabler with Bootstrap** and **B — Tailwind CSS with DaisyUI**. Neither framework is preferred. Phoenix is the measured baseline, not the required visual outcome or a replacement decision. The user's explicit comparative specification governs the lab; the [AGENTS.md](../../../AGENTS.md) and [motionmate-ui skill](../../../.agents/skills/motionmate-ui/SKILL.md) preservation requirements still govern application behavior. This document authorizes no prototype build, dependency installation or production integration.

## 1. Problems established by the baseline

Reviewed [01-audit.md](01-audit.md), [baseline-metrics.json](baseline-metrics.json), desktop light/dark viewport images, tablet light/dark images, full mobile light/dark pages, and mobile long-content, locked and viewer captures. These are the existing Step 1 artifacts; no new browser session or database was needed for this specification. The eight source hashes recorded by the audit still match the current application entry points.

| Problem | Evidence inspected | Design consequence |
| --- | --- | --- |
| Summaries displace work | [1440 light](screenshots/services-dashboard-populated-1440-light-viewport.png): eight metric cards and booking sharing precede queues. At 390px, follow-up starts at **1,661px**, appointments at **2,345px**. | Put appointments and booking follow-up before metrics, sharing and configuration. |
| Desktop composition does not activate | At 1440px, queues remain single-column; the current `xxl` threshold is 1540px. [Desktop dark](screenshots/services-dashboard-populated-1440-dark-viewport.png) shows the same geometry. | Specify layout thresholds explicitly and identically for A/B. |
| Mobile is a long card stack | [390 light full page](screenshots/services-dashboard-populated-390-light-full.png) is **3,963px** tall; [dark](screenshots/services-dashboard-populated-390-dark-full.png) has the same structure. | Use compact record previews, inline counts, deliberate disclosures and fewer independent surfaces. |
| Tablet gains little task visibility | [768 light](screenshots/services-dashboard-populated-768-light-viewport.png) and [dark](screenshots/services-dashboard-populated-768-dark-viewport.png): follow-up begins at **1,054px**, appointments at **1,619px**. | Tablet has its own row composition and priorities; it does not inherit desktop card sizing. |
| Headers and controls compete for width | Mobile booking URL field is **94px** wide; section headings/buttons wrap beside each other. Settings buttons are 33px tall. | Place mobile actions beneath headings, give URLs a full row, and provide 44px controls. |
| Fine text undermines scanning | Labels are 12.8px; record metadata is **10.24px**. Long-text follow-up grows from 668px to **964px**. [Long-content capture](screenshots/services-dashboard-long-390-light-full.png). | Readable type, stable record fields, wrapping and progressive detail; never shrink text to fit. |
| Surface hierarchy is inconsistent | The share panel's `border-0 shadow-sm` differs from broad light-mode card overrides. Dark mode largely retains a separate default treatment. | One semantic surface/elevation system, designed in both themes. |
| Empty/locked states repeat low-value content | Eight zero-value cards precede empty actions; [locked capture](screenshots/services-dashboard-locked-390-light-full.png) repeats restrictions and mixes “0” with “Locked”. | Treat zero, unavailable and restricted as distinct states; keep an allowed next step visible. |
| Accessibility and correctness defects exist | Metrics record unnamed mobile brand/search links, missing initial keyboard focus treatment, broken search modal target and a timezone mismatch. | Track these as explicit corrections in §5, not evidence that a framework automatically solves them. |

No horizontal document overflow was measured in Step 1. The redesign must preserve that strength while improving task visibility, rather than describing the existing dashboard as wholly broken.

## 2. Modern & Expressive creative direction

**A confident Services workspace: recognizable Motionmate identity around a calm, precise working area.** Expressiveness comes from the mark, typography, composition and selective color. Operational rows remain restrained and easy to compare.

### Brand foundation

The existing [Motionmate SVG mark](../../../src/static/assets/img/icons/motionmate-logo.svg) contains cyan `#22A8FF`, blue `#4D66FF`, violet `#9C4DFF` and deep navy `#07162E`–`#12284D`. The [current lockup](../../../src/templates/includes/motionmate_logo.html) uses Nunito Sans and the visible spelling “MotionMate”. The lab uses the canonical customer-facing **Motionmate**, with **Services** as a clear contextual descriptor. No internal package/model/database naming changes follow from that spelling.

Retain the existing mark unchanged for both prototypes. Give its dark navy detail a small, quiet light tile in dark mode so the mark remains readable. Do not redraw it or invent a replacement logo. Keep its existing gradient inside the mark; do not spread gradients across headers, buttons or metric panels.

Use solid indigo for primary actions and current navigation, a narrow violet accent only where it helps establish brand identity, and cyan sparingly for informational emphasis. Amber means attention, green means a verified positive state, and red means an error/destructive action. Brand violet must not become an ambiguous financial status.

### Distinctive composition

- A compact brand/navigation frame, an editorial page title, a clear workspace-time line and two prominent work areas establish the first view.
- Appointment time is a strong alignment anchor. Customer, service and state form a consistent visual rhythm. Follow-up rows emphasize the person and existing request status, with the online source explicitly labeled.
- Counts live beside their relevant section titles; financial figures sit in one quieter summary region. No eight-card KPI wall, decorative chart, fake trend, oversized greeting, AI assistant panel, notification center or command palette.
- A single primary action leads to the existing Appointments workspace. Contextual links remain secondary. Setup guidance remains accessible without becoming the page's dominant task.
- Premium quality means precise alignment, useful density, readable copy and complete interaction states. It does not mean low-contrast gray text, excessive rounding, floating panels or ornamental animation.

## 3. Information architecture and viewport behavior

### Content order and data boundaries

The semantic/keyboard order is **page context → appointments → booking follow-up → invoice follow-up and financial summary → workspace summary → booking sharing/settings**. Required subscription/security alerts retain their existing visibility and precedence. Navigation is a separate landmark. Neither framework may change this order to make its demo appear more attractive.

| Region | Proposed content | Existing data/behavior retained |
| --- | --- | --- |
| Page context | `Services overview` as the only `h1`; workspace name; local date and timezone; primary `Open Appointments`; quiet Setup Guide when permitted | Existing business, appointment/workspace access and onboarding conditions. No workspace switcher. |
| Appointments | `Today's appointments` with the authoritative today count; `Next scheduled` preview underneath; customer, time/date, service/title and Scheduled label | `today_appointment_count`, `upcoming_appointment_count` and existing `upcoming_appointments`, in their current order and capped at five. |
| Booking follow-up | Open count, online review count, New count and this-month count in a compact section summary; existing request rows | `service_request_followups`, `open_service_request_count`, `public_booking_pending_review_count`, `new_service_request_count`, `service_request_count_this_month`. Existing request-detail links. |
| Invoice area | Issued collectible invoice preview with lifecycle/payment labels and balance due; compact draft/issued/count and money summary | Existing `recent_invoices`, `invoice.presentation`, counts and authoritative amounts. No local accounting logic. |
| Workspace summary | Clients and this-month additions; business name, currency, timezone and invoice prefix | Existing client counts and Business fields. Use a definition list with explicit gaps. |
| Secondary utilities | Existing online booking sharing; Services, Availability and Business Settings links with their existing guards | Readiness, role and write conditions remain authoritative. Sharing stays absent where currently absent. |

**The appointment preview is not a complete daily schedule.** The current query returns the next five future scheduled records, potentially spanning dates; the today count can include earlier appointments. Keep those meanings separate. Label rows beyond the workspace's current date with their actual date. If today has no scheduled appointments, use “No appointments scheduled today” beside the zero count, while retaining any future `Next scheduled` preview. If the preview is empty, say “No upcoming scheduled appointments”. Never derive all-day completeness from the five returned rows, invent past rows or add a new date-picker/query/API. The existing Appointments destination provides the full workflow.

All eight current metric subjects remain available in the corresponding regions above, with their current reporting periods. Moving a count does not redefine it. Display currency beside each money summary. The all-currency open-invoice count must not be relabeled as a USD-only count; visible money totals retain their supplied currency. Do not silently expose the currently commented currency/review table as part of the visual comparison; see §10.

### Desktop — 1440 × 900 CSS pixels

- At **1200px and above**, use a 224px navigation column, 64px top bar, 32px content gutters, 24px region gaps and a content maximum of 1200px. At 1440px, available content is approximately 1152px.
- Place appointments and follow-up alongside each other in a roughly **7:5** split. Give both headers and the beginning of both record lists first-viewport visibility. Use independent heights; do not stretch a short queue to create empty space.
- Use compact five-row previews. Follow with the financial region, then secondary workspace/sharing utilities. Keep money aligned with tabular numerals.
- Navigation uses only existing Services destinations and permissions. Indicate the current dashboard visibly and with `aria-current="page"`. No Logistics items, new navigation destination or persistent layout change on other application pages.

### Tablet — 768 × 1024 CSS pixels

- At **768–1199px**, use a 64px top bar and navigation drawer, 24px gutters and 20px region gaps. Keep the work areas full width in semantic order; forcing two narrow columns is unnecessary.
- Use the available width for a time/customer/service/state row, with supporting details beneath as needed. Show all five appointment preview rows by default; make follow-up begin within the tablet's first screen as specified in §8.
- Finance becomes a compact two-column description grid, not four equal-height cards. Sharing/settings follow the work. The navigation drawer uses the same destinations as desktop.

### Mobile — 390 × 844 CSS pixels

- Below **768px**, use 16px gutters, 16px region gaps and a compact 64px top bar. Keep the brand link accessible even if the wordmark is visually shortened. Show a labeled menu trigger, theme control and account menu; omit unsupported search (§5).
- Put page title/date/timezone first, then the appointment preview. The primary Appointments link can sit beneath the title or in the appointment header; **render it once**, not in both places. Setup Guide is a secondary text/button treatment in the same context region when permitted.
- Show the first **three** appointment rows and the first **three** request rows by default. Where the supplied preview has more rows, a labeled inline `Show 2 more` disclosure reveals the remainder without a fetch, route change or new business action. The full five-row preview remains available; `View all appointments` / `View bookings` still lead to the existing workspace. This is a presentation disclosure, not server pagination or a new scheduling capability.
- A row has a full-width customer name, a readable time/date, a service/company line and a status line. Badges never squeeze the customer name into a tiny left column. Place source and status together where they wrap predictably.
- Keep appointment and follow-up sections ahead of every secondary metric. No dashboard tab hides one queue, no horizontal carousel hides metrics, and no new bottom navigation duplicates existing destinations.
- Stack the booking URL field above equal-width Copy/Open actions. At 390px the input must be at least 300px wide inside its panel. Use a two-column definition layout with a 12px gap for workspace values; switch to label-above-value when content needs it.

The three-row mobile default is a reviewable design choice; both prototypes use it unless human review revises the shared contract. At long-content sizes, expand rows and let the page grow. Baseline geometry targets apply to the standard fixture, not as clipping heights for edge cases.

### Existing route and hook contract

| User intent | Existing destination/contract |
| --- | --- |
| Open the complete appointments/bookings workspace | `appointment_list`; retain current entitlement/role conditions |
| Open needs-follow-up | `appointment_list` with **`?state=needs_follow_up`** |
| Read an appointment | `appointment_detail` with its existing appointment ID |
| Read a request | `staff_lead_detail` with its existing Lead ID |
| Open invoice records/details | `invoice_list` / `invoice_detail` with the original identifiers |
| Use the current empty invoice action | `staff_client_list`, labeled `Create From Clients`, under its existing manage condition |
| Manage Services, availability, workspace defaults | `business_service_list`, `business_booking_settings`, `business_settings`; preserve the exact existing role/write guards |
| Share public booking | Supplied `public_booking_url` / `public_booking_path`; retain readiness, `target`, `rel`, escaping and manual-confirmation explanation |
| Open/continue setup | Existing welcome/guide IDs, `data-onboarding-target` values, target selectors and POST intent/CSRF/hidden fields |

There is no inline approve/schedule/pay/cancel action in this design. Users continue through existing detail/workspace flows, including inline client creation and draft preservation where those flows already provide them. Navigation does not bypass server authorization. Subscription billing remains separate from customer invoicing.

## 4. Typography, spacing, color and component system

### Typography and density

Preferred candidate: **Manrope**, one family for headings, controls and body, using weights 400/600/700/750. Its geometry relates to the existing rounded brand while providing a different editorial hierarchy. This is a proposal, not a font already installed in the app. The [Google Fonts metadata](https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/METADATA.pb) records its variable weight range and OFL license; retain the [license](https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/OFL.txt) with any later approved font asset.

Both prototypes must use the exact same approved font files and fallback stack. If font acquisition is not authorized or unavailable, use the existing Nunito Sans for **both** and record that limitation before visual scoring. Do not compare one framework with a downloaded font against the other with a fallback. Prefer locally served assets in a later lab build; no external font dependency is introduced now.

| Role | Desktop/tablet | Mobile | Guidance |
| --- | --- | --- | --- |
| Page title | 32px / 40px, 750 | 28px / 34px, 750 | Slight negative tracking, maximum −0.025em; no giant hero heading |
| Section heading | 20px / 28px, 700 | 20px / 28px, 700 | Semantic `h2`; clear count nearby |
| Record/customer title | 15px / 22px, 600 | 16px / 24px, 600 | Natural case; full accessible name |
| Body | 15px / 24px, 400 | 16px / 24px, 400 | Comfortable reading without loose paragraph blocks |
| Supporting text/status/control labels | 14px / 20px | 14px / 20px | No working text below 14px; mobile text inputs at least 16px |
| Compact amount/count | 24px / 30px, 700 | 22px / 28px, 700 | Tabular numerals where supported; units and currency remain explicit |

Use a 4px spacing basis: **4, 8, 12, 16, 20, 24, 32, 40, 48px**. Panel padding is 20px desktop, 16px mobile. Record padding is 12–16px vertically with room to grow; do not set a fixed text-containing row height. Section headings are headings; numeric counts are text, not additional headings.

### Proposed semantic color tokens

These are framework-neutral lab tokens, not replacements for global Phoenix variables. Prefix later lab variables with `--mm-services-*` and map each framework's component variables to them inside its own document.

| Token/purpose | Light | Dark |
| --- | --- | --- |
| Canvas | `#F6F7FB` | `#0B1020` |
| Working surface | `#FFFFFF` | `#121A2B` |
| Raised/hover surface | `#EEF1FA` | `#1A2440` |
| Primary text | `#182235` | `#EDF1FC` |
| Secondary text | `#526079` | `#B0BCD2` |
| Primary action / link / focus | `#3949DB` | `#ABB6FF` |
| Text on filled primary | `#FFFFFF` | `#101727` |
| Filled primary hover | `#2E3CB8` | `#BEC6FF` |
| Decorative divider | `#D8DFEA` | `#29354D` |
| Required control boundary | `#71819A` | `#7D8EAE` |
| Brand accent, non-status | `#7460D9` | `#B9A8FF` |
| Success text / surface | `#16624A` / `#E7F5EF` | `#8AE0B9` / `#113C30` |
| Attention text / surface | `#7A4A09` / `#FFF3D6` | `#F5CC80` / `#3C2D16` |
| Error text / surface | `#9C2D3A` / `#FCEAEC` | `#FFACB5` / `#40202B` |

Read-only sRGB calculations for these candidate pairs give: light primary/white **6.67:1**, light secondary/white **6.35:1**, dark secondary/surface **9.08:1**, and dark primary fill/on-primary text **9.26:1**. Candidate success/attention/error text on their paired surfaces exceeds **6:1** in each theme. These are numerical token checks, not rendered prototype validation; hover, focus, links, badges, opacity and compositing still need browser checks.

### Surfaces, iconography and interaction

- Working panels: 1px decorative border, 12px radius, no general drop shadow. Buttons/fields: 8px radius. Status labels: compact 6px radius, natural-case text and no unnecessary uppercase tracking. Use shadow only for overlays/popovers, e.g. `0 12px 32px` at restrained opacity; dark elevation primarily changes surface value and border.
- Show one solid primary action per local task context; secondary actions use neutral/quiet treatments. A primary-style button is not required on every panel. Destructive controls remain distinct and only appear where an existing action exists.
- Use the **same small inline SVG icon set** in A/B, selected from the existing Feather-style vocabulary, with consistent 20px sizing and stroke. Do not give A Tabler's full icon library and B an unrelated set. Status information always includes text; decorative icons are hidden from assistive technology.
- Keep links semantic anchors and disclosures/toggles semantic buttons or native disclosure elements. Record rows have one principal detail link and no nested interactive control. If a whole row is linked, provide a clear focus treatment and a useful accessible name.
- Provide default, hover, focus-visible, pressed, busy, disabled and error appearances. No new validation or mutation workflow follows from these visual states. A locked module is an explanation, not a clickable disabled KPI.
- Hover/focus feedback may use 120–160ms color/border transitions. Respect reduced motion; remove movement and animated skeleton shimmer. No bouncing cards, count-up numbers or entrance animation.
- Copy feedback belongs beside the control and in a polite live region: `Link copied` after success; `Copy unavailable — select the link to copy` on failure. Keep manual selection available. This is feedback for the existing capability, not a new sharing integration.

## 5. Theme, accessibility and separate correction work

Both themes are first-class designs with identical content, layout and affordances. Choose the initial theme from the lab's explicit capture setting; otherwise respect the user's saved lab choice and system preference. Use a lab-only storage key shared by A/B, not production Phoenix/Tabler defaults. Switching theme preserves focus, disclosures, open navigation state and data. Avoid a flash of the wrong theme. Do not write production preference keys.

Target **WCAG 2.2 AA**. Normal text must reach 4.5:1; larger qualifying text 3:1. All control labels in this brief should meet 4.5:1, avoiding dependence on the large-text exception. Follow the [W3C contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html). Required control boundaries, focus indicators and meaningful non-text graphics need at least 3:1 against adjacent colors. Decorative separators do not need to masquerade as control boundaries.

The lab's control target is **44 × 44 CSS pixels**, including menu/theme/account/copy and close buttons, with 8px separation where practical. This is the project's comfort requirement; [WCAG 2.2's minimum target criterion](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html) uses 24px with specified exceptions. Do not claim every existing 33px control is automatically a WCAG failure.

Require a skip link, clear navigation/main landmarks, one `h1`, coherent section headings, visible text labels, and a 2px visible focus ring with separation from the focused surface. Navigation drawers trap focus while modal, close with Escape and return focus to the trigger. Account menus support their keyboard behavior. The existing setup guide's deliberate static-backdrop/keyboard rules are a separate workflow contract: preserve them and keep its existing close/continue controls keyboard reachable; do not add an Escape action that silently changes saved onboarding state.

At 200% zoom and the 320px reflow check, no text or control is clipped or hidden behind sticky chrome. Wrap long names/URLs and use `min-width: 0` where needed. Essential record identity, time, status and monetary values are not ellipsized without an accessible complete value. A visual preview may shorten secondary prose only through an equivalent expandable treatment in both prototypes. Do not rely on hover tooltips for required information.

### Corrections tracked separately from visual composition

| ID | Baseline defect / constraint | Same prototype treatment in A and B | Production implication, not performed here |
| --- | --- | --- | --- |
| F1 | Services mobile search targets absent `#searchBoxModal`; click throws a Bootstrap error | Omit that unsupported search control. Preserve existing workspace search within its existing destination; do not add global search | A Services-only correction needs explicit implementation scope. Logistics parcel search remains untouched. |
| F2 | Business-local day boundaries but UTC-rendered record times | Format the same supplied instants in `current_business.timezone`, show the zone, preserve original instants in the fixture manifest | Approve and regression-test a presentation-only timezone correction, including day/DST boundaries. No timezone selector, rescheduling or count-query changes. |
| F3 | Unnamed brand/search controls; weak initial focus; sampled button text contrast around 4:1 | Supply accessible names, keyboard/focus behavior and verified semantic colors | A framework does not prove accessibility. Shared-shell fixes require a later Services-scoped boundary and Logistics preservation checks. |
| F4 | “0” and “Locked” blur unavailable versus empty data | Use the existing unavailable message and an explicit locked label; retain exact entitlement predicates | Copy/presentation correction only. Do not widen access, fabricate zeros or add an upgrade workflow. |
| F5 | Clipboard action supplies no result feedback | Add success/failure feedback in the isolated lab only, with permission denial covered | Reuse the same supplied URL and escaping; no external sharing service or altered booking flow. |
| F6 | Currency/review include exists inside an HTML comment | Retain current visible finance scope, explicit currency and supplied financial presentation; flag incomplete aggregate context | Exposing that table or new review indicators needs a separate content decision. Never recompute settlement in JavaScript. |

These proposed corrections are disclosed differences from the baseline and must appear identically in both prototypes. They cannot be attributed to one framework's visual quality. Their production implementation is a separate authorization and verification decision.

## 6. Required states and prototype parity

### Canonical synthetic content

Reuse the audit's realistic content and underlying instants, with a fixed clock **2026-11-14 09:00 UTC** (05:00 in `America/Lower_Princes`, UTC−04:00). Date inside the prototype is fixture time, not the reviewer's current date. Workspace: **Harbour Services · UI Audit**; signed-in user: **Alex Morgan**; currency **USD**; invoice prefix **INV**. Use synthetic `.test` contact details only.

| Customer | Company | Appointment instant, 14 Nov UTC | Proposed workspace-local display | Request preferred time, 15 Nov local | Request source / status |
| --- | --- | --- | --- | --- | --- |
| Jamie Rivera | Harbour View Apartments | 11:00 | 7:00 AM | 7:00 AM | Online Booking / New |
| Taylor Bennett | Island Property Services | 14:00 | 10:00 AM | 10:00 AM | Online Booking / New |
| Casey Laurent | Household | 17:00 | 1:00 PM | 1:00 PM | Staff-entered / New |
| Jordan Ellis | Seaview Guesthouse | 20:00 | 4:00 PM | 4:00 PM | Staff-entered / Contacted |
| Riley James | Market Street Studio | 23:00 | 7:00 PM | 7:00 PM | Staff-entered / Contacted |

Each appointment is Scheduled, service **Property maintenance consultation**, title **Initial site visit**. Each request remains a separate eligible unlinked REQUEST Lead, not an appointment. Appointment order is the table order; request ordering follows the supplied server projection, not a new client-side urgency score.

Exact summary values: **5 clients / 5 added this month; 5 open requests / 3 New / 5 created this month; 2 online pending review; 5 appointments today / 5 upcoming; 2 draft invoices; 3 invoices with a balance due / 3 issued; $750.00 issued invoice value this month; $750.00 outstanding, USD**. The three invoice rows remain **AUD-1003 / Casey / $375.00**, **AUD-1002 / Taylor / $250.00**, **AUD-1001 / Jamie / $125.00**, each with distinct **Issued** and **Unpaid** labels. These are supplied fixture amounts; the lab does not calculate them.

Use the same supplied synthetic public booking URL/path, readiness and manual-confirmation explanation in A/B. No localhost port, asset host, fixture name or framework label should alter the product content between captures. A future comparison harness must resolve route intents against one shared read-only destination map; neither prototype can navigate or submit to an ordinary application database. External handoffs are intercepted/labeled outside the product UI for review, not implemented as redesigned destination pages.

### Screen-state matrix

Every row applies to **both** prototypes with identical state inputs. Standard captures use **1440 × 900, 768 × 1024 and 390 × 844**, DPR 1, in **light and dark**. This means six comparable renders per required state per prototype, not one framework's desktop against the other's mobile. Interaction states are captured after the same scripted action; loading is captured at the same controlled time.

| State | Required content / behavior | Scope note |
| --- | --- | --- |
| Populated owner | Canonical fixture above; default mobile previews; all existing guarded actions | Primary visual baseline |
| Empty workspace | No customers/requests/invoices/upcoming appointments; allowed existing empty actions and setup guidance | No fabricated statistics or trend decoration |
| No appointments today, future preview present | Today count zero; future rows retain dates; requests remain visible | Never label future appointments as today's schedule |
| Today count positive, no future preview | Earlier scheduled records can contribute to today count; accurate empty `Next scheduled` message | No invented past-history query |
| Independent module locks | Appointments unavailable with requests still available; invoicing unavailable; online booking unavailable | Existing unavailable messages, guards and distinction from zero |
| Staff / viewer / accountant / admin | Role-accurate navigation and action visibility; all valid Services roles currently retain appointment/invoice read access | Do not fabricate a hidden-finance viewer policy. Exact context predicates win. |
| Existing workspace read-only/grace states | Existing subscription alert/owner actions and write restrictions, using supplied state | No new billing recovery, payment or suspension logic |
| Long content / large amounts | Audit long names/company/workspace; long unbroken secondary URL; supplied large currency-formatted amounts | Wrap and grow. Preserve identifiers, currency and status; do not shrink type. |
| Booking sharing ready / absent | Existing ready share region; absent region when its existing condition is false | A setup-needed variant is shown only where the current dashboard actually renders it; no newly exposed branch |
| Setup welcome / selected guide | Same journeys, progress, target hooks, static behavior and existing operation intents | Presentation preview only; no saved completion or POST execution |
| Navigation, account and focus | Drawer open/closed; account menu; keyboard focus; returned focus; theme switch with disclosures retained | No unsupported search |
| Copy success / denied | Same URL, confirmed copy feedback, denied/unavailable fallback | Same clipboard API/permission test conditions |
| Controlled pending / error message | See loading boundary below; nonzero/unknown must never be rendered as a false zero | A lab state is not evidence of a new API or error handler |
| Financial edge presentation | Existing authoritative partial-payment/refund/review/currency payloads where applicable; no invented collectibles or cash-revenue label | No new ledger, review destination, payment control or uncommented finance table |

**Loading boundary:** the current page is server-rendered and has no independent data-fetch loading phase. Do not add asynchronous fetching, charts, polling or permanent skeleton panels to manufacture one. A future lab can demonstrate a controlled pending navigation/clipboard state and the visual language of an externally supplied loading/error state. Mark simulation controls in the review harness, outside the product UI. Do not claim the production dashboard has those states or that a static prototype verifies network recovery. Announce a genuine busy state once, keep geometry stable, and omit shimmer under reduced motion.

**Onboarding parity:** retain hook names including `clients`, `service-requests`, `booking-settings`, `appointments`, `invoices`, `business-settings`, `services` and `availability`, along with existing IDs and operation field names. Moving summary content must not strand a spotlight target inside a closed disclosure. Preserve POST intent, CSRF and retry contracts in the documented integration map; a static prototype records the intended action and does not execute it.

### Feature parity contract

| Dimension | A — Tabler + Bootstrap | B — Tailwind + DaisyUI |
| --- | --- | --- |
| Product tasks | Open appointments, read appointment/request/invoice, review follow-up, navigate existing settings, share link, use existing setup guide | Identical |
| Data, amounts, periods, ordering, permission flags | One canonical supplied fixture set; no local business computations | Identical |
| Page composition | Shared IA, breakpoints, type scale, token colors, icon/font files and mobile three-row disclosures | Identical |
| Dialog/menu behavior | Same keyboard, focus and existing onboarding intent contract | Identical |
| States / viewports / themes | Full matrix above | Identical |
| Visible functionality | Existing capabilities only; no chart, search, calendar picker or inline workflow addition | Identical |
| Evidence | Same scripted task sequence, screenshot names, capture delays, browser, network/cache settings and review rubric | Identical |
| Framework freedom | Native Tabler/Bootstrap components and appropriate local customization | Native DaisyUI components/Tailwind layout and appropriate local customization |

Parity does not require identical class lists or a pixel copy of one framework. Both must independently realize the same design contract. Any visual/interaction difference caused by a framework limitation is recorded, not hidden by reducing the other prototype's scope.

## 7. Implementation boundaries and expected risks

### Common isolation boundary — proposed only

Later work, if authorized, should live under a separate **`ui-lab/services-dashboard/`** tree with sibling `tabler/`, `daisyui/` and shared read-only fixture/token/brand inputs. These are proposed locations, not directories created in Step 2. Each prototype has its own HTML/template source, dependency manifest/lock, build/output assets and entry document; either can be built/viewed without the other framework. Shared material contains product data/design inputs and a framework-neutral test contract, not components from A imported into B or vice versa.

Serve the two experiments as separate documents through a lab-only static or test harness. Do not add production Django routes, alter `ROOT_URLCONF`, register a Django app, extend `dashboard_parent.html`, change Django static discovery, run `collectstatic`, or place output in **`src/templates/`, `src/static/` or `src/staticfiles/`**. Do not load Phoenix, Silicon or Logistics styles/scripts in either lab page. Prefixes and wrappers are extra defenses; **a separate document and asset graph are the isolation guarantee**.

No prototype changes the production sidebar or shell. A later production adoption plan would need a Services-dashboard-only asset/template boundary and a clear handoff to unchanged existing pages. It must prove that no lab CSS/JS or preference keys reach Logistics, other Services screens or the public site. A successful lab does not authorize a site-wide framework migration.

### A — Tabler with Bootstrap

- Use a pinned compatible `@tabler/core` release, its Bootstrap-based grid/components and scoped Motionmate token/component customization. Compiled CSS/JS can be served to server-rendered Django templates without a Node runtime; see [Tabler's Django guidance](https://docs.tabler.io/ui/getting-started/frameworks/django). A Sass/tooling build is optional if needed for the approved customization; measure that maintenance cost.
- Use one Bootstrap interaction runtime. The [current Tabler installation documentation](https://docs.tabler.io/ui/getting-started/installation) says Tabler's JS includes Bootstrap and warns against loading a second copy. Do not carry the existing Phoenix Bootstrap bundle into the experiment. Confirm whether the pinned release exposes `tabler.Modal`, `bootstrap.Modal` or another documented API before adapting setup guidance; a `data-bs-*` attribute alone does not prove old scripts remain compatible.
- Map the shared tokens to Tabler's actual component variables, not only its primary swatch. Override default font, panel density, spacing and button variants enough to implement this brief, without adding an unrelated dashboard layout just because a demo ships it.
- Expected risks: global element/component selectors (`.btn`, `.card`, `.navbar`), Bootstrap reset/variable collisions, duplicate event handlers/backdrops, framework-version differences in modal/offcanvas APIs, and Tabler theme persistence competing with Phoenix keys. These are engineering integration risks inferred from the current shell and the documented runtime behavior.
- Use a lab theme adapter with the shared lab-only preference. Tabler supports `data-bs-theme` and its own theme script/storage conventions; do not let those defaults change the comparison or production state. [Tabler color modes](https://docs.tabler.io/ui/getting-started/color-modes).

### B — Tailwind CSS with DaisyUI

- Use compatible pinned Tailwind CSS 4 / DaisyUI 5 packages and a lab-only CLI or PostCSS build. DaisyUI is a Tailwind plugin; it does not require React or a Django replacement. The official [installation guide](https://daisyui.com/docs/install/) describes the Node/Tailwind build dependency. Serve the compiled result as ordinary CSS in a later Django integration; no utility compiler is required in the request path.
- Implement the same work areas with Tailwind layout utilities and DaisyUI buttons, menus, status, fields and dialogs where suitable. Define two custom semantic themes from this brief, rather than adopting a decorative built-in theme that changes the design comparison. DaisyUI's [theme documentation](https://daisyui.com/docs/themes/) describes custom theme configuration.
- Expected risks: Preflight resets global element styling; `.btn`, `.card`, menu and modal names overlap existing components; global root/theme/scrollbar behavior can escape a wrapper. DaisyUI documents component prefixes, theme-variable roots and component inclusion/exclusion; these do not scope every selector or event. Audit generated CSS even in the isolated document. [DaisyUI configuration](https://daisyui.com/docs/config/), [Tailwind Preflight](https://tailwindcss.com/docs/preflight).
- Configure source scanning explicitly for the lab's templates/includes/state maps. Tailwind reads text tokens rather than evaluating Django expressions; use complete class strings and documented safelisting for supplied variants. Do not build classes such as `bg-{{ status }}-500`, scan the whole repository or generate utilities from arbitrary customer data. [Tailwind class detection](https://tailwindcss.com/docs/detecting-classes-in-source-files).
- CSS components do not establish the existing setup-guide workflow or accessible focus behavior. Budget a small, lab-local interaction layer/native dialog treatment for drawer/menu/disclosures and setup intent previews. Preserve existing identifiers/metadata without loading Bootstrap as a hidden second framework. A production adapter for legacy `window.bootstrap`/`data-bs-*` consumers would require separate verification; this experiment cannot claim drop-in compatibility.

### Comparable dependency and Django integration review

| Review item | A — Tabler + Bootstrap | B — Tailwind + DaisyUI |
| --- | --- | --- |
| Dependency inventory | Core distribution, bundled interaction runtime, optional Sass/build toolchain; no duplicate Bootstrap | Tailwind compiler, DaisyUI plugin, chosen build integration and a small interaction layer |
| Design translation | Map tokens into the pinned Tabler/Bootstrap component variables | Map tokens into custom DaisyUI theme variables and Tailwind layout/style utilities |
| Django binding | Later server-rendered includes consume existing context and named routes | Same context/routes; explicitly scan all relevant template sources |
| Legacy interaction compatibility | Verify component globals and events despite familiar Bootstrap attributes | Verify a local behavior adapter; CSS alone cannot run Bootstrap-dependent guidance |
| CSS coexistence | Global Bootstrap/Tabler components and reset require a separate document | Reset, component classes, root variables and utilities require a separate document |
| Theme persistence | Bypass/adapt framework defaults to the common lab-only key | Same common key; map to the custom DaisyUI theme attribute |
| Browser support | Current docs list Chrome/Edge 123+, Firefox 128+, Safari/iOS 17.5+ | Tailwind 4 docs list Chrome 111+, Firefox 128+, Safari 16.4+; check DaisyUI and chosen components as well |
| Asset/maintenance evidence | Record actual generated CSS/JS/fonts, dependency count, adapters and upgrade points | Record the same measurements; do not assume utility generation is free or a smaller bundle guarantees better UX |

Browser floors above are the **documentation checked on 15 November 2026**, not a confirmed Motionmate support policy or a guarantee for future package versions. Pin and verify against the agreed browser matrix before building. Sources: [Tabler browser support](https://docs.tabler.io/ui/getting-started/browser-support), [Tailwind compatibility](https://tailwindcss.com/docs/compatibility). Neither framework is automatically the safer choice merely because its component names are familiar or its build is newer.

No runtime bundle size, production speed, accessibility pass or engineering effort estimate is claimed before prototypes exist. Optional chart/map/editor libraries are outside both builds. Future asset comparisons use the same server, compression, cache and font conditions and report CSS, JS and fonts separately; the audit's 7.82 MB local header total is not a fair production speed benchmark.

## 8. Acceptance criteria for the later comparison

These are **requirements to test later**, not passed checks from Step 2. A/B must pass all hard functional/isolation/accessibility gates before aesthetic preference is used to select a direction.

| ID | Objective check |
| --- | --- |
| V1 — Desktop priority | In the canonical 1440 × 900 default state, both appointment/follow-up headings start at or above document y=240px and at least three rows from each are visible before y=900px. Secondary metrics/sharing do not precede them. |
| V2 — Tablet priority | At 768 × 1024, the first appointment starts by y=320px; follow-up heading starts by y=820px and its first request is visible by y=1024px. |
| V3 — Mobile priority | At 390 × 844, first appointment starts by y=300px, follow-up heading by y=960px and first request by y=1120px with the shared three-row preview. Both queues precede secondary metrics. This allows readable rows and a short scroll to follow-up, rather than forcing both queues into one screen. Compare against baseline appointments y=2345 / follow-up y=1661. No fonts are reduced to meet these targets. |
| V4 — Responsive integrity | All six standard viewport/theme captures have document scroll width ≤ viewport width + 1px, no overlaps or clipped controls, and identical content order. Supplemental 320px/200% zoom checks reflow without lost essential content. Long states may exceed normal vertical targets. |
| V5 — Useful density | No eight standalone KPI cards; no chart. Every existing metric subject/period remains findable in its assigned region. Mobile booking input ≥300px at 390px; actions and metadata follow §4 sizes. |
| V6 — Theme completeness | Each component's default/hover/focus/busy/disabled/error and overlay states are legible in both themes; no white utility patches or low-contrast brand mark in dark mode; no wrong-theme flash in recorded loading. |
| A1 — Accessibility | Every interactive element has an accessible name and visible focus; keyboard traversal follows reading order. Focus is not obscured by sticky chrome, drawer/account focus returns correctly, and onboarding dismissal semantics remain intact. Text/meaningful-control contrast and 44px lab targets are measured, not inferred from library defaults. |
| F1 — Data and route parity | A/B fixture values, instants, counts, row ordering, currency and lifecycle/payment labels match exactly; normalized visible text differs only for documented framework-independent responsive labels. Existing route names, IDs and query parameters match the contract. No hidden recomputation or added workflow action. |
| F2 — Preview honesty | Both use the same three/five preview rules. Reveal-more exposes all supplied rows without a fetch. Today totals, next scheduled rows and future dates retain distinct meanings. Timezone-boundary variants and unavailable/zero states render honestly. |
| F3 — Permissions and guidance | Owner/admin/staff/accountant/viewer and independent entitlement states follow supplied current predicates; read-only affects writes as currently defined. All onboarding hooks resolve to visible/revealable targets. Mutation intents match existing field names; lab previews execute no application POSTs. |
| F4 — Interaction evidence | Scripted nav/account/theme/disclosure/copy/setup-preview checks run in both. Zero unexpected page errors or failed required assets. The missing Services search target is not carried into either prototype. |
| I1 — Isolation | Only the respective lab asset graph loads. No ordinary database/provider requests, production template/static/route/config changes, production preference writes, or assets from the other framework/Phoenix/Logistics. A production-page asset comparison later proves Logistics has no lab dependency. |
| E1 — Fair evidence | Same browser build, viewport/DPR, font files, fixture/state manifest, clock/timezone, capture delays and scripts; initial/default and expanded states labeled. Save viewport/full-page pairs and raw metrics for both. Report any unavailable browser/tooling as a limitation. |

For human visual review, hide the framework names in product screenshots and alternate left/right order. Use the same tasks: identify the next appointment and its local time; identify the two online requests needing review; open the existing follow-up destination; distinguish invoice status from payment status/balance; find and copy the booking URL. Record success/errors and time under the same conditions. Ask reviewers to score task hierarchy, mobile clarity, brand distinctiveness and light/dark polish separately from dependency/integration cost. Do not announce a winner from framework reputation, mockup polish alone or one favorable viewport.

## 9. Human approval checkpoints

These checkpoints describe subsequent decisions. They do not interrupt completion of this specification and are not authorization to begin the next phase.

| Checkpoint | Concrete material for review | Approval authorizes |
| --- | --- | --- |
| H1 — Direction and shared contract | This brief: evidence, palette/type candidate, desktop/tablet/mobile IA, mobile disclosures, parity data/tasks and F1–F6 correction ledger | A separate request may authorize building both isolated prototypes and the exact dependencies/assets. Approval of the design alone does not permit package installation. |
| H2 — Before acquiring/building dependencies | Pinned versions, licenses/font files, browser-support matrix, lab-only paths, asset/build graph and no-database harness plan | Only the specifically approved lab setup. No production/Django route changes or ordinary database writes. |
| H3 — Prototype comparison | Both complete A/B evidence sets, every required state, acceptance results, missing checks, asset totals and integration-risk notes | Select/refine a visual direction and decide whether either framework merits a separate integration proposal. Neither candidate is preselected. |
| H4 — Correctness and Services integration | Explicit decisions on search removal, timezone display, accessibility fixes, hooks, finance scope and a dashboard-only implementation/rollback plan with Logistics preservation evidence | Only separately requested application work. No schema/data changes, broad shell migration or other vertical redesign by implication. |
| H5 — Release | Reviewed implementation and actual checks against authorized runtime/provider boundaries | Commit/push/deployment or external changes still need explicit authorization for those actions; a prototype approval does not grant it. |

## 10. Unresolved decisions

| Decision | Proposed default / what remains to decide |
| --- | --- |
| Font and brand treatment | Manrope, existing unchanged mark on a quiet tile, canonical Motionmate wordmark. Human review must confirm the face, logo tile/wordmark balance and approved local font asset; neither prototype gets a different font. |
| Accent intensity and dark-mode character | Indigo primary with restrained violet, navy dark surfaces. Final rendered accent coverage and hover/focus pairings need approval; calculated contrast does not prove visual quality. |
| Mobile preview density | Three appointment and three request rows, reveal remainder locally. Review whether three gives enough context and whether longer real names need an alternate density; any revision applies to both frameworks. |
| Timezone format | Workspace-local, explicit IANA zone and date-sensitive UTC offset, 12-hour time matching current customer-facing examples. Confirm locale/12-versus-24-hour expectations separately; no new timezone preference setting. |
| “Today's appointments” wording | Keep authoritative today count and explicitly label the capped next-scheduled preview. Human review may prefer `Appointments` with `Today: 5 scheduled` if the combined heading could imply a complete day view. No full-day query is assumed. |
| Finance completeness | Preserve current supplied values and visible scope with explicit currency. Decide separately whether the hidden currency/review table belongs on this dashboard and how to explain all-currency counts versus workspace-currency money; no new accounting policy. |
| Framework versions and supported browsers | No exact lock selected or dependency acquired. Confirm the actual Motionmate browser floor before choosing package minors; neither framework's current defaults establish that policy. |
| Safe prototype destination/setup harness | Approve a lab-only read-only route-intent map and setup-action recorder. Real destination workflows remain outside the prototype; static interaction success cannot substitute for Django integration tests. |
| Production boundary and framework outcome | Retain Phoenix, adopt one candidate for this dashboard, or implement the approved visual language with another explicitly reviewed integration remains undecided. Logistics and other Services pages retain their current implementation throughout this phase. |

**Step 2 completion:** only this specification was added. Existing audit/screenshots/metrics and application files were preserved. Local evidence/source reads, primary-documentation checks, candidate token calculations and document link/whitespace/scope checks were performed. No prototypes, dependencies, migrations, database changes, commits, pushes or deployments were made. Stop here for human review.
