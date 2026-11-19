# Automated Motionmate UI workflow v2

Use [$motionmate-ui-workflow](../../../.agents/skills/motionmate-ui-workflow/SKILL.md)
for Quick Change or Full Redesign. It complements the existing
[UI skill](../../../.agents/skills/motionmate-ui/SKILL.md),
[real preview workflow](PREVIEW-WORKFLOW.md) and [setup runbook](REPRODUCIBILITY.md).
Phoenix 1.23.0 stays in production; Tailwind/DaisyUI remain optional references.
The state helper needs only Python's standard library and no installation.

Full Redesign now follows:

1. Automatically audit existing Django functionality and prepare the design brief.
2. **Gate A:** stop for design-direction approval of an identifiable brief/version.
3. Automatically prepare the production integration plan and exact file manifest.
4. **Gate B:** stop for implementation and applicable disposable-resource consent.
5. Preserve actual working-tree BEFORE, implement approved files locally, validate
   Django behavior/accessibility/responsive layouts/regressions, then refresh AFTER.
6. Present **one real interactive Django BEFORE/AFTER pair** with synthetic records.
7. **Gate C:** stop for final acceptance of the identified candidate and limitations.
8. After C, automatically prepare an exact commit manifest; recommend one commit
   per accepted redesign. Wait for explicit authorization before any commit.

No standalone interactive lab or synthetic prototype is mandatory. A prototype
needs an explicit request or an explained major uncertainty plus authorization;
it cannot replace actual templates, routes, authentication, forms and permissions.
Quick Change retains a concise plan, already authorized bounded implementation
and focused validation, without a separate design/acceptance cycle.

## Example requests

**Quick Change, already authorized:**

```text
Use $motionmate-ui-workflow in Quick Change mode for Services at
/appointments/create/. Improve labels and spacing. I authorize the bounded local
presentation repair and workflow records. Preserve forms, drafts, routes and
guards. Use existing authorized validation resources; no new setup or databases.
```

For planning only, say “Produce the plan only; do not implement.” No second
implementation prompt is needed when the original request covers the exact files.
Missing runtime evidence stays disclosed; setup is never implicit.

**Full Redesign, through Gate A:**

```text
Use $motionmate-ui-workflow v2 in Full Redesign mode for Services at /appointments/.
Create task records, audit actual functionality and propose screen improvements
in a versioned design brief. Stop at Gate A. No standalone prototype, application
implementation, database setup, installs or Git/release actions are authorized.
```

For Logistics, name LOGISTICS and the actual parcel/shipment route. Preserve its
location grants, permitted transitions, scanner fallback and financial controls;
Services remains outside scope. Services design approval never covers Logistics.

**Gate A, design direction only:**

```text
Approve the recorded design brief v1 for services-example, excluding its deferred
functional decisions. Prepare the exact production integration manifest, risks,
shared-consumer assessment and disposable validation plan. Stop at Gate B.
```

**Gate B, concrete files and resources:**

```text
Authorize local implementation for services-example, design v1, limited to the
exact reviewed manifest and exclusions in integration.md. I authorize the
identified disposable PostgreSQL BEFORE/AFTER and test environments, synthetic
fixtures, existing migrations only in those empty owned databases, and described
backend/browser checks. Preserve ordinary databases and disable external providers.
No installs, schema changes, Git release actions or cleanup. Present Gate C.
```

The integration plan must identify resources/actions before this approval.
Reuse valid earlier resource authorization. If setup permission is missing,
continue independent authorized work and leave Full Redesign review pending.

**Gate C, acceptance and automatic preparation:**

```text
Accept the identified candidate and actual Django BEFORE/AFTER review for
services-example, with disclosed limitations. Prepare its exact commit manifest.
No staging, commit, push, merge, deployment or cleanup is authorized.
```

Commit preparation follows C automatically as workflow documentation even when
not repeated in the acceptance message; it never grants commit authorization.

**Resume:**

```text
Use $motionmate-ui-workflow to resume
 docs/design/motionmate-ui-lab/workflows/services-example/state.json.
Verify the latest instructions, saved approvals, file/source/fixture identities,
worktree and checkpoints. Continue the first authorized incomplete phase; preserve
concurrent edits and all pending gates. Do not reopen completed redesigns.
```

If discovery has not refreshed, read the skill's exact path directly. No new or
competing skill is needed.

## State and helper commands

New tasks create only `state.json`, `brief.md`, `integration.md`, `validation.md`
under `workflows/<task-id>/`. No prototype review, build or browser output is
created by initialization. Optional exploration can copy its template separately.
See [state/resume conventions](../../../.agents/skills/motionmate-ui-workflow/references/state.md)
for environment records, approvals, categories and inventory fields.

```sh
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py init \
  --task services-example --vertical SERVICE --mode full \
  --route /appointments/ --objective 'Improve the Appointments workspace'
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py check \
  docs/design/motionmate-ui-lab/workflows/services-example/state.json
```

Record completed phases/evidence and actual user approvals. Run `baseline STATE`
once after the closed manifest and before B. Immediately before application
edits, run `check STATE --pre-implementation`. Save reviewed progress with
`checkpoint STATE`, and use `check STATE --resume` after interruption. These
checks detect branch/HEAD/status changes, overlapping target changes and unrelated
dirty-file changes. Do not checkpoint unexplained drift to make it disappear.
The conventional task directory is exempt from status comparison; approved source
hashes are still checked. Prefer external `--output` for synthetic simulations.

`check` is read-only. A pending gate returns 0 with a stop instruction; invalid or
stale records fail. No helper executes phase commands, starts previews, accesses a
database, authenticates approval quotes or verifies live ownership. Agents must
verify actual user consent and use existing database ownership guards.

Schema 1 retains original phases and digest behavior. Completed records,
accepted candidates, historical approvals/manifests and evidence remain unchanged.
Archived evidence may need its preserved local archive to verify old hashes;
do not rewrite them for v2. No automatic migration or historical commit packaging.

## Evidence and commit preparation

Test representative mobile/tablet/desktop layouts and both themes; add 320px
reflow/RTL/zoom where relevant. Exercise actual workflows, permissions, difficult
states, forms and accessibility. Shared files need impact/planned regressions and
results for both verticals. Test coverage does not require a screenshot per case.
Keep selected before/after views, meaningful failures, axe incompletes and compact
results; do not retain redundant screenshot matrices in Git by default.

Use owned external session/task directories for browser output, logs, temporary
source copies, builds and PostgreSQL. When an existing tool hardcodes in-tree
output, document it and use only a narrow task-specific ignore if necessary.
Never broadly ignore required runtime/reproducibility assets or alter historical
evidence. No new ignore rules are needed for the default v2 offline helper.

After C, classify files as implementation, tests, documentation, required_asset
or generated. The accepted implementation manifest supplies source categories;
the helper discovers design/task records. Explicit `artifact_inventory` records
select representative screenshots, required assets and any ownership exceptions.
Runtime fonts, licenses, bundled assets and fixture/check source must survive
packaging even if generated. Exclude unnecessary builds/caches/logs/database
contents, without deleting them or treating every ignored file as disposable.

```sh
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py prepare-commit \
  docs/design/motionmate-ui-lab/workflows/services-example/state.json
```

This writes `commit-manifest.json`: exact included/excluded paths, categories,
purposes and file hashes, bound to the accepted candidate and implementation
manifest. It lists its own path without a self hash. It does not change accepted
state. Repeat runs verify identical output; differences require reconciliation.
Unclassified task source/binary files and new changes outside approved scope stop
preparation. Required assets cannot be discarded as generated. One commit per
completed redesign is recommended; explicit commit authorization is still needed.
Never automatically stage, commit, push, merge, deploy or clean up.

## Offline validation

These commands use synthetic workflow files in external temporary directories,
not Django, PostgreSQL or ordinary application data:

```sh
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/test_workflow.py -v
.venv/bin/python -B scripts/check_ui_workflow.py
git diff --check
```

The repository-wide checker also checks historical preservation records; report
unrelated historical discrepancies separately. See the
[v2 validation report](AUTOMATED-WORKFLOW-V2-VALIDATION.md). The
[original setup report](AUTOMATED-WORKFLOW-VALIDATION.md) remains historical.
