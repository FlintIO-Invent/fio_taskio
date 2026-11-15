# Motionmate frontend baseline audit

> Historical step report. Steps 1–8 were subsequently completed and approved.
> Current setup/approval boundaries: [reproducible workflow](REPRODUCIBILITY.md).
> Complete historical evidence is in the [separate local archive](PRESERVATION.md).

Completed: **15 November 2026**. Mode: **Audit**. Primary vertical: **Services**.
Page: **`/crm/agent/dashboard/`**, named route `agent_dashboard`.
Shared scope: workspace shell, branding, Phoenix assets, navigation and theme controls.

## Diagnosis

The Services dashboard renders reliably in the captured states, but its hierarchy prioritizes summaries and setup over daily work. Eight equally weighted metric cards and the booking-link panel precede the work queues. At 390 CSS pixels, Booking Follow-Up begins **1,661px** down the document and Upcoming Activity begins **2,345px** down. At 1440px the queues still stack, because this Phoenix installation starts `xxl` at **1540px**.

The main weaknesses are task placement, mobile density, cramped card headers, tiny supporting text, and competing surface rules. There are also two concrete interaction/presentation defects: the Services mobile search button targets a missing modal, and appointment times render in UTC while dashboard day boundaries use the workspace timezone. Phoenix already supplies the components needed for a later, scoped improvement; replacing the theme is unnecessary.

This report contains recommendations only. Application code and configuration were not changed.

## Evidence and safe capture environment

- Read the root [AGENTS.md](../../../AGENTS.md), [motionmate-ui skill](../../../.agents/skills/motionmate-ui/SKILL.md), and its [Phoenix map](../../../.agents/skills/motionmate-ui/references/phoenix-map.md). The user explicitly authorized the report, screenshots and safe test data; those instructions govern the skill's default prohibition on audit artifacts/fixtures.
- Used the existing `.venv/bin/python`, installed Python Playwright, and cached Chromium at `/home/mzero/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome`. No packages or browser binaries were installed.
- Served the **existing Django URLconf, view, context processors, templates and static assets** through `StaticFilesHandler` on a temporary `127.0.0.1` port. These are browser captures of the application route, not reconstructed HTML or design mockups.
- Temporary settings module: `/tmp/motionmate-ui-audit-20261114/audit_settings.py`. The only database was a fresh SQLite file at `/tmp/motionmate-ui-audit-20261114/disposable.sqlite3`, selected before `django.setup()`. Its schema was created directly with `schema_editor.create_model()`. **No migration command, migration executor or migration file ran.** This bypasses historical data migrations and does not verify migration readiness.
- Fixtures used synthetic workspaces and `.test` contact addresses. The populated owner fixture has five clients, five open requests (two public), five upcoming appointments, two draft invoices and three issued unpaid invoices. There are no real customers, receipts or provider transactions in this evidence.
- Additional captures cover an empty workspace, a plan without appointments/invoicing/online booking, staff and viewer access, and long names/company text. Staff and viewer are separate actual role states, not simulated permission flags.
- Fixture time was fixed to **14 November 2026, 09:00 UTC**; the workspace timezone is `America/Lower_Princes`. The dates inside the screenshots are synthetic. The report completion date is independent of that clock.
- Email/cache were in memory; Stripe was disabled and its keys blanked in temporary settings. Browser requests were GET-only. No application forms were submitted. Service workers were blocked to avoid a previous browser cache influencing the baseline. Fonts and CDN assets loaded successfully.
- Ordinary local, staging, production and Test Lab databases were not connected to or written. No route edits, business-logic changes, package installation, migrations, commits, pushes or deployments were performed. Temporary browser servers were stopped and the disposable database was removed after capture.

[baseline-metrics.json](baseline-metrics.json) records viewport sizes, geometry, computed styles, network responses, errors, role checks, interactions, CSS comparisons and hashes of the inspected application entry points. It contains no session cookie values. The temporary capture scripts remain under `/tmp/motionmate-ui-audit-20261114/`; their paths are local working evidence, not durable repository tooling.

### Screenshot index

All screenshots are PNGs at **device scale factor 1**. Widths are CSS pixels. Both an unchanged initial viewport and the complete page were saved; a full-page image is taller than its viewport.

| Viewport | Light viewport | Light full page | Dark viewport | Dark full page |
| --- | --- | --- | --- | --- |
| 1440 × 900 | [1440 light](screenshots/services-dashboard-populated-1440-light-viewport.png) | [Full](screenshots/services-dashboard-populated-1440-light-full.png) | [1440 dark](screenshots/services-dashboard-populated-1440-dark-viewport.png) | [Full](screenshots/services-dashboard-populated-1440-dark-full.png) |
| 768 × 1024 | [768 light](screenshots/services-dashboard-populated-768-light-viewport.png) | [Full](screenshots/services-dashboard-populated-768-light-full.png) | [768 dark](screenshots/services-dashboard-populated-768-dark-viewport.png) | [Full](screenshots/services-dashboard-populated-768-dark-full.png) |
| 390 × 844 | [390 light](screenshots/services-dashboard-populated-390-light-viewport.png) | [Full](screenshots/services-dashboard-populated-390-light-full.png) | [390 dark](screenshots/services-dashboard-populated-390-dark-viewport.png) | [Full](screenshots/services-dashboard-populated-390-dark-full.png) |

| Additional state, 390 × 844, light | Viewport | Full page |
| --- | --- | --- |
| Empty, modules enabled | [Viewport](screenshots/services-dashboard-empty-390-light-viewport.png) | [Full](screenshots/services-dashboard-empty-390-light-full.png) |
| Modules locked by plan | [Viewport](screenshots/services-dashboard-locked-390-light-viewport.png) | [Full](screenshots/services-dashboard-locked-390-light-full.png) |
| Staff role | [Viewport](screenshots/services-dashboard-staff-390-light-viewport.png) | [Full](screenshots/services-dashboard-staff-390-light-full.png) |
| Viewer role | [Viewport](screenshots/services-dashboard-viewer-390-light-viewport.png) | [Full](screenshots/services-dashboard-viewer-390-light-full.png) |
| Long customer/company/workspace text | [Viewport](screenshots/services-dashboard-long-390-light-viewport.png) | [Full](screenshots/services-dashboard-long-390-light-full.png) |

Expanded navigation: [390px](screenshots/services-navigation-390-light.png), [768px](screenshots/services-navigation-768-light.png).

## Current information hierarchy

The [Services dashboard template](../../../src/templates/crm/agent_dashboard/agent_dashboard.html) renders the following sequence:

1. Shared fixed top bar and vertical navigation; collapsed navigation below `lg` (992px).
2. Date, personalized “Welcome back” heading, workspace name and owner/admin Setup Guide action.
3. Four operational metric cards: Total Clients, Open Requests, Online Booking Review, Appointments Today.
4. Four finance cards when permitted: Draft Invoices, Invoices with a balance due, Issued Invoice Value This Month, Outstanding balance. Otherwise an explanatory locked/restricted alert.
5. Online Booking Link, when the existing readiness conditions are met.
6. Booking Follow-Up, then Upcoming Activity, Invoice Follow-Up and Workspace Details. The intended 7/5-column split uses `col-xxl-*` and therefore does not activate at any requested capture width.
7. Conditional welcome modal/setup guide, outside the page content flow.

The populated page has **13 cards**. Counts and supporting labels carry similar visual weight despite representing different periods and tasks. The top-row request/review cards overlap conceptually with Booking Follow-Up; the invoice cards repeat context available in Invoice Follow-Up. The summary cards themselves are not links. The page's main title is a greeting rather than “Dashboard” or an operational task, and starts at `h2`; metric values are `h3`, section titles `h4`, and record titles `h6`.

The [dashboard view](../../../src/apps/crm/views.py), `agent_dashboard` at line 587, retains authoritative tenant/module/role checks. It caps request, appointment and invoice queues at five rows. Upcoming appointments are scheduled records ordered by start time; invoice follow-up uses collectible balances from the existing billing presentation. Requests remain `Lead` rows and link into the existing Appointments workspace. This audit proposes no replacement records or workflow.

### Measured responsive behavior

Positions below are document coordinates, measured before any menu or theme interaction; light/dark geometry matched.

| Measurement | 1440px | 768px | 390px |
| --- | ---: | ---: | ---: |
| Document width / viewport width | 1440 / 1440 | 768 / 768 | 390 / 390 |
| Document height | 2,599px | 2,943px | 3,963px |
| Metric columns per row | 4 | 2 | 1 |
| Online Booking Link top | 528px | 812px | 1,333px |
| Booking Follow-Up top | 737px | 1,054px | 1,661px |
| Upcoming Activity top | 1,302px | 1,619px | 2,345px |
| Invoice Follow-Up top | 1,856px | 2,173px | 3,058px |
| Workspace Details top | 2,234px | 2,551px | 3,498px |
| Booking URL input width | 858px | 472px | 94px |

No horizontal document overflow was measured in the captured baseline or additional states. Long content wraps, but increases the mobile Booking Follow-Up card from **668px to 964px** and pushes Upcoming Activity to **2,665px**. In Workspace Details, the long business name starts immediately beside the “Business” label and wraps through several lines; there is no reserved label/value gap.

At 390px the first viewport consists of the greeting/setup control and operational metric cards. At 768px neither work queue reaches the first viewport. At 1440px only the start of Booking Follow-Up is visible; appointments and invoice follow-up require scrolling.

## Shared components and asset entry points

| Component | Existing implementation and impact |
| --- | --- |
| Workspace shell | [dashboard_parent.html](../../../src/templates/inheritance/dashboard_parent.html): shared by Services and Logistics. Owns navigation, account menu, theme control, subscription alerts, work-location include and asset order. Changing it can affect both verticals and all workspace pages. |
| Services navigation | [workspace_navigation.html](../../../src/templates/appointments/includes/workspace_navigation.html): All Bookings & Requests, Needs follow-up and Booking Settings under the existing entitlement/role conditions. Also read the [Appointments contract](../../services_unified_appointments.md). |
| Branding | [motionmate_logo.html](../../../src/templates/includes/motionmate_logo.html), existing SVG marks and `user*.css`. Visible wordmark currently reads **MotionMate**, while AGENTS.md specifies **Motionmate**. Internal names must remain intact. |
| Booking sharing | [public_booking_share_card.html](../../../src/templates/businesses/includes/public_booking_share_card.html): reusable readiness/status, readonly URL, Copy/Open controls and setup explanation. Clipboard action has no success/failure feedback. Clipboard operation was not exercised. |
| Invoice meaning | [invoice_status.html](../../../src/templates/billings/includes/invoice_status.html), [presentation.py](../../../src/apps/billings/presentation.py), and [vocabulary](../../invoice_payment_terminology.md): lifecycle and recorded payment state remain distinct. No frontend settlement calculation is warranted. |
| Setup guidance | [welcome modal](../../../src/templates/crm/agent_dashboard/includes/onboarding_welcome_modal.html), [guide panel](../../../src/templates/crm/agent_dashboard/includes/onboarding_guide_panel.html), [onboarding-guide.js](../../../src/static/assets/js/onboarding-guide.js). Contains existing POST/CSRF actions, persistent state and spotlight hooks. Screenshots use an already-dismissed welcome state. |
| Access context | [context_processors.py](../../../src/apps/businesses/context_processors.py), [utils.py](../../../src/apps/businesses/utils.py), and [workspace.py](../../../src/apps/appointments/workspace.py). Keep active-Business resolution, membership, module access, write state and role controls server-authoritative. |
| Logistics | The same route branches to [dashboard_snapshot.html](../../../src/templates/logistics/includes/dashboard_snapshot.html). The shell conditionally loads [logistics-mobile.css](../../../src/static/assets/css/logistics-mobile.css) / [logistics-mobile.js](../../../src/static/assets/js/logistics-mobile.js) and adds `.logistics-workspace`. Its scoped mobile layout/touch rules do not apply to Services. Source inspection only; no Logistics browser pass is claimed. |
| Public site | [public_site/base.html](../../../src/templates/public_site/base.html) loads its separate Silicon CSS/JS under `static/public_site/`. Those assets were not loaded into the workspace. Marketing pages were not visually audited. |

The shell's effective loading order is:

1. PWA head include (`pwa.css`, deferred `pwa.js`), SimpleBar and `assets/js/config.js`.
2. Vendor CSS, Google Nunito Sans and Unicons, then Phoenix `theme-rtl.min.css` / `theme.min.css`, then `user-rtl.min.css` / `user.min.css`. The inline direction switch disables the unused pair. The captured LTR CSSOM has only the default theme/user pair active.
3. Conditional Logistics mobile assets.
4. Content and conditional onboarding script.
5. Popper, Bootstrap, AnchorJS, is.js, Font Awesome, Lodash, List.js, Feather, Day.js, `assets/js/phoenix.js`; then ECharts, Mapbox, Turf CDN, Swiper, TinyMCE, Dropzone, Choices and Flatpickr. `dashboards/crm-dashboard.js` is loaded for Services, although this template contains none of its demo chart containers.

Assets were served from **`src/static/`**, not `src/staticfiles/`. Browser CSSOM comparisons found matching selector/declaration sets between `user.css` and `user.min.css`, and between the RTL counterparts, after whitespace/numeric normalization. Rule ordering differs; there is no demonstrated missing-declaration/stale-output defect. Do not assume a future source edit automatically updates the loaded minified files.

The captured uncached 1440px light load recorded **41 GET responses** with approximately **7.82 MB** summed `Content-Length` values. It includes both direction theme stylesheets being downloaded even though one becomes disabled. Mapbox JS (~1.55 MB), Font Awesome JS (~1.53 MB), the two theme CSS files (~1.12 MB each), and ECharts (~1.03 MB) dominate this local uncompressed sample. This is an asset-inventory observation, not a production transfer-size or page-speed score.

## Findings and priorities

### P1 — Daily work is buried by equal-weight summaries

**Observed:** the first useful record queue starts 1,661px down on mobile; appointments start 2,345px down. Setup and link-sharing controls receive more prominent placement than reviewing or scheduling work. Counts provide no direct drill-down.

**Source:** dashboard template lines 44–197; `col-sm-6 col-xl-3` metrics and `col-xxl-7/5` work areas. Phoenix [grid variables](../../../design_references/phoenix/src/scss/theme/_variables.scss) explicitly define `xxl: 1540px`.

**Recommendation:** prioritize today's appointments and existing needs-follow-up queue, reduce summary-card density on mobile, and make any future drill-down use the current named routes/query parameters. Move the sharing/settings material lower. Choose a desktop split against Phoenix's actual breakpoints. Preserve the existing module/role branches and onboarding targets.

### P1 — Services mobile search is broken

**Observed:** at 390px, clicking `[data-bs-target="#searchBoxModal"]` finds zero target elements, opens no modal, and raises **`Cannot read properties of undefined (reading 'backdrop')`**. Baseline captures before this deliberate click had no page errors.

**Source:** shared shell lines 321–325. The Services branch exposes this control below `lg`; the Logistics branch instead links to the existing parcel list and supplies `aria-label="Search parcels"`.

**Recommendation:** resolve the Services control within an explicitly scoped follow-up. Reuse a verified existing search destination/interaction or remove the unsupported affordance after its intended behavior is decided. Do not invent a new application route during presentation work.

### P1 — Appointment times do not communicate the workspace timezone

**Observed:** with workspace `America/Lower_Princes`, an appointment at `2026-11-14T11:00:00Z` appears as **“Nov 14, 11:00 AM”**. Its workspace-local time is **07:00 AM**. Workspace Details lists the workspace timezone, but individual displayed times have no zone label.

**Source:** `_business_local_periods` in `crm/views.py:450` computes day/month boundaries in the Business timezone. The dashboard's date filters at lines 233–237 and 281 use Django's active/default timezone; `taskio/settings.py` defaults to UTC and the inspected request path does not activate the Business timezone.

**Recommendation:** agree on explicit workspace-local timestamp presentation, including a timezone label where needed, while preserving stored instants and authoritative booking/count rules. This is a presentation diagnosis; no scheduling behavior was changed or end-to-end timezone regression test run.

### P1 — Several controls lack adequate names, focus treatment or text contrast

**Observed:** the 390px brand link has an empty accessible name because the wordmark is hidden and the mark image has `alt=""`. The Services search link is also unnamed. The theme control's captured accessibility subtree exposes only an image. The account button correctly exposes **“Account menu”**. The first keyboard Tab reaches Toggle Navigation, whose computed outline and box-shadow are both absent.

Computed normal-size primary text is `#3874ff`. Its contrast is approximately **4.00:1** against the light card-header `#fbfcfe`, below the 4.5:1 normal-text target. White text on that primary blue is approximately **4.11:1**. This affects the small outline actions and filled Open button. Supporting `#525b75` text on white measures **6.75:1**; its main issue is size rather than that sampled contrast.

**Source:** shared shell lines 293–325, logo include, and loaded Phoenix button styles. Ratios use sRGB relative luminance from captured computed colors; this is a limited sample, not a full accessibility conformance audit.

**Recommendation:** provide stable accessible names for icon controls/home link, verify keyboard-visible focus, and select accessible button variants/tokens across both themes. Any shared change needs Services and Logistics verification. Do not alter global primary colors without evaluating dependent compiled component variables.

### P2 — Mobile cards fit, but their interiors are cramped

**Observed:** Booking/Upcoming/Invoice headers keep title, description and action in the same flex row. At 390px “Upcoming Activity” and “View Appointments” wrap onto two lines. Workspace Details places three separate action rows beside a squeezed title. The booking URL input is only **94px** wide. The long business name crowds its label. Settings actions are **33px** tall, the hamburger is **36px**, and Copy/Open controls are **38px** tall.

**Source:** dashboard card headers at lines 200, 260, 324 and 379; booking-share input group; Workspace Details `justify-content-between` rows. The Services branch lacks the Logistics-specific 44px mobile control treatment.

**Recommendation:** stack card-header content/actions at small widths, give the URL a full row and put its actions together, and use a stable label/value layout with gaps. Adopt appropriate Services-scoped touch sizing. Keep every URL, conditional, copied value and control hook intact.

### P2 — Broad CSS overrides create competing surface rules

**Observed/source:** [user.css](../../../src/static/assets/css/user.css), lines 117–167, applies literal light-mode colors and shadows to every `.content .card`, card header, list divider, form field and some badges. These rules affect both verticals. The local KPI card computes to a `#d9e2ef` border and an 8px/20px shadow. The booking-share include instead uses `border-0 shadow-sm`; those important utilities win, producing a borderless card with a 2px/4px shadow. The neighboring cards consequently have different elevation/border treatments.

Light mode adds a custom surface system while dark mode mostly retains Phoenix defaults. Global `bg-body-tertiary` and dark `bg-light/bg-white` overrides use `!important`; intended semantic utility colors can therefore be replaced. This is an existing cascade conflict, not evidence that Silicon CSS leaks into the workspace.

**Recommendation:** decide the desired surface hierarchy and map it to Phoenix semantic tokens. Scope any Services composition changes to Services, and assess shared token changes against both verticals. Keep default/RTL minified asset handling explicit.

### P2 — Small metadata and redundant empty/locked content weaken scanning

**Observed:** metric labels/record secondary text use **12.8px** (`fs-9`); dates and service/title details use **10.24px** (`fs-10`). Fine text is especially hard to scan on the dark mobile page. Eight zero-value summary cards still precede empty-state actions. The locked page repeats invoice restrictions in both an alert and a separate card, and displays “0” for unavailable Online Booking Review while Appointments Today says “Locked”.

**Source:** loaded [theme.css](../../../src/static/assets/css/theme.css), `fs-9`/`fs-10`; dashboard metric/empty/restricted branches. The heading structure also treats each metric value as a heading, making the section outline noisy. Navigation groups organize Services settings under Home, records under Workspace and bookings under Modules; the captured dashboard link has no distinct current-page treatment.

**Recommendation:** use a consistent readable metadata scale, preserve the distinction between zero and unavailable, simplify repeated explanations, and make empty-state task entry easier to reach. Retain the existing routes, role checks and draft-preserving creation flows. Use semantic page/section headings without changing Phoenix typography unnecessarily.

### P2 — Existing finance context is generated but hidden

**Source and browser check:** dashboard line 178 wraps `{% include 'billings/includes/finance_totals.html' %}` in an **HTML comment**. Django still renders the include, but its currency/review table is not a DOM section and is invisible. The Logistics snapshot contains the same commented include. The browser recorded `financeTableVisible: false`.

The Services view computes per-currency finance totals and review information, while visible aggregate money cards select the workspace currency; open invoice counts sum the currency rows. The [invoice vocabulary documentation](../../invoice_payment_terminology.md) describes separated currency/unverified-balance presentation more broadly than this dashboard currently exposes. The captured fixture uses one currency and no review cases; mixed-currency/review behavior was not visually tested.

**Recommendation:** review the dashboard's intended currency/review presentation against the existing authoritative finance projection. Do not reinterpret “issued” as paid or turn issued invoice value into cash revenue. This audit neither uncommented the include nor changed accounting policy.

## Phoenix reference review

`design_references/phoenix/` exists, is Git-ignored, and identifies **Phoenix 1.23.0** in [package.json](../../../design_references/phoenix/package.json). It was read only; no build, edit or force-add occurred.

Relevant examples/source inspected:

- [CRM dashboard](../../../design_references/phoenix/public/dashboard/crm.html): responsive composition and metric/icon patterns. Its `icon-wrapper-sm` example uses a dedicated pseudo-element shadow class and a sized/layered icon; the app instead puts background classes directly on the wrapper, resulting in small square icon patches. The demo's graphs/data are not requirements for Motionmate.
- [Card examples](../../../design_references/phoenix/public/modules/components/card.html): the responsive `row g-3` header pattern gives content `col-12 col-md` and actions `col col-md-auto`, avoiding the dashboard's rigid narrow flex headers.
- [Dark-mode documentation](../../../design_references/phoenix/public/documentation/customization/dark-mode.html), [variables](../../../design_references/phoenix/src/scss/theme/_variables.scss), [dark variables](../../../design_references/phoenix/src/scss/theme/_variables-dark.scss), [root tokens](../../../design_references/phoenix/src/scss/theme/_root.scss), and [CRM Sass](../../../design_references/phoenix/src/scss/theme/_crm.scss): existing theme controls, typography, breakpoints and icon behavior.

The smallest future direction is a Services dashboard composition using the existing Phoenix grid, cards, buttons and semantic tokens. Resolve broken affordances and timestamp clarity first; then improve the work hierarchy and mobile card interiors. These recommendations do not authorize implementation.

## Verification results and limits

- Actual Chromium captures: six populated viewport/theme combinations plus five additional mobile states; **24 PNGs** including viewport/full-page pairs and two expanded-navigation captures. The required 1440/768/390 widths were measured in-browser with DPR 1 and visually inspected.
- All captured dashboard GETs returned 200. Populated/empty/locked/staff/long captures had zero page errors and zero failed asset requests. Viewer loaded successfully; its deliberate search click reproduced the separately recorded error.
- Navigation opened/closed at 768/390; desktop sidebar collapsed/expanded at 1440. Account menu opened and closed with Escape, and theme controls switched light → dark → light at all three widths. An initial mobile keyboard focus sample was recorded. These are targeted interaction checks, not a complete keyboard/screen-reader audit.
- The viewer capture omits Setup Guide and the Workspace Details settings actions but retains invoice/appointment reads. Current `BILLING_VIEW_ROLES` and `APPOINTMENT_VIEW_ROLES` include all five valid Services roles, so the template's role-restricted finance/activity branches were source-inspected, not claimed as visually exercised. Module-locked rendering was captured separately.
- Long text, empty data and module locks were checked in light/mobile only. Arbitrarily long unbroken strings, extreme monetary values, admin/accountant variants, subscription payment-grace/read-only states, RTL rendering and reduced-motion interactions were not browser-tested. The reference/application reduced-motion and RTL sources were inspected.
- The server-rendered dashboard has no dedicated asynchronous loading state in this path. Toast/message/error branches were inspected in source; no validation failure, provider error, offline/PWA installation, onboarding POST or transaction was induced.
- No production/staging/ordinary-runtime behavior, live provider readiness, PostgreSQL concurrency, migration behavior, production static collection or full-site accessibility/performance result is implied by this disposable SQLite/browser audit. Browser access was available; there was no screenshot blocker.
- Checked screenshot dimensions, artifact links, whitespace and working-tree scope. Only this report, screenshots and evidence metadata were added. No automated application regression suite was run because application code did not change.

**Stopped after the audit.** No frontend implementation or rollout was performed.
