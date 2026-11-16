# Automated Motionmate UI workflow

Use [$motionmate-ui-workflow](../../../.agents/skills/motionmate-ui-workflow/SKILL.md)
to orchestrate work and save progress. It complements the existing
[UI skill](../../../.agents/skills/motionmate-ui/SKILL.md),
[preview workflow](PREVIEW-WORKFLOW.md) and [setup runbook](REPRODUCIBILITY.md).
Phoenix remains the production foundation. No package installation is needed
for the state helper; it uses Python's standard library.

The repository skill is stored under `.agents/skills/`, with a narrow Git-ignore
exception so it can be included in a separately authorized future commit. Nothing
in setup commits it. A running Codex session may need a new session to refresh its
skill catalog; the explicit file path below can also be read directly.

## Copy-and-paste requests

**Services Quick Change — implementation explicitly authorized:**

```text
Use $motionmate-ui-workflow in Quick Change mode for Services. Clean up the
spacing and labels on /appointments/create/. I authorize local presentation
implementation within that bounded scope and workflow records. Preserve field
names, validation, draft creation, routes and guards. No full prototype. Inspect
available safe validation resources; do not create databases or install tools.
```

For a plan only, replace the implementation sentence with: “Produce the change
plan only; do not implement.” Quick Change then stops after the plan. An invoice
layout repair uses the same mode, preserving authoritative billing behavior and
adding appropriate rendered PDF/email checks within the authorized resources.

**Services Full Redesign — proceed automatically through design review:**

```text
Use $motionmate-ui-workflow in Full Redesign mode for the Services Appointments
workspace at /appointments/. Create task records, audit the real source, write
the brief, build a new task-owned connected synthetic prototype and validate it
with existing installed tools and loopback browser evidence. Do not overwrite
historical prototypes/evidence. Stop at Gate A. No application implementation,
database setup, dependency installation or release actions are authorized.
```

**Logistics Full Redesign — its own visual approval:**

```text
Use $motionmate-ui-workflow in Full Redesign mode for the Logistics parcel list.
Resolve its actual route. Create task records, audit it, and build/validate a
separate connected synthetic prototype using existing tools and loopback evidence.
Preserve location grants, operational transitions, scanner fallback and finance
restrictions. Services is outside scope. Stop at Gate A; do not implement or
access application databases. Do not assume Services design approval covers it.
```

**Resume an interrupted workflow:**

```text
Use $motionmate-ui-workflow to resume
docs/design/motionmate-ui-lab/workflows/services-example/state.json.
Verify saved approvals against this conversation and the latest scope, artifact
hashes and current worktree. Continue the first authorized incomplete phase.
Keep required approval gates pending; do not infer consent from saved progress.
```

**Gate A — design approval only:**

```text
Approve design v1 for task services-example as shown in its recorded prototype
review, excluding its deferred functional decisions. Continue with the production
integration audit, exact proposed manifest and risk/regression plan. Stop at B.
```

**Gate B — approve the concrete manifest and identified resources:**

```text
Authorize local implementation for task services-example, design v1, limited to
the exact manifest and exclusions in its reviewed integration.md. I also authorize
the identified disposable BEFORE/AFTER environment, synthetic fixtures, existing
migrations only within those empty disposable databases, and backend/browser
checks described there. Preserve ordinary databases and disable external
providers. No installs, schema changes, Git mutations or deployment. Continue
through validation and present Gate C.
```

Use that resource authorization only after the integration report identifies the
resources and effects. Reuse an existing environment authorization where valid;
do not request it again. If the user authorizes implementation without setup,
continue independent work and leave dependent validation pending.

**Gate C — acceptance:**

```text
Accept the completed candidate identified in task services-example's validation
report and recorded BEFORE/AFTER comparison, with its disclosed limitations.
No release, Git operation or cleanup is authorized.
```

If skill discovery has not refreshed, say: “Read and use
`.agents/skills/motionmate-ui-workflow/SKILL.md` for this task.”

## Saved task state and helper

An authorized task creates `workflows/<task-id>/state.json`, `brief.md`,
`prototype-review.md`, `integration.md` and `validation.md`. Quick tasks leave
the prototype report N/A; no prototype is created. See the
[state convention](../../../.agents/skills/motionmate-ui-workflow/references/state.md)
for fields and approval records.

```sh
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py init \
  --task services-example --vertical SERVICE --mode quick \
  --route /appointments/create/ --objective 'Improve labels and spacing'
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py check \
  docs/design/motionmate-ui-lab/workflows/services-example/state.json
```

The agent updates actual completed phases/evidence, creates the closed manifest
and runs `baseline STATE` before recording implementation authorization. It
records the real instruction and digest bindings, then uses `checkpoint STATE`
to save the computed next phase. Run `check STATE --pre-implementation` immediately
before edits to detect Git/target-file drift. The conventional task directory is
excluded from the Git-status comparison so checkpoint/report writes do not
invalidate their own baseline; it is not excluded from the approved production
file hashes. Custom `--output` directories inside the repository should remain
untracked or have their status effects reviewed explicitly.

`check` is read-only and reports a pending gate with exit 0: the record is valid,
but approval is still needed. Invalid/stale records return nonzero. No helper
executes phase commands, grants consent, authenticates approval quotes, starts
previews or accesses a database. Codex performs the authorized phases using the
existing tools and records their evidence.

## Review and release boundaries

Full flow: audit → brief → prototype → prototype validation → **A** → integration
manifest/risks → **B** → actual interactive BEFORE → implementation → backend/
browser validation → real AFTER comparison/report → **C**. Capture BEFORE from
the actual working tree before implementation. Synthetic design prototypes are
distinct from real Django review apps. Missing runtime permissions/tooling must
remain visible; source inspection cannot replace a rendered pass.

Shared files need both Services and Logistics consumer assessment and regression
coverage. Standard widths are **1440, 768, 390 and 320px**, in light/dark where
applicable, with accessibility, difficult states, interactions and applicable
role/module/subscription/location variants. Existing generic capture tools need
task-specific 320px and journey checks. Keep raw failures and axe incompletes.

Recommend a separately authorized isolated worktree when independent features
overlap. Never create/switch/merge/delete branches or worktrees automatically.
No ordinary database/provider access, destructive tests, installs, schema work,
staging, commits, pushes, merges, deployments or cleanup follows a UI approval.

## Offline self-validation

These commands validate workflow infrastructure only; they use synthetic files
in temporary directories and do not initialize Django or any database:

```sh
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/test_workflow.py -v
.venv/bin/python -B scripts/check_ui_workflow.py
git diff --check
```

The test suite models each approval gate, Quick Change authorization, interrupted
state, stale approvals, concurrent edits and the retained Appointments documents.
Its “SIMULATION ONLY” approvals never become actual task consent. See the
[setup validation report](AUTOMATED-WORKFLOW-VALIDATION.md) for this run's evidence.
