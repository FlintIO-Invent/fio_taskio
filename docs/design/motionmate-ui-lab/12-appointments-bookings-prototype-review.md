# Motionmate Services — Appointments & Bookings prototype review

**16 November 2026 · Step 3 · UI Lab only · Ready for visual review**

Extended the existing Appointments lab into one connected prototype with five screen compositions. It uses the approved Manrope, Motionmate tokens and shared lab components, with synthetic browser-memory records and no Django or application database connection. The [Step 2 brief](11-appointments-bookings-design-brief.md) is the design specification; the [Step 1 audit](10-appointments-bookings-audit.md) supplies the existing implementation/workflow contract.

The approved Services dashboard, shared design-system files, application code, Logistics, dependencies and deployment environments were preserved. This review is design evidence, not a production implementation or real Django BEFORE/AFTER review.

## 1. Open the prototype

The existing read-only UI Lab server is running on loopback port **8765**:

- [Open Appointments](http://127.0.0.1:8765/services-appointments/dist/?view=workspace&theme=light)
- [Open the screenshot gallery](http://127.0.0.1:8765/services-appointments/evidence/step3/gallery.html)

To launch it again from the repository root, when the port is free:

```sh
.venv/bin/python -B ui-lab/services-dashboard/tools/serve.py --root ui-lab --port 8765
```

Keep `--root ui-lab`; the historical default serves the dashboard subtree. Use another free port if needed rather than taking over an existing listener. The preview requires JavaScript; its `noscript` message points to static evidence. No installation, Django startup, login or database setup is required. A fresh checkout may need the lab-only build using already installed pinned tools:

```sh
node ui-lab/tools/build.mjs services-appointments
```

Open **Interactive prototype** above the product frame to choose a screen/scenario and read proposal notes. These reviewer controls are outside the product flow. Theme switching preserves the local draft. Navigation within the prototype retains drafts and local changes; changing scenarios or reloading resets them. Only the existing lab theme preference persists.

## 2. Structure and changed files

All implementation writes are under `ui-lab/services-appointments/`, plus this report.

| File | Role |
| --- | --- |
| [src/app.js](../../../ui-lab/services-appointments/src/app.js) | Connected local navigation, history/return paths, drafts, synthetic submissions, filters/page state, validation and feedback. |
| [src/journey.js](../../../ui-lab/services-appointments/src/journey.js) — new | Detail, appointment form, public wizard/outcomes, request/completion compositions and preview dialogs. |
| [src/input.css](../../../ui-lab/services-appointments/src/input.css) | Added responsive layouts, form/error/slot states, related-action disclosure and public composition, using existing semantic tokens. |
| [src/fixtures.js](../../../ui-lab/services-appointments/src/fixtures.js) | Existing records/filter options retained; the shared Client 501 request classification was aligned with its supplied Active Client appointment context. No real Client was changed. |
| [README.md](../../../ui-lab/services-appointments/README.md) | Launch/build/scenario instructions, contracts, validation and review boundary. |
| [validate_step3.py](../../../ui-lab/services-appointments/validate_step3.py) — new | Core responsive/theme matrix and connected task checks using the existing static server. |
| [validate_states_step3.py](../../../ui-lab/services-appointments/validate_states_step3.py) — new | Dialog, slot selection, public review/outcome and error-state captures, keyboard and axe checks. |
| [supplement_contrast.py](../../../ui-lab/services-appointments/supplement_contrast.py) — new | Computed-color supplement for retained native-dialog contrast incompletes. |
| [review_evidence.py](../../../ui-lab/services-appointments/review_evidence.py) — new | Gallery/summary, final source hashes and protected-file comparison. |
| `dist/`, `build-meta.json`, `evidence/step3/` | Generated local build/assets/licenses and new review evidence. No earlier evidence directory was regenerated. |

The existing workspace renderer, isolated HTML/CSP, shared tokens/components and pinned build/server tools were reused. No UI Lab rebuild, registry replacement, new framework or dependency installation was needed. The legacy list-only `check.py` is retained as historical Step 5 tooling; its route-intent assumptions are not the connected Step 3 validation.

## 3. Five compositions and their navigation

| Composition | Open directly | Connected behavior |
| --- | --- | --- |
| Appointments workspace | [Workspace](http://127.0.0.1:8765/services-appointments/dist/?view=workspace) | Scheduled/terminal appointment rows and Needs follow-up; search, state, More filters, explicit apply/reset, 50-row pagination and responsive records. View/Edit, New Appointment and Create Request open the corresponding local composition. |
| Appointment details | [Details](http://127.0.0.1:8765/services-appointments/dist/?view=detail&id=801) | Client/service/staff, date range/zone, notes, related actions, edit and invoice destination. Scheduled records offer terminal-action previews; terminal records retain their status on edit. |
| Create/edit appointment | [New appointment](http://127.0.0.1:8765/services-appointments/dist/?view=form) | Full-page create/edit/from-request modes, native selectors, inline Client dialog, requirements/time-order errors, retained draft and pending/success feedback. Local save returns to details; Back preserves workspace filters. |
| Public booking and confirmation | [Public booking](http://127.0.0.1:8765/services-appointments/dist/?view=public) | Service/intent → Availability → Contact → Location & review. Both intents, keyboard-selected slots, Company/Individual, review/edit and truthful outcome variants. Staff navigation is hidden. |
| Request follow-up | [Missing Client details](http://127.0.0.1:8765/services-appointments/dist/?view=request&id=703) | Request state, contact/context, Client completion, saved-Client explanation and scheduling handoff. Ready requests open the shared appointment form. The D4 direct-resume candidate is explicitly exposed in reviewer controls. |

Create/edit request and Client completion are subviews of the follow-up composition; outcome is a subview of public booking. They are not separate apps. Client, invoice, dashboard, history, settings and contact actions outside these compositions are intercepted as destination previews. No invoice is created, email sent, call started or real status updated.

### Booking-to-Appointments representation

- **New Appointment:** a local Scheduled row, then local Appointment Details.
- **Create Request:** an unscheduled local follow-up, without another appointment.
- **Public Book now:** a local Scheduled row with source-request context; its linked request is not a second operational row.
- **Public Contact before booking:** an unscheduled local Needs follow-up row.
- **Request scheduling:** the local appointment becomes the operational row and the source request remains linked context. No invented manual-confirmation stage is added.

These are synthetic outcome projections. They illustrate the existing workflow distinction and proposed presentation, not a replacement booking service or proof of authoritative POST, locking, capacity, matching or retry behavior.

## 4. Scenarios and synthetic data

Use `scenario` for review states; `state` retains its existing filter meaning. Add `theme=light|dark` and `view=workspace|detail|form|public|request` as needed.

| Scenario group | Examples |
| --- | --- |
| Work lists | `populated`, `long`, `empty`, `pagination` (50 + 2), `invalid`, `loading`, `error`. |
| Roles/access | `admin`, `staff`, `accountant`, `viewer`, `read-only`, `request-only`, `appointments-only`, `locked`. These are explicit supplied access projections, not a browser authorization evaluator. |
| Public feedback | `no-slots`, `conflict`, `uncertain`. Conflict and uncertainty are forced examples, not computed/live provider responses. |
| Detail/form contexts | `id=801` Scheduled/linked request; `id=802` Completed/linked invoice; `id=803` Cancelled/unassigned; `mode=edit|from-request`; `view=completion&id=703`. |
| Public outcomes | `view=outcome&result=scheduled` or `result=request` are explicit synthetic outcome fixtures. Query values must never become trusted application receipt/context logic. |

The inherited fixed clock is **14 November 2026, 09:00 UTC**. Workspace examples use **America/Lower_Princes, UTC−04:00**; public choices use 16–18 November. Dates are historical synthetic fixtures, not live availability or “today”. Names, companies, addresses and `example.test` contact values are synthetic. No customer data was copied.

The prototype retains all nine workspace information subjects, six filters, `status` bookmark compatibility, source/classification unknowns and independent row entitlements. It does not infer request assignment from staff preference or apply Logistics financial restrictions to Services. Existing catalog and availability policy is not reimplemented; fixed supplied options illustrate selection only.

## 5. Responsive and theme validation

Final checks used existing cached **Chromium 148.0.7778.96**, the project's installed Playwright and existing axe-core. Playwright's default matching browser was absent, so `PWA_CHROMIUM` selected an already installed cache binary; no browser/package download occurred.

| Check | Result |
| --- | --- |
| Core compositions: five × 1440/768/390/320px × light/dark | **40/40 passed**. |
| Empty/long/invalid/locked/loading/error/no-slots/public-read-only/completion-context/outcome states, 390px, both themes | **22/22 passed**. |
| Connected tasks at 1440 light, 768 dark, 390 light, 320 dark | **166/166 assertions passed**. |
| Supplemental dialog/wizard/review/success/error states at 1440 light and 390 dark | **14/14 states**, plus **14/14 assertions passed**. |
| Document overflow, visible target sizes, one page heading | Passed for the captured cases. Checkbox/radio targets are measured through their clickable wrapping labels. |
| Browser errors / failed requests in final runs | None recorded. Requests remained loopback GETs. |
| Axe WCAG-tag violations | **0** across the 76 captured cases; see retained incompletes below. |
| Protected existing files | **13,689 unchanged**; no changed/missing protected file. |
| New Python validator lint; diff whitespace | Passed. |

Evidence: [summary](../../../ui-lab/services-appointments/evidence/step3/summary.json), [matrix/task results](../../../ui-lab/services-appointments/evidence/step3/validation.json), [supplemental states](../../../ui-lab/services-appointments/evidence/step3/states.json), [protected baseline](../../../ui-lab/services-appointments/evidence/step3/protected-before.json). The summary includes final source/build hashes. The approved dashboard and other protected evidence were compared as files; no new dashboard/Logistics runtime regression is claimed.

Task checks cover search, creation, errors, Client modal, theme/back draft preservation, terminal dialogs, editing without reopening, keyboard slot selection, both intents, local booking-to-workspace outcomes, Client completion/resume identity, related-action disclosure, invoice interception, request creation, read-only/independent entitlements, pagination and mobile navigation focus return.

Initial exploratory failures were corrected: the validator's string predicates conflicted with CSP, and the status dialog referenced an unqualified timezone variable. The CSP was retained; function predicates and the dialog reference were corrected. [Initial task-failure evidence](../../../ui-lab/services-appointments/evidence/step3/initial-task-failures.json) remains separate from the final passing results. Early diagnostic PNGs outside the gallery are not final review captures.

## 6. Accessibility observations

Verified in the local prototype: persistent labels and requirements, one page `h1`, named steps, native controls, textual status, associated error summaries, 44px controls/label targets, visible focus, dialog containment/Escape/return, related-action disclosure keyboard handling and slot `aria-pressed` state with preserved focus. The 320px review retained content without horizontal document scrolling. Themes retain the entered draft; captures used reduced motion, with scoped reduced-motion CSS retained.

**Axe left two terminal-dialog cases contrast-incomplete:** two text nodes at 1440 light and one at 390 dark. They remain in the raw results; zero violations does not convert these to automated passes. A [computed-style supplement](../../../ui-lab/services-appointments/evidence/step3/contrast-supplement.json) checks the text colors against the opaque dialog surface and records 15.92:1 in light and 15.38:1 in dark; it supports targeted review, not full accessibility conformance.

Firefox/WebKit, screen readers, real devices, native browser zoom, RTL and exhaustive normal-motion tasks were not tested. Synthetic native-dialog and responsive table/card evidence does not certify assistive-technology behavior in Django/Phoenix. The application public-booking fallback remains a separate decision; the prototype's JavaScript requirement is not a fixed production fallback.

## 7. Screenshots and gallery

The [gallery](../../../ui-lab/services-appointments/evidence/step3/gallery.html) contains **152 PNGs**: viewport/full-page pairs for 62 matrix cases and 14 supplemental states. Click a thumbnail for the full page.

| Example | Screenshot |
| --- | --- |
| Desktop workspace, light | [1440px](../../../ui-lab/services-appointments/evidence/step3/screenshots/workspace-1440-light-viewport.png) |
| Mobile workspace, dark | [390px](../../../ui-lab/services-appointments/evidence/step3/screenshots/workspace-390-dark-full.png) |
| Appointment details, tablet | [768px](../../../ui-lab/services-appointments/evidence/step3/screenshots/detail-768-light-full.png) |
| Create form, narrow mobile | [320px](../../../ui-lab/services-appointments/evidence/step3/screenshots/form-320-dark-full.png) |
| Selected public availability | [390px dark](../../../ui-lab/services-appointments/evidence/step3/screenshots/availability-selected-390-dark-full.png) |
| Public review | [390px dark](../../../ui-lab/services-appointments/evidence/step3/screenshots/public-review-390-dark-full.png) |
| Missing Client context | [390px light](../../../ui-lab/services-appointments/evidence/step3/screenshots/client-completion-390-light-full.png) |
| Terminal-action dialog | [1440px light](../../../ui-lab/services-appointments/evidence/step3/screenshots/terminal-dialog-1440-light-viewport.png) |

Screenshots supplement the interactive prototype. They are not current Django screens or production BEFORE/AFTER evidence. Existing approved dashboard images/distributions were not regenerated.

## 8. Simulation differences and pending decisions

| Brief item | Demonstrated concept | Separate decision still required |
| --- | --- | --- |
| D1 notifications | No real or simulated email-delivery claim. | Cancellation/reschedule notification triggers, recipient/retry/failure policy. |
| D2 terminal actions | Local confirmation dialogs and synthetic terminal states; edit does not reopen. | Production confirmation integration and any reopening/status-policy change. |
| D3 scheduling rules | Fixed supplied service durations/slots and forced conflict example. | Booking buffers, effective confirmation settings and internal conflict/override policy. No new rule was enforced. |
| D4 Client/request handoff | Saved Client is distinct from appointment; reviewer controls offer direct scheduling resume with the completed Client selected. | Current application redirect/GET synchronization and durable `source_lead` preservation changes. |
| D5 wizard/fallback | Four steps, local review, keyboard focus and cleared hidden slot values on switching to contact intent. | Server stale-value/readiness validation, fallback, uncertain-result recovery and any step skipping. |
| D6 outcomes | Separate Scheduled and Request received screens driven by synthetic local outcomes. | Trusted server outcome context through redirects/retries/expiry; no real receipt or application rendering added. |
| D7 finance/destinations | Existing invoice/Client destination intents only. | Restoring hidden shortcuts or changing staff notification targets. No invoice/payment automation. |
| D8 queries/returns | Current filters/page size and local back-context retention. | Production return parameters, date views, ordering/search/performance changes. |
| D9 internal Client/forms | Current required Client fields, native selectors and explicit start/end/title. | Internal Individual parity, enhanced selectors or service-driven defaults. |

This is not an authoritative availability, CRM matching or financial engine. It does not implement full legacy/history/interest workflows, live currency/default changes, DST repeated-hour scenarios, authentication/CSRF, concurrency, capacity, provider integrations or ordinary-runtime stability. Known classifications and access are supplied examples; real queries and writers remain in Django.

## 9. Reproduce the checks

With the existing tools and an already installed compatible Chromium, from the repository root:

```sh
node ui-lab/tools/build.mjs services-appointments
export PWA_CHROMIUM=/path/to/already-installed/chrome
.venv/bin/python -B ui-lab/services-appointments/validate_step3.py
.venv/bin/python -B ui-lab/services-appointments/validate_states_step3.py
.venv/bin/python -B ui-lab/services-appointments/supplement_contrast.py
.venv/bin/python -B ui-lab/services-appointments/review_evidence.py
```

The observed browser was `/home/mzero/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome`. The override is process-local; use the appropriate existing path on another machine. Default Playwright selection can be used when its matching browser is already installed. Missing tools are a limitation, not permission to install dependencies.

These validators use the existing static server on ephemeral loopback ports, block other destinations/write requests and write only this package's evidence. They never run Django or contact application databases. Repeated checks replace current Step 3 evidence; the protected baseline and final hashes identify what was reviewed. No ordinary runtime/provider validation follows from their pass.

## 10. Human review and stop point

Review the five-screen hierarchy, record density, tablet/mobile action placement, form requirements, public step/review flow, outcome wording and Client-completion handoff. In particular, review D2/D4/D5/D6 as proposed concepts rather than approved backend behavior. The two axe-incomplete dialog states also need visual/accessibility review.

Accepting the visual design may leave functional decisions open. A later production proposal must identify Services templates/assets, data/context dependencies and checks, retain Phoenix, protect Logistics/dashboard, and use the authorized real Django BEFORE/AFTER methodology. Prototype approval does not authorize that implementation, framework migration, database/schema work or release.

**Stop after Step 3.** The static prototype remains available for review. No application code, application database, Logistics, approved dashboard, dependency, migration, commit, push, merge or deployment was changed or run.
