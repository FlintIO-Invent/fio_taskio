# Motionmate UI Lab — production integration audit

> Historical step report. Steps 1–8 were subsequently completed and approved.
> Current setup/approval boundaries: [reproducible workflow](REPRODUCIBILITY.md).
> Complete historical evidence is in the [separate local archive](PRESERVATION.md).

**15 November 2026 · AUDIT ONLY · Motionmate Services dashboard**

Target: named route `agent_dashboard`, `/crm/agent/dashboard/`. Recommend **B:
progressive component integration in the existing Phoenix shell**, with the
approved visual tokens, content composition and locally served Manrope scoped
to this dashboard. Retain the existing navigation and Bootstrap interaction
system. Do not load the lab's Tailwind/DaisyUI distribution into Phoenix.

This recommendation adopts the **visual direction**, not the Tailwind/DaisyUI
production packages. That distinction requires explicit approval. If using
those packages in production is mandatory, choose a separately scoped isolation
project under approach A rather than calling a mixed stylesheet safe.

**No implementation authorization is inferred.** The only artifact created in
this audit is this requested report. All proposed paths and phases below are
future work. No application process, database query, fixture, test suite,
browser capture, compiler, migration, static collection or deployment ran.

## 1. Existing architecture and dependencies

### Actual request and template path

| Layer | Current implementation and consequence |
| --- | --- |
| Entry | [CRM routes](../../../src/apps/crm/urls.py) expose `agent_dashboard`; [project routes](../../../src/taskio/urls.py) include CRM at `/crm/`. The [view](../../../src/apps/crm/views.py), beginning at line 587, accepts GET and POST under `business_required()`. A redesign must preserve both methods. |
| Tenant/membership | [business utilities](../../../src/apps/businesses/utils.py) resolve an active Business through active membership and the session, with a first-membership fallback for legacy accounts. Retain that resolver; do not introduce a workspace selector or client-side tenant context. |
| Access before rendering | The dashboard checks effective subscription access before querying normal operational data. Pending/no-workspace-access states can redirect owners to existing billing/subscription destinations and deny other members. Logistics restricted/pending states have separate dashboard responses. These decisions precede the Services presentation. |
| Services data | The view computes tenant-scoped clients, REQUEST Leads, upcoming appointments and authoritative invoice projections. It then renders [agent_dashboard.html](../../../src/templates/crm/agent_dashboard/agent_dashboard.html). |
| Vertical dispatch | The view uses `current_business.has_capability("parcels")` for the operational Logistics branch. The template uses `logistics_dashboard` to include [dashboard_snapshot.html](../../../src/templates/logistics/includes/dashboard_snapshot.html); otherwise it renders Services. Preserve that dispatch and the Logistics greeting/messages/setup behavior. |
| Shared parent | The dashboard extends [dashboard_parent.html](../../../src/templates/inheritance/dashboard_parent.html). **60 templates directly extend this parent**, including Appointments, Clients, invoices/payments, Business Settings, imports and Logistics operations. It currently offers only the `content` block, with no page-specific head asset or body-attribute block. |
| Shared navigation | The parent owns Home, Workspace and module groups, collapse IDs, role/module/write gates and the account dropdown. It includes [Services Appointments navigation](../../../src/templates/appointments/includes/workspace_navigation.html). Parcels precedes Invoices and Clients under its existing guards; do not rebuild/reorder this system. |
| Shared alerts/site context | The parent owns subscription grace/read-only notices, owner-only recovery controls and the Logistics work-location include. Their precedence, forms and conditions must remain intact. |
| Template context | [business context processor](../../../src/apps/businesses/context_processors.py) supplies membership, subscription/access state, `module_access`, `module_write_access`, `module_capabilities`, `role_access` and workspace read/write flags. [Appointments navigation context](../../../src/apps/appointments/workspace.py) independently supplies request/appointment workspace access. The view's `dashboard_*_enabled` flags are the authoritative dashboard display decisions. |

The parent is a complete HTML document with a shared top bar/sidebar and one
outer `main`. New dashboard content should use a named region and one page `h1`,
without copying the prototype's second shell or adding nested main landmarks.

### Loaded asset graph

The checked-in Phoenix reference identifies **1.23.0**; the application Bootstrap
bundle identifies **5.3.6**. `phoenix.js` consumes the existing global Bootstrap.
The reference is read-only and Git-ignored; its Gulp scripts are not an
established application build pipeline.

Current parent asset order:

1. [PWA head](../../../src/templates/includes/pwa_head.html), SimpleBar and
   [config.js](../../../src/static/assets/js/config.js).
2. Dropzone, Choices, Flatpickr, Mapbox, Swiper CSS, Google Nunito Sans, SimpleBar
   CSS and external Unicons; then Phoenix `theme*.min.css` and local `user*.min.css`.
   The direction script disables the unused LTR/RTL pair. Logistics mobile assets
   are additionally loaded only for `LOGISTICS`.
3. Dashboard content and conditional onboarding includes/scripts.
4. Popper, Bootstrap, AnchorJS, is.js, Font Awesome, Lodash, List.js, Feather,
   Day.js, `phoenix.js`, then ECharts, Mapbox, external Turf, Swiper, TinyMCE,
   Dropzone, Choices and Flatpickr. CRM dashboard JS is loaded only when this is
   not a Logistics dashboard/business.

Do not remove apparently unused vendors or change that order during this UI
integration. Asset pruning is a separate performance task. The public site's
Silicon assets are separate and must not enter the workspace.

Phoenix uses `data-bs-theme` and the persisted `phoenixTheme` preference,
including `auto`. The lab's `mm-services-lab-theme`, `data-theme` adapter and
synthetic query-state preferences must not become a second production theme
system. The checked-in shell uses a **992px** expanded-navigation breakpoint,
a **15.875rem** sidebar token and a 64px top-bar token. The reference's grid
`xxl` is **1540px**. The prototype instead uses a 224px sidebar and a 1200px
navigation threshold: these are explicit layout differences, not interchangeable
Bootstrap defaults.

### Existing interactive contracts

- Welcome setup is a Bootstrap Modal; the selected guide is a Bootstrap
  Offcanvas. Preserve `onboardingWelcomeModal`, `onboardingGuidePanel`, their
  labels, targets and auto-open behavior. The guide explicitly has a static
  backdrop and `data-bs-keyboard="false"`; Escape must not silently replace
  its Continue later POST.
- The actual [welcome](../../../src/templates/crm/agent_dashboard/includes/onboarding_welcome_modal.html)
  and [guide](../../../src/templates/crm/agent_dashboard/includes/onboarding_guide_panel.html)
  forms POST to `agent_dashboard` with real CSRF. Operations are `select_journey`,
  `dismiss_welcome`, `guide_step`, `skip_step`, `continue_later`, `start_task`.
  Preserve `selected_journey`, `open_guide_after_select=1`, `current_step_key`
  and `target_step_key` wherever currently present. Journey eligibility,
  progress, prerequisites, locks and CTA redirects come from
  [onboarding.py](../../../src/apps/businesses/onboarding.py), not fixed cards.
- [onboarding-guide.js](../../../src/static/assets/js/onboarding-guide.js) listens
  for Bootstrap offcanvas events, finds the first visible matching target outside
  the guide and manages spotlight positioning/scrolling. Preserve targets
  `clients`, `service-requests`, `booking-settings`, `appointments`, `invoices`,
  `business-settings`, `services`, `availability` and shared navigation targets.
  Avoid clipping/stacking contexts around spotlight targets. Targets must not
  disappear inside closed mobile disclosures.
- The account dropdown, navigation collapse, tooltips and theme control remain
  Phoenix/Bootstrap-owned. Keep their IDs, attributes and current destinations,
  including Team, Data Import, Subscription and Change Password where allowed.
- The [sharing include](../../../src/templates/businesses/includes/public_booking_share_card.html)
  currently uses an inline clipboard call and opens the supplied booking path
  with `target="_blank" rel="noopener"`. Eligibility/readiness comes from
  `get_public_booking_share_context()` in the business utilities.

### Roles, subscriptions and entitlements

| Subject | Actual behavior to preserve |
| --- | --- |
| Appointment reads | `dashboard_appointments_enabled` combines appointment read entitlement with `APPOINTMENT_VIEW_ROLES`; all five current Services roles are in that role set. |
| Invoice reads | `dashboard_invoices_enabled` combines invoicing read entitlement with `BILLING_VIEW_ROLES`; owner/admin/staff/accountant/viewer are included. Do not import Logistics STAFF financial hiding into Services. |
| Writes | Appointment/Lead management roles are owner/admin/staff; billing management also includes accountant. Destination endpoints retain their own write/subscription/quota checks. Dashboard links are not permission grants. |
| Setup | Owner/admin only, based on actual active membership. Visibility and journey data remain server-derived. Dashboard POSTs reject workspace writes in restricted mode. Do not replace this with the lab's fixed setup state. |
| Requests | After dashboard access, the current view computes the request queue/counts without a separate `can_view_module("service_requests")` or request role guard. The Appointments destination does have its own entitlement checks. Treat this as an existing policy question; do not silently add/remove a dashboard request gate in a visual change. |
| Settings/empty links | Current Workspace Details settings links use `can_manage_business_settings`; several empty-state links use manage-role flags without a write flag. They navigate to existing pages. Preserve these actual predicates unless a separately approved permission change is requested. |
| Sharing | Not owner-only: any dashboard reader can receive a ready share region. Readiness requires public-booking write access, enabled booking, a bookable service and active availability. Restricted mode therefore removes readiness even when reads remain available. |
| Access states | Exercise full/trial/grace, restricted read-only, blocked/pending/inactive-plan, no subscription and independent module locks. Do not turn every case into the same lock card: some states redirect or deny before rendering, while no-subscription/module-lock behavior follows the current view. |

Logistics retains its separate location/financial overlay, including STAFF's
bounded invoice scope and absence of business-wide financial dashboard summaries.
The [financial policy](../../logistics_financial_access.md) and its services remain
outside this implementation boundary.

## 2. Map the actual dashboard to the approved Step 4 prototype

Reference: [Step 4 report](04-daisyui-refinement.md),
[renderer](../../../ui-lab/services-dashboard/daisyui/src/render.js),
[styles](../../../ui-lab/services-dashboard/daisyui/src/input.css),
[fixtures](../../../ui-lab/services-dashboard/shared/fixtures.js) and
[controller](../../../ui-lab/services-dashboard/shared/controller.js).
Use the approved [design system](../motionmate-design-system/DESIGN.md),
[components](../motionmate-design-system/COMPONENTS.md) and
[vertical boundaries](../motionmate-design-system/VERTICALS.md).

| Prototype region | Real binding and preservation requirement |
| --- | --- |
| Services overview/date | `current_business.name`, authenticated user's existing name and `dashboard_today`; one `h1`. Actual subscription alerts retain precedence. No fake clock or identity. |
| Appointments first | `dashboard_appointments_enabled`, `today_appointment_count`, `upcoming_appointment_count`, `upcoming_appointments`. Next scheduled query is capped at five, ordered by start/PK and includes only future scheduled records. Today count can include earlier scheduled records. Keep these meanings distinct; do not turn the preview into a full daily agenda. Preserve stored `service_name`/title fallbacks and full Client/company identity. |
| Booking follow-up | `service_request_followups` and existing open/New/month/online-review counts. `follow_up_requests()` uses active NEW/CONTACTED REQUEST Leads with no linked Appointment. Dashboard ordering also prioritizes status, presence of preferred time, preferred time, creation and PK. Keep that server ordering rather than using fixture order or a browser urgency score. |
| Financial region | `draft_invoice_count`, `sent_invoice_count`, `open_invoice_count`, `invoice_value_this_month`, `unpaid_invoice_total`, `recent_invoices`. The view selects at most five collectible invoices in existing newest-first order. Use `invoice.presentation` and the existing status include. |
| Workspace details | Existing Business name/currency/timezone/prefix, Client counts and existing role-gated settings links; no copying profile defaults or adding settings behavior. |
| Booking sharing | Existing `public_booking_share_ready`, URL/path and manual-confirmation explanation. Keep the region absent when not ready; do not expose the shared include's currently unreachable setup-needed branch as an unapproved feature. |
| Mobile compactness | Three initial appointment/request rows with disclosure of remaining supplied rows is a presentation change only. All five remain available; no fetch, new pagination or record limit. Keep full lists readable without JS and preserve focus/disclosure choices through theme changes. |
| Navigation/overlays | Retain the real shell and setup components. The lab renders simplified navigation and native dialogs, intercepts links and records simulated forms. Those adapters must not enter production. |

**Concrete prototype gaps:** the lab `select_journey` form supplies
`selected_journey` but omits the actual `open_guide_after_select=1` field; its
guide has fixed progress/tasks; its URLs do not exercise endpoint authorization;
its currency strings are supplied. Its successful contract comparisons against
other prototypes do not establish complete parity with the real application.
Bind to the actual templates/view/services above and keep existing integration
tests authoritative.

Preserve these route intents with Django `{% url %}` and real identifiers:

| Intent | Existing route/method |
| --- | --- |
| Open complete work list | GET `appointment_list` → `/appointments/` |
| Needs follow-up | GET `appointment_list` with `?state=needs_follow_up` |
| Read scheduled appointment | GET `appointment_detail` with original Appointment ID |
| Read request | GET `staff_lead_detail` with original Lead ID |
| Invoice list/detail | GET `invoice_list` / `invoice_detail`, preserving original IDs |
| Existing invoice empty action | GET `staff_client_list`, Create From Clients, with existing manage-role condition |
| Settings | GET `business_service_list`, `business_booking_settings`, `business_settings` under current guards |
| Share | Supplied absolute `public_booking_url` for copy and relative `public_booking_path` for opening; preserve escaping/attributes |
| Setup | Real POST `agent_dashboard` and `?setup_guide=1` return navigation, preserving CSRF and all operation-specific hidden fields |

No inline scheduling, booking approval, invoice transition, receipt recording,
new search destination or background request API is part of this dashboard design.

## 3. Strategy comparison and recommendation

| Evaluation | A — isolated DaisyUI dashboard | B — progressive visual integration in Phoenix |
| --- | --- | --- |
| CSS isolation | A separate document can exclude Phoenix. A wrapper alone cannot isolate the current build: its output contains global Preflight resets, `:root` theme rules and generic `.btn`/`.modal` selectors despite the DaisyUI `root` option. A same-document mix needs a separately proved build boundary. | Use dashboard-owned component names and scoped semantic colors/typography. No Preflight, DaisyUI theme roots or second set of generic component classes. Existing Phoenix remains loaded and must be tested against scoped overrides. |
| JS | Native-dialog adapters do not implement current Bootstrap setup behavior. Keeping Bootstrap interactions without their CSS requires another compatibility layer. Loading two owners for menus/overlays is unsafe. | Retain the one Bootstrap/Phoenix owner. New JS handles only dashboard disclosures and copy feedback; never intercept normal links, setup forms or accounting actions. |
| Inheritance | A separate parent must recover PWA, alerts, authorization-aware navigation, account links, theme, RTL and setup integrations. Extracting reusable shell pieces would touch a much larger shared surface. | Keep the current parent and route; add narrow, default-preserving extension hooks and one Services content partial. |
| Navigation | Copying prototype navigation would duplicate/drop real destinations and predicates. A common navigation refactor would need its own approved scope. | Existing groups/order, collapse IDs and role/module gates remain the single navigation system. |
| Maintenance | New production npm build/lock, explicit template scanning, scoped output checks, framework upgrades and a second shell/interaction treatment. No such application pipeline currently exists. | One small stylesheet, a small dependency-free script and a licensed font. Use existing static collection. No new npm/runtime dependency or global token migration. |
| Responsive | Can match the reference frame, but introduces different sidebar/drawer breakpoints and handoff to unchanged pages. | Preserve shell breakpoints and adapt content to available width. Full-page screenshots will deliberately differ from the isolated reference; compact task hierarchy can still match. |
| Accessibility | Framework CSS does not supply real setup semantics or authorization. A new shell needs full landmarks, focus, navigation and overlay verification. iframe/Shadow DOM workarounds add sizing/focus/spotlight complexity and are not recommended. | Preserve Bootstrap semantics and server forms; verify the new content and scoped shell repairs. Existing shell defects still require explicit decisions; this approach does not automatically make the whole page conformant. |
| Regression risk | Broad: route dispatch, shell extraction, asset replacement, theme and overlay migration, plus navigation continuity. | Lower if assets are emitted only for the Services dashboard and every rule/handler is scoped. Shared parent changes still require both-vertical regression evidence. |
| Future reuse | Could establish a later independent framework boundary after explicit architecture approval; it does not justify converting other Services pages or Logistics now. | Approved framework-neutral visual patterns can be reused in later authorized screens without sharing business policies. Extract production-wide components only when another real consumer is approved. |

**Recommend B for the first production increment.** Translate the approved
indigo/navy palette, Manrope, readable type, compact time anchors, work-first
composition and mobile disclosures into server-rendered Django content and
dashboard-scoped styles. This avoids maintaining parallel navigation or business
logic and keeps current destination pages familiar.

The fidelity boundary must be accepted explicitly: keep Phoenix navigation
geometry/account structure and Bootstrap setup dialogs. Apply Manrope to the
dashboard content; do not globally change the shell font, sidebar width or
branding. The shared logo's existing “MotionMate” spelling remains a known shell
difference; a shared wordmark change is outside this increment. Do not promise
pixel identity with the prototype's whole document or its y-coordinate targets.
Review the real integrated content at all three widths instead.

If package adoption or the exact Step 4 shell is required, stop and re-scope A
with a common navigation/shell design, production build ownership and a verified
Bootstrap compatibility decision. Do not smuggle that expansion into B.

## 4. Exact proposed implementation boundary

**This is a proposed manifest, not authorization to edit these files.** It covers
the recommended B increment plus the explicitly identified dashboard-only
correctness/accessibility repairs. If a repair is declined, remove that hunk
from the authorized scope and record its unresolved acceptance criterion.

### Existing files requiring modification

| File | Exact intended change and restriction |
| --- | --- |
| `src/templates/inheritance/dashboard_parent.html` | Add an empty `page_assets` block after existing styles and before head close; a `page_body_attributes` block whose default reproduces the existing attributes, including `logistics-workspace`; and a `services_mobile_search` block around only the current non-Logistics search item. Under the server-supplied Services-dashboard marker only, give the brand link and theme checkbox stable accessible names. No nav extraction, reordering, asset removal or condition widening. Hooks default to current behavior on every other page. This shared file requires special approval. |
| `src/templates/crm/agent_dashboard/agent_dashboard.html` | Override those hooks only when `services_dashboard_ui` is true. Load only the new dashboard CSS/deferred JS. Dispatch Services content into the new partial; keep the Logistics branch's current messages/greeting/setup/snapshot output. Keep the real onboarding includes, auto-open scripts and forms rendered once with their current guards. Suppress the unsupported Services search item only on this dashboard if approved. |
| `src/apps/crm/views.py` | In the existing Services context only, add `services_dashboard_ui` derived from `Business.vertical == SERVICE`, `dashboard_timezone` from the already resolved `start_of_today.tzinfo`, and `dashboard_now` localized from the existing `now`. This marker is presentation-only, never authorization. Preserve all querysets, counts, periods, ordering, context aliases, POST handlers, subscription decisions and Logistics early returns. The timezone presentation addition requires explicit approval. |
| `src/apps/crm/tests.py` | Update only assertions for approved renamed/reordered Services content, such as Upcoming Activity → Appointments. Retain tenant, data, role, module, setup and destination assertions. Prefer checking the actual dashboard region so navigation text cannot create a false pass. Do not weaken financial expectations or rewrite unrelated tests. |

### New files

| File | Responsibility |
| --- | --- |
| `src/templates/crm/agent_dashboard/includes/services_overview.html` | Server-rendered Services content: page heading, appointment/request queues, supplied finance, workspace and sharing regions. Consume existing context/status include; do not reproduce query, permission, booking or accounting logic. Dashboard-specific sharing markup consumes the existing share context rather than changing the shared include for other screens. |
| `src/static/assets/css/services-dashboard.css` | Approved light/dark semantic values, content layout/type/components and narrowly scoped focus/target repairs. Use `.mm-services-dashboard` for content and `body.mm-services-dashboard-page` for the limited shell-control repairs. No unscoped element/`.btn`/`.card` rules, root palette reset, vendor imports or global font change. |
| `src/static/assets/js/services-dashboard.js` | A scoped, dependency-free initializer for local three/five-row disclosures and clipboard result/failure feedback. Initialize safely on the real document; do not import the lab controller, simulate forms, own overlays, set theme preferences or intercept navigation. |
| `src/static/assets/fonts/manrope/manrope-latin-wght-normal.woff2` | Copy the already approved local font bytes from the lab package/output; no network acquisition or replacement of current fonts. |
| `src/static/assets/fonts/manrope/OFL.txt` | Retain the Manrope OFL license alongside the font. |
| `src/apps/crm/test_services_dashboard_ui.py` | New server-level coverage for asset/vertical/role scope, unchanged data and route contracts, timezone/currency presentation, and unchanged responses on representative other pages. Data-writing fixtures require future disposable-test authorization. |
| `scripts/services_dashboard_ui_browser_check.py` | Real-Django Chromium evidence using existing StaticLiveServer/Playwright patterns and authorized disposable fixtures; screenshots, interaction/axe/network/focus checks and before/after comparisons. Reuse existing fixture/browser helpers where suitable; no second preview server/application. |
| `docs/design/motionmate-ui-lab/07-services-dashboard-integration.md` | Future implementation evidence, actual file scope, visual variances, test outcomes, unresolved issues and release/rollback handoff. Not created by this audit. |

No new root package/lock, npm build, settings change or Node process is proposed
for B. Serve the new CSS/JS directly through Django staticfiles; WhiteNoise can
compress/hash them during the existing authorized collection step. A later
requirement for compiled Tailwind/DaisyUI would reopen the build manifest and
approval decision rather than reuse the lab build as a production dependency.

### Files and systems to keep untouched

- All `src/apps/logistics/` and `src/templates/logistics/` files and Logistics
  static assets, including dashboard snapshots, pending checkout and staff/site
  financial visibility; all other Services screen templates and behavior.
- Shared navigation include, onboarding includes/definitions/JS, branding
  include/logo, booking-share include, invoice status/finance includes, finance
  projections/services and payment/booking/appointment writers. Their existing
  markup/behavior remains authoritative; styling their rendered output must be
  scoped to the new dashboard marker.
- `theme.css`, `theme.min.css`, RTL theme files, all `user*.css`, `config.js`,
  `phoenix.js`, Bootstrap/vendor assets, `crm-dashboard.js`, Silicon assets and
  `design_references/phoenix/`.
- Models, migrations, URLs, context processors, capability/permission/subscription
  policies, environment/configuration, `src/taskio/settings.py`, `build.sh`,
  `Procfile`, Python dependencies/locks and PWA code/cache policy.
- Existing Step 1–5 documentation, lab prototypes/compiled outputs/evidence,
  design-system sources, AGENTS.md and the UI skill. Production must not import
  `/ui-lab/` paths or lab-generated HTML/JS.
- `src/staticfiles/` is collected output, not an editing target. No database,
  stored enum, record, role, plan, staff grant or provider configuration changes.

### Shared dependencies requiring special approval

The parent has 60 direct consumers. Its new hooks, page marker and conditional
accessible names must preserve the default rendered DOM/attributes, original
asset order, navigation, alerts and Logistics site selector. Asset emission must
require the server marker and existing Services response, not a query parameter.
No consumer other than this dashboard may receive the new stylesheet, script,
font request or page class. Approval of this exception is narrower than approval
to redesign the shared shell.

## 5. Known risks, boundaries and mitigation

| Risk/finding | Evidence and treatment |
| --- | --- |
| Global Phoenix overrides | [user.css](../../../src/static/assets/css/user.css) lines 117 onward sets literal light `.content`, `.content .card`, headers, tables/list dividers and form boundaries; important light `bg-body-tertiary` and dark `bg-light/bg-white` rules also exist. Matching relevant overrides are present in the loaded `user.min.css` and RTL counterparts. Use new panel classes without legacy `.card`/conflicting background utilities where possible; explicitly test specificity where reusing an existing include. Do not “fix” these global rules. |
| Tailwind/DaisyUI collisions | The current lab CSS has global reset/theme rules and generic `.btn`, `.modal`, `.menu`, `.card`, `.input` names. CSS layers/prefixes or DaisyUI's configured root alone do not isolate the existing output from Phoenix. B loads none of that distribution. A needs a separately validated isolation design. |
| Theme ownership | Read `html[data-bs-theme]` for scoped colors and preserve Phoenix control/config/storage behavior. No lab theme key, theme query switcher or second account/menu adapter in production. Verify light/dark/auto and RTL initialization. |
| Modal/dropdown dependencies | Real setup relies on Bootstrap Modal/Offcanvas APIs, events and persisted POSTs; account/navigation also use Bootstrap. Keep the current runtime and markup. Preserve the guide's static/Escape policy and spotlight z-index/scroll behavior. Do not add a native-dialog replacement or second backdrop/focus owner. |
| Mobile search defect | `dashboard_parent.html` links Services mobile search to `#searchBoxModal`; there is no active matching modal in this inheritance path. Similar triggers in `account_parent.html` and a commented customer-view modal do not supply it. Step 1 recorded the browser failure; Step 6 confirms the unresolved source, not a new runtime reproduction. Recommend omitting this unsupported item only on the Services dashboard via the proposed block, with explicit approval. Do not invent global search or repair other pages in this increment. |
| Existing shell accessibility | Mobile brand text is hidden while the logo image has empty alt; theme labels are icon treatments with 32px inline dimensions. Earlier audit recorded naming/focus issues. Propose dashboard-only accessible names and scoped minimum 44px targets/focus, using the server marker; do not silently repair every page. Re-test the whole dashboard and report remaining baseline issues rather than claiming framework conformance. |
| Timezone presentation | `_business_local_periods()` already resolves Business-local count boundaries, with its existing fallback. Record timestamps still use plain date filters; settings default to UTC and no Business-timezone activation is established in this request path. Propose the already-resolved timezone object in the Services context and a bounded Django `{% timezone dashboard_timezone %}` block for record displays/header. Use date-sensitive offsets per record, retain stored instants and queries. No middleware/global activation, new preference or scheduling change. This is an approved-scope decision, not an automatic cosmetic fix. |
| Finance and EUR/USD | `present_invoice()` uses settlement currency and a copied `billing_business`; render row balances with that object's money filter and explicit `financial.currency`. Preserve invoice status vs receipt/payment indicators. Workspace summaries use only the workspace-currency bucket, while open-invoice counts span currency buckets. Label those scopes; never convert/sum currencies or call issued value cash revenue. |
| Hidden finance region | `finance_totals.html` is inside an HTML comment in the current dashboard. Django still renders its values into the response, though the table is not visually displayed. Retain the current commented treatment by default; do not uncomment it, create a new review workflow, or silently convert it into a Django comment/remove it. The vocabulary document describes currency/review presentation more broadly than the visible dashboard currently provides. Exposing it is a separate content decision. |
| Request entitlement ambiguity | The dashboard's request queue lacks its own request-module guard, unlike the unified destination. Record/test existing behavior; any policy correction is a separate functional/authorization change. A fixture flag cannot resolve the policy. |
| Clipboard feedback | Current copy has no success/denial message. Proposed dashboard-local controls may provide confirmed success and selectable-URL fallback, preserving URL/path/escaping and open attributes. Do not bind an additional writer on top of the existing inline handler; leave the shared include unchanged. Approve this interaction refinement explicitly. |
| Real-data size and states | Full names, service/title snapshots, missing preferred times, large localized amounts, empty/locked data, alerts and dynamic journeys differ from the canonical fixture. Grow rows, preserve all fields, and test at 320/390/768/1440px. No fake async loading, refresh API, chart or fabricated zero. |
| Static/deployment pipeline | [build.sh](../../../build.sh) runs `uv sync --locked` and `collectstatic`, not npm/Gulp. [settings](../../../src/taskio/settings.py) select `CompressedManifestStaticFilesStorage` for non-debug/non-test serving. New CSS must reference the font through a relative static URL that manifest post-processing resolves. Verify collected hashed assets and font/license paths in a separately authorized environment; never edit collected files or build reference assets. |
| Release hook | [Procfile](../../../Procfile) has `release: python src/manage.py migrate`. A UI-only change does not disable that hook or prove no migrations are pending in a deployed DB. Deployment/release-hook execution requires separate authorization and a runtime-specific migration review; do not alter Procfile or run the hook in this audit. |
| PWA | [PWA server policy](../../../src/taskio/pwa.py) and [worker](../../../src/templates/pwa/service-worker.js) cache only the explicit public shell resources. Other static assets retain normal hashed caching; operational responses are not cached. No PWA asset-list/cache-policy change is required for new dashboard static files. Verify online/update/offline behavior later without adding authenticated HTML/data to caches. |

Visual integration covers composition, type, density, colors, responsive rows
and action placement. Search omission, local-time correction, scoped shell
accessibility and copy feedback are explicit related repairs requiring approval.
Global styling cleanup, asset pruning, request-policy correction, multi-currency
table exposure, a shared brand change and framework migration are separate work.

## 6. Implementation phases — future, authorization required

1. **Approve the boundary.** Choose B's visual translation versus actual framework
   adoption; approve the manifest/shared-parent exception and each related repair.
   Accept retained Phoenix chrome/dialog differences. Resolve finance visibility
   scope and language/browser requirements. No production edits before this gate.
2. **Establish a disposable baseline.** Identify settings, sanitized host/port/DB
   identity and an explicitly disposable test cluster; authorize fixtures/tests.
   Record current Services/Logistics/unchanged-page responses/screenshots, asset
   requests, permissions and query results. Protect all unrelated working-tree
   edits and Step 4 reference files. Existing failing tests remain separately
   classified; do not silently revise expectations to obtain a green run.
3. **Add the bounded binding.** Add default-preserving parent hooks and server
   presentation context. Create the new Services partial/assets/font with no
   query, financial, booking or navigation logic changes. Retain Logistics output
   and all real setup forms. Build no new framework pipeline.
4. **Apply approved refinements.** Compose work regions first; retain all metric
   subjects/periods, route intents and status projections. Add local disclosure/
   copy behavior and only the separately approved timezone/search/a11y hunks.
5. **Validate and review the integrated result.** Run the plan below, compare with
   Step 4 for approved content treatment and with the actual pre-change app for
   contracts/unchanged pages. Record visual variances and unresolved failures in
   the proposed Step 7 report. Stop for implementation review.
6. **Release approval.** Present actual results, collected-asset verification,
   migration-hook implications and rollback material. Commit, push, provider
   actions, staging/production writes and deployment each remain separately
   controlled actions; none is authorized by the design or this audit.

## 7. Validation and rollback plan

### Existing coverage to reuse

These sources were inspected, **not executed in Step 6**:

| Coverage | Existing tests/tooling and practical limit |
| --- | --- |
| Tenant metrics, roles, modules and empty data | `apps.crm.tests.CRMBusinessScopingTests`, especially `test_agent_dashboard_scopes_metrics_to_current_business`, appointment allowed/blocked cases, staff/accountant billing cases, sharing readiness and empty dashboard. These assert actual query/context behavior. Some heading assertions will need the narrowly approved updates. |
| Real setup state and navigation | `apps.crm.tests.DashboardOnboardingViewTests`; `apps.businesses.tests.OnboardingStatusHelperTests` and `OnboardingVisibilityTests`. Cover owner/admin, non-owner visibility, hidden fields, journey operations/returns and actual navigation guards. |
| Subscription modes and isolation | `apps.businesses.tests.SubscriptionEffectiveAccessPolicyTests`, `CurrentBusinessTests`, focused dashboard/grace/restricted cases in `BusinessSubscriptionViewTests`, plus `apps.businesses.test_capabilities.VerticalAccessTests`. Do not run unrelated seed/purge/migration suites for a UI change. |
| Requests/appointments | `apps.appointments.test_workspace.UnifiedWorkspaceTests`; `apps.crm.tests.PublicBookingTests`. These protect eligible unlinked Leads, historical counts, entitlement distinctions, bookings and existing destination workflows. |
| Invoice/currency semantics | `apps.billings.test_presentation.InvoicePresentationTests`, relevant `CustomerPaymentTests`, and `apps.businesses.tests.BusinessModelTests.test_money_formatting_uses_business_currency_locale_and_country`. Current tests cover retained receipt currency after Business defaults change, partial balances, review exclusion and Services dashboard totals. |
| Logistics protection | `apps.logistics.test_financial_access.LogisticsFinancialAccessTests`, especially STAFF's scoped reads without dashboard summaries; `LocationAccessTests` and focused dashboard/subscription cases in `test_local_billing_bypass`. Retain the Logistics pending/restricted responses and work-site gates. |
| Actual browser/PDF surfaces | `scripts.invoice_terminology_browser_check` already visits the Services dashboard and other Services/Logistics screens, including a Business currency change to EUR with saved USD receipts. `scripts.unified_appointments_browser_check`, `scripts.draft_client_browser_check`, Logistics financial/location browser checks and `scripts.pwa_browser_check` provide existing workflow patterns. They create records/submit forms: authorization and disposable settings are prerequisites. |
| Lab reference | Existing Step 4 evidence and Step 5 capture/axe tooling provide visual conventions and screenshot metadata. Static lab passes do not validate Django, current runtime or providers; do not execute a reference validator that overwrites approved evidence as part of this audit. |

Use `taskio.services_test_settings` only against an identified, approved
disposable localhost PostgreSQL cluster. It replaces database configuration,
rejects port 5432, uses test database `test_services_rollout`, local-memory
email/cache and a test-only hasher. A nonstandard port alone is not proof the
target is disposable. Do not reuse the ordinary DB or infer authorization from
the existence of a script. Review provider mocks/network boundaries first.

An example **future** focused command, after the test environment and implementation
have been authorized, is:

```sh
SERVICES_TEST_PG_PORT="$APPROVED_TEST_PG_PORT" .venv/bin/python src/manage.py test \
  apps.crm.tests.CRMBusinessScopingTests \
  apps.crm.tests.DashboardOnboardingViewTests \
  apps.appointments.test_workspace \
  apps.billings.test_presentation.InvoicePresentationTests \
  apps.businesses.tests.SubscriptionEffectiveAccessPolicyTests \
  apps.businesses.tests.CurrentBusinessTests \
  apps.crm.test_services_dashboard_ui \
  --settings=taskio.services_test_settings --noinput
```

The last module is proposed, not present yet. Additional existing suites/browser
cases in the table run only as required by the authorized change, with the same
disposable boundary. No setup, test or migration commands ran in this audit.

### Required acceptance matrix

| Area | Required assertions/evidence |
| --- | --- |
| Actual data/queries | Compare pre/post context values, tenant ownership, IDs/order, five-row caps, counts/periods and relevant query behavior. No new domain writes on dashboard GET and no new queries for per-row permission/financial calculations. Preserve no-JS navigation/full-record access. |
| Roles | Owner/admin/staff/accountant/viewer: allowed reads, correct setup/settings/empty links, no added creation/payment controls. Anonymous, inactive/missing membership and foreign-tenant attempts preserve current denials/resolution. Browser hiding is not the authorization test. |
| Subscription/entitlements | Full/trial/grace/restricted/blocked/pending/no-subscription, independent appointment/invoicing/public-booking locks, request-only versus appointment-only destinations. Check actual redirect/403/200 behavior, owner recovery forms and neutral non-owner alerts. Preserve the current request-queue policy pending a separate decision. |
| Appointments/bookings | Today with past and future scheduled records; zero today with future records; today count positive with empty future preview; preferred/undated requests; linked/inactive/closed/Interest exclusions; ordering and more-than-five cases. Existing detail/list/follow-up/settings links must resolve and retain query values. Existing creation/draft/confirmation writers remain unchanged. |
| Local time | Fixed UTC instants near Business midnight/month boundary; `America/Lower_Princes`, `Europe/Amsterdam` in winter/summer and repeated DST times; existing unknown-zone fallback. Assert local date/time and date-sensitive offsets, unchanged instants/count query boundaries and no timezone leakage to other requests, Logistics or other Services pages. |
| EUR/USD/finance | USD/en-SX `$1,234.56` and EUR/nl-NL `€1.234,56` using the real formatter; explicit codes where needed. Saved USD receipts after Business default changes to EUR, simultaneous USD/EUR invoices, no workspace-currency bucket, large amounts, partial payments, legacy PAID review, draft/cancelled/zero obligations, credits/refunds and concurrent debt/refund indicators. No FX, cash-revenue relabel or UI settlement calculation. Retain authoritative review exclusions and the commented finance table unless separately approved. |
| Browser/layout | Real Django-rendered populated, empty, long and relevant restricted states at 1440×900, 768×1024, 390×844 in light/dark; additional 320px and 200% native zoom where available. Measure overflow, record readability, target sizes, work hierarchy and sidebar-collapse states at actual Phoenix breakpoints. Record screenshot viewport/DPR/theme/clock/browser/loaded font. Compare approved content treatment, not incompatible whole-shell pixel coordinates. |
| Interactions | Real route navigation; local expand/collapse; theme/auto change with focus and disclosure state retained; account/nav Bootstrap behavior; clipboard exact URL, success/denial/manual fallback; actual dynamic welcome→journey→guide/back/skip/start/continue flows with CSRF and persisted return state in disposable fixtures. Normal and reduced motion. No simulated route modal or intercepted setup POST. |
| Accessibility | Axe plus raw incompletes, one page h1/named region, labels/status announcements, text/control/focus contrast, 44px targets, Tab/Shift+Tab/Enter/Escape, focus containment/return and sticky-header obstruction. Preserve static guide behavior. Test screen readers and supported engines/devices before claiming conformance. Separate pre-existing untouched findings from new failures; do not report a whole-page AA pass on partial evidence. |
| Asset/network/theme | New local CSS/JS/font only on this Services response; Manrope loaded/fallback legible, licenses retained, zero unanticipated JS errors or failed required local assets, one Bootstrap runtime and no Tailwind/DaisyUI/lab asset leakage. Block live providers; account separately for deliberately blocked existing CDN resources and use consistent before/after font/network conditions. Do not count blocked provider traffic as provider verification. |
| Unchanged Services/Phoenix | Before/after screenshot/DOM/asset comparisons for Appointments, Clients, invoice list/detail/payment page, Business Settings, service list/import entry and relevant public booking/public site entry. Assert no new page marker, CSS, script, font request, style/storage change or navigation/role difference. Default hook output must preserve existing structure. |
| Logistics | Operational dashboard for accounting roles and STAFF, assigned/unassigned/read-only sites, restricted/pending checkout, parcel list/detail/registration, shipments and financial surfaces. Assert no Services assets/marker, no business-wide STAFF financial exposure, unchanged menu order/guards/site selector, and unchanged write/clearance behavior. Run real server authorization coverage as well as representative browser comparisons. |
| Collection/PWA/release | In a separately authorized disposable/static staging environment, resolve `{% static %}` through the production manifest, fetch collected CSS/JS/font with correct MIME/compression/hash rewrites, verify direction and fresh/cached navigation, and confirm no private HTML/financial data enters PWA caches. No production collection or release-hook execution under test authorization alone. |

Before release, establish the supported browser/language policy. Prior lab
evidence is Chromium-only and Latin Manrope only; this audit adds no browser,
screen-reader, native-zoom, runtime/database or provider verification. Historical
reports mention unrelated import/demo/browser failures; baseline them rather
than treating old green counts or old failures as current results.

### Rollback

Keep the pre-change templates/context and static artifact manifest available as
one rollback unit. Restore the old dashboard entry and parent hooks/attributes,
remove only the new Services asset references and presentation keys, and revert
the associated tests/documented expectations. New unused font/CSS/JS artifacts
can remain available during cache expiry; do not delete hashed assets still
referenced by active pages or old releases.

No schema/data rollback, migration reversal, record reset or provider action is
needed for this proposed UI increment. Preserve any legitimate operational data
and setup POSTs created while it was in use. Confirm the old dashboard and
unchanged Services/Logistics asset graphs after rollback. Actual rollback
deployment still requires explicit authorization and consideration of the
existing release migration hook; never execute a deploy/reset automatically.

## 8. Decisions requiring explicit approval

1. **Strategy/fidelity:** B's approved visual translation in Phoenix, without
   production Tailwind/DaisyUI packages, retaining real navigation geometry,
   shell font/wordmark and Bootstrap setup dialogs. If exact shell/package
   adoption is required, re-scope A before implementation.
2. **File/shared boundary:** approve the exact proposed manifest, including the
   default-preserving parent hooks, Services-only body marker and accessible
   names. No other Services/Logistics redesign or global CSS cleanup follows.
3. **Timezone:** approve dashboard-only local-time presentation/context and
   explicit zone/offset labels, with unchanged instants/queries/scheduling.
4. **Related repairs:** approve dashboard-only removal of unsupported mobile
   search, scoped naming/focus/44px controls and confirmed copy/denial feedback.
   These are recorded changes from production behavior, not silently bundled fixes.
5. **Finance/request policy:** keep supplied financial calculations, scoped
   currency labels and the current commented table; leave request entitlement
   policy unchanged. Any table exposure or authorization correction needs a
   separate functional scope and tests.
6. **Validation resources:** authorize an identified disposable test environment
   and fixture-writing/browser checks; settle supported engines, accessibility
   review and Manrope language coverage. Ordinary runtime/provider writes are
   not covered by that authorization.
7. **Implementation/release:** issue explicit implementation authorization after
   reviewing this audit and the decisions above. Commit, push, migrations,
   deployment and release-hook execution remain separate later approvals.

## Audit evidence and stopping point

Inspected the current checked-out source, template consumers, relevant loaded
asset files, approved design-system/prototype sources, static/PWA/release paths
and existing test/browser code. This is source inspection and planning, not a
fresh runtime/browser test result. Earlier screenshot/test reports are reference
evidence only. No application, migration, collection or data-writing command ran.

The pre-existing modified AGENTS.md, untracked design/lab tree and local ignored
UI skill were preserved. Existing-file hashes were recorded before inspection;
the completion check excludes only this new report and verifies the same
**13,828 existing files**. Document links, whitespace and working-tree scope are
checked separately. There are no additional audit artifacts or production edits.

**Stop after this audit. Wait for explicit implementation authorization.**
