# Phase execution and existing tools

Read only the domain documentation relevant to the route; `AGENTS.md` supplies
the authoritative links. For shared components, trace both verticals' consumers.
Use the existing [preview workflow](../../../../docs/design/motionmate-ui-lab/PREVIEW-WORKFLOW.md)
and [setup](../../../../docs/design/motionmate-ui-lab/REPRODUCIBILITY.md).
Neither these commands nor a historical run is present authorization.

## Audit and plan

Trace route → resolver/guard → view/service → form/model → template/asset and
downstream effects. Inspect scripts before running them: even GET navigation
can write (request scheduling and Booking Settings are documented examples).
Inspect branch/status, unrelated changes, generated/ignored evidence and target
hashes. Record workflow, form/JS, financial, permission and tenant contracts.
Use `brief.md` for the audit, Quick Change plan or Full Redesign brief.

Quick Change stops after `plan` unless explicit implementation authorization
already covers the repair. Do not infer it from “review”, “suggest” or approval
of appearance. Record an initially authorized repair as implementation approval,
bound to the narrow manifest; do not invent a second gate.

## Design and Gate A (Full Redesign)

Compose connected journeys in a **new task-owned** `ui-lab/<screen>/` package
with supplied synthetic scenarios. Reuse `ui-lab/design-system/`, local Manrope,
existing shell/components and pinned tools. Preserve dashboard/Appointments
sources, frozen builds and historical review records. Use `scenario` for review
variants where `state` is already an application filter. Intercept out-of-scope
destinations; label proposed server outcomes outside the product frame.

Existing tools, when their required resources and writes are authorized:

```sh
node ui-lab/tools/build.mjs TASK_SCREEN
.venv/bin/python -B ui-lab/services-dashboard/tools/serve.py --root ui-lab --port FREE_PORT
.venv/bin/python -B ui-lab/tools/capture.py --screen TASK_SCREEN
```

Check the builder's supported package structure first. The generic capture
currently covers **1440/768/390 only**; add task-scoped 320px and connected
journey/state checks rather than declaring its default sufficient. Appointments'
`validate_step3.py` / `validate_states_step3.py` are five-composition examples,
not general validators. Do not rerun them into historical evidence directories.

Use `prototype-review.md`: 1440×900, 768×1024, 390×844 and 320×844; light/dark
where supported; long/empty/error/loading/restricted states; overflow, labels,
contrast, keyboard/focus, touch targets, dialogs, draft continuity, reduced
motion and affected interactions. Preserve raw axe violations/incompletes,
console failures and initial failures. Record unsupported browser/AT/RTL/native
zoom checks rather than claiming full accessibility conformance.

At Gate A save the design version and immutable artifact hashes. Ask for that
version's visual/interaction approval and identify still-open functional choices.
New design bytes invalidate the old approval until the change is reconciled.

## Integration and Gate B

Use `integration.md` for the exact proposed additions/modifications, purpose,
shared consumers, contracts, exclusions, risk/compatibility and validation plan.
No wildcard manifest entries, implicit generated outputs or follow-on files.
Inspect existing source, not just a historical prototype's apparent behavior.
Separate presentation from decisions about financial, permission, data or server
semantics. A file manifest alone never authorizes those decisions.

Run `baseline STATE` before recording B. It saves current branch/HEAD/status and
target hashes; review any dirty target with the user/session ownership evidence.
Record excluded dirty files, deferred decisions and protected evidence. Review
the emitted manifest digest; bind implementation approval to it and the design
version. Runtime/test permissions must identify resources/actions separately.
Do not automatically create or switch branches/worktrees.

## Actual BEFORE, implementation and validation

Before edits, capture **actual working-tree bytes**, including authorized
uncommitted/untracked runtime sources. HEAD is not a substitute. Under explicit
disposable-runtime permission, follow the existing ownership-checked tooling:

```sh
.venv/bin/python -B scripts/motionmate_preview.py capture
.venv/bin/python -B scripts/motionmate_preview.py create \
  --before-snapshot BEFORE_SNAPSHOT --route ACTUAL_ROUTE
# After authorized edits and checks:
.venv/bin/python -B scripts/motionmate_preview.py refresh-after --session SESSION_PATH
```

Record real identities: settings module, disposable database name/owner,
canonical cluster directory/system identifier, port/process and sanitized
source/session IDs. A test-looking name or nonstandard port is insufficient.
Keep providers/email/workers disabled and do not load ordinary `.env` files or
copy records. Distinct session/CSRF cookies and identical initial synthetic
fixtures support both sides. Review writes persist independently; never reset or
reseed them to manufacture parity. Preserve BEFORE throughout.

`motionmate_preview.py validate` and `check-dashboard` target dashboard contracts;
`--route` only changes the launch destination. The Appointments adapter exists
at `scripts/ui_preview/appointments_checks.py`; inspect its module entrypoint,
guards, fixture contract and side effects before using it. New screens need an
audited adapter within the authorized tooling manifest, or a disclosed missing
validation capability. Do not weaken financial/network/ownership guards.

Use `validation.md` for backend contracts, real form POST/CSRF/retry checks,
responsive/themes, affected roles/modules/subscriptions/location states and
cross-vertical regressions. Quick Change needs focused checks without inventing
tests for simple copy/markup changes. Check rendered PDFs when relevant. Keep
static, synthetic-browser, isolated Django/backend, actual interactive Django,
manual and provider evidence distinct. A historical debug-allocator workaround
does not prove ordinary-runtime health. Runtime failures stay visible.

Record actual results and commands once; repair scoped failures and repeat only
affected checks. If runtime setup is not authorized/available, finish independent
source work and report the limitation; do not label missing checks as passed.

## Gate C and final handoff

Present real BEFORE/AFTER URLs, immutable sources, fixture context, changed file
list, representative evidence and unresolved findings. Quick Change reports its
result without adding a full-redesign acceptance ceremony. Full Redesign stops
at C for explicit acceptance, including any acknowledged limitations. A new
design, manifest expansion or modified candidate invalidates the corresponding
approval; routine fixes inside approved scope do not require B again.
Leave review resources available. No automatic cleanup or release follows.
