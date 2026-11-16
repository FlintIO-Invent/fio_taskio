# Services Appointments & Bookings — connected prototype

Step 3 UI Lab only, based on the [audit](../../docs/design/motionmate-ui-lab/10-appointments-bookings-audit.md) and [design brief](../../docs/design/motionmate-ui-lab/11-appointments-bookings-design-brief.md). This extends the existing Step 5 Appointments composition into one connected review. Phoenix and Django application sources, the approved dashboard and shared design-system files are unchanged.

Synthetic records and browser-memory state only. Reload resets demo changes and drafts. The only persistent preference is the existing lab-only theme setting. No database, real record, email, invoice, account or provider is accessed. UI outcome/confirmation concepts do not establish application behavior or authorize backend changes.

## Launch

From the repository root, with the existing environment:

```sh
.venv/bin/python -B ui-lab/services-dashboard/tools/serve.py --root ui-lab --port 8765
```

- [Workspace](http://127.0.0.1:8765/services-appointments/dist/?view=workspace&theme=light)
- [Appointment details](http://127.0.0.1:8765/services-appointments/dist/?view=detail&id=801&theme=light)
- [Create appointment](http://127.0.0.1:8765/services-appointments/dist/?view=form&theme=light)
- [Public booking](http://127.0.0.1:8765/services-appointments/dist/?view=public&theme=light)
- [Request follow-up](http://127.0.0.1:8765/services-appointments/dist/?view=request&id=703&theme=light)
- [Review gallery](http://127.0.0.1:8765/services-appointments/evidence/step3/gallery.html)

Keep `--root ui-lab`: the server's historical default serves only the dashboard subtree. It binds to loopback and rejects writes. If 8765 is occupied, use another free port; do not take over an existing listener. No package installation, Django startup or database setup is needed. The generated `dist/` may be Git-ignored or absent in a fresh checkout; rebuild only after confirming the existing pinned toolchain is available.

## Five compositions and local interactions

1. **Workspace:** original six GET filter meanings, historical `status` alias, 50-row pagination, mixed appointment/request records, desktop table and tablet/mobile cards. New Appointment and Create Request open local forms. Requests and scheduled records retain distinct state/time semantics.
2. **Appointment details:** edit, related-record disclosure, invoice destination intent, and terminal-action confirmation previews. Only Scheduled has outgoing status choices; editing a terminal preview does not reopen it.
3. **Create/edit:** one full-page form in create/edit/from-request modes; required fields and time ordering, native selectors, inline Client dialog, preserved draft, busy/success states. This is local validation, not server-rule coverage.
4. **Public booking:** four named steps, both intents, selected day/time, Company/Individual, review/edit links, and distinct outcomes. Synthetic Book now adds an appointment to the local workspace without a duplicate request row; Contact before booking adds unscheduled follow-up. This is a supplied local outcome projection, not a second authoritative booking service.
5. **Follow-up:** request details, missing Client completion and request-linked scheduling. The completion subview distinguishes saved Client information from an appointment. Review controls expose the proposed direct scheduling resume (D4); the existing Client Details destination is identified explicitly. Create/edit request forms belong to this composition.

The **Interactive prototype** disclosure above the product frame provides screen/scenario selection and proposal notes. Public views hide staff navigation. Product navigation within the prototype retains local drafts; review scenario changes deliberately reload and reset the demo. Client, invoice, dashboard, history/settings and contact destinations outside the five compositions are intercepted as destination previews. No real request/call/email is made.

## Scenarios and contracts

Use `?view=workspace|detail|form|public|request` with `&theme=light|dark`. `view` is review-only. Existing `state` remains a workspace filter, not a scenario name. `scenario` accepts:

- `populated`, `long`, `empty`, `pagination`, `invalid`, `loading`, `error`;
- `staff`, `admin`, `accountant`, `viewer`, `read-only`, `request-only`, `appointments-only`, `locked`;
- `no-slots`, `conflict`, `uncertain` for public booking error examples.

Additional review destinations: `view=completion&id=703`, `view=request-form`, and `view=outcome&result=scheduled|request`. Deep-linked outcomes are explicit synthetic fixtures, not trusted application receipts. `mode=edit|from-request` selects the shared appointment form mode with an existing synthetic `id`.

The fixed supplied clock is **14 November 2026 09:00 UTC**; records use **America/Lower_Princes, UTC−04:00**, and public slots use 16–18 November. These are historical fixture dates, not the current day. Availability choices, conflicts and access flags are supplied examples. There is no live availability feed, production matching engine, buffer enforcement or server authorization evaluator. Known Client projections retain their supplied classification; missing/ambiguous data remains Unknown/Unspecified. Legitimate historical multiple appointments and compatibility route names remain application contracts, not newly implemented prototype services.

The existing list retains `q`, `state`, `source`, `classification`, `staff`, `service`, `status` compatibility, row identity and all nine record information subjects. Staff filtering removes requests; Service does not infer category matches. Appointment/request access flags are independent. Accountant/Viewer reads and Services billing permissions are not replaced with Logistics policy.

## Structure and reuse

- `src/fixtures.js`: existing synthetic list projections/filter options.
- `src/render.js`: existing workspace composition and shared shell usage.
- `src/journey.js`: added detail/form/public/follow-up compositions and synthetic context.
- `src/app.js`: connected local navigation/drafts/projections, validation and feedback.
- `src/input.css`: existing table/cards plus new responsive compositions using shared tokens.
- `src/index.html`: existing isolated document and CSP (`connect-src 'none'`, `form-action 'none'`).
- `dist/`, `build-meta.json`: generated by the existing lab-only builder.
- `validate_step3.py`, `validate_states_step3.py`: static-loopback Chromium/axe/task checks; no Django imports.
- `supplement_contrast.py`: computed-color supplement for retained dialog incompletes.
- `review_evidence.py`: gallery/summary and protected-file verification.
- `evidence/step3/`: raw results, screenshots, gallery, source hashes and protected-file manifest.

Shared tokens/components are read from `ui-lab/design-system/`; the existing pinned Step 4 build tools, local Manrope/logo and licenses are reused. No dashboard build or shared component edit is performed.

## Build and validation

Only use already installed tools; missing dependencies require separate approval. Do not run installation commands as part of this prototype.

```sh
node ui-lab/tools/build.mjs services-appointments
# If Playwright's matching browser is absent, select an existing compatible browser:
# export PWA_CHROMIUM=/path/to/already-installed/chrome
.venv/bin/python -B ui-lab/services-appointments/validate_step3.py
.venv/bin/python -B ui-lab/services-appointments/validate_states_step3.py
.venv/bin/python -B ui-lab/services-appointments/supplement_contrast.py
.venv/bin/python -B ui-lab/services-appointments/review_evidence.py
```

These checks start their own GET-only ephemeral loopback servers and write evidence only under this package. They never contact the ordinary local Django listener or any application database/provider. Repeats replace the current Step 3 results/screenshots. Retain any failed evidence separately when needed. `STEP3_TASKS_ONLY=1` runs tasks alone and writes `tasks-only.json`, explicitly not a replacement for the full matrix.

The 40-case primary matrix covers five compositions × 1440/768/390/320px × light/dark. Additional state cases and dialog/wizard captures are documented in the [Step 3 report](../../docs/design/motionmate-ui-lab/12-appointments-bookings-prototype-review.md). The original `check.py` and its earlier evidence describe the Step 5 list-only route-intent demonstration; its navigation assumptions do not certify the connected Step 3 journey. The new validators are the current checks.

## Review boundary

D2 terminal confirmations, D4 request resume/linkage, D5 mode clearing/fallback/server validation and D6 outcome context remain proposed interactions/server dependencies. No reopening, notification, invoice automation, new conflict/buffer policy or non-JS application fallback is implemented. Simulated client/booking writes and status previews never prove real POST/CSRF/retry/provider behavior. Step 3 has no Django BEFORE/AFTER or live-runtime verification.

Stop for visual review. Design approval does not authorize production integration, framework changes, data/schema work, staging, commits, push/merge or deployment. Follow the established [review workflow](../../docs/design/motionmate-ui-lab/PREVIEW-WORKFLOW.md) and [runbook](../../docs/design/motionmate-ui-lab/REPRODUCIBILITY.md) for a separately authorized next phase.
