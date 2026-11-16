# Automated UI workflow setup — validation report

16 November 2026. Local workflow infrastructure/documentation only.
Starting branch: `experiment/motionmate-ui-redesign`; HEAD:
`09ba474815806f362f2f146bc99c82bd2ba58112`. The initial working tree was clean.
No concurrent file changes were observed during this task; other editor/thread
activity cannot be ruled out solely from Git status.

## Deliverables and exact change manifest

The new [skill](../../../.agents/skills/motionmate-ui-workflow/SKILL.md) supports
Quick Change and Full Redesign. It orchestrates the existing Motionmate tools,
saves task state, reuses scoped authorization and stops at the required gates.
The [usage guide](AUTOMATED-WORKFLOW.md) includes invocation, resume and approval
examples. No application screen was redesigned as part of this setup.

| Action | Exact file | Purpose |
| --- | --- | --- |
| Modify | `.gitignore` | Narrow exception for the new repository skill; preserve all existing ignore rules. |
| Add | `.agents/skills/motionmate-ui-workflow/SKILL.md` | Mode selection, orchestration, A/B/C gates and permanent boundaries. |
| Add | `.agents/skills/motionmate-ui-workflow/agents/openai.yaml` | Discoverable skill metadata and invocation example. |
| Add | `.agents/skills/motionmate-ui-workflow/references/stages.md` | Existing tooling, phase execution and evidence requirements. |
| Add | `.agents/skills/motionmate-ui-workflow/references/state.md` | Durable state, consent bindings, concurrency and resume convention. |
| Add | `.agents/skills/motionmate-ui-workflow/assets/state.json` | Task-state template with pending approvals. |
| Add | `.agents/skills/motionmate-ui-workflow/assets/brief.md` | Audit, concise Quick Change plan or redesign brief. |
| Add | `.agents/skills/motionmate-ui-workflow/assets/prototype-review.md` | Connected prototype, responsive/accessibility/interaction evidence and Gate A. |
| Add | `.agents/skills/motionmate-ui-workflow/assets/integration.md` | Exact proposed manifest, compatibility, risks and Gate B. |
| Add | `.agents/skills/motionmate-ui-workflow/assets/validation.md` | Backend/browser/regression evidence, actual BEFORE/AFTER and acceptance. |
| Add | `.agents/skills/motionmate-ui-workflow/scripts/workflow.py` | Standard-library-only init, baseline, check and atomic checkpoint helper. |
| Add | `.agents/skills/motionmate-ui-workflow/scripts/test_workflow.py` | Synthetic gate, scope, concurrency, interruption and historical-reference tests. |
| Add | `docs/design/motionmate-ui-lab/AUTOMATED-WORKFLOW.md` | Usage and authorization examples. |
| Add | `docs/design/motionmate-ui-lab/AUTOMATED-WORKFLOW-VALIDATION.md` | This report. |

Total: **13 new files, one existing file modified**. Nothing staged or committed.
The existing UI skill, preview runner, design system, historical artifacts and
approval records were not edited or restructured.

## Source/reference audit

Read the current repository instructions, skill-creator guidance, existing
Motionmate UI skill/Phoenix map, UI review workflow/setup, approved design system
and vertical boundaries. Reviewed the Services dashboard design-system/integration
and validation conventions, plus Appointments' retained
[audit](10-appointments-bookings-audit.md),
[brief](11-appointments-bookings-design-brief.md),
[prototype review](12-appointments-bookings-prototype-review.md),
[integration proposal](13-appointments-bookings-production-integration-audit.md)
and connected prototype README. Inspected existing capture/build/preview adapter
interfaces without executing application or browser workflows.

Preserved these distinctions in the skill:

- Synthetic connected design previews versus actual interactive Django reviews.
- Services visual approval versus Logistics' separate approval and policies.
- Visual/interaction approval versus functional decisions and production scope.
- Quick repairs explicitly authorized initially versus plan-only requests.
- Historical evidence versus checks actually executed in the current task.
- Application implementation/acceptance versus separately authorized release.

## Checks actually executed

| Check | Result and coverage |
| --- | --- |
| Synthetic unit suite | **17/17 passed** using temporary files; no Django/database initialization. |
| Cold source-copy unit suite | **17/17 passed** with the new skill and four historical reference documents copied to a separate temporary tree. This tests the helper without checkout-specific generated artifacts; it is not a full runtime/fresh-checkout application test. |
| CLI smoke checks | **7/7 expected outcomes**: init, pending B checkpoint, manifest baseline, authorized-before checkpoint, read-only pre-implementation check, refusal to rebaseline approved work, refusal to overwrite a task. |
| Approval behavior | A/B/C stops; Quick Change requires implementation consent without a prototype; Logistics has its own design gate. |
| Stale/concurrent state | Changed design bytes/version, manifest/objective/vertical expansion, candidate changes after acceptance, Git/file drift, duplicate/unsafe/symlink paths and skipped evidence are rejected. |
| Interruption/resume | Saved-state reload retains B; simulated interrupted atomic replacement retains the previous checkpoint. |
| Validation records | Pending results cannot be marked complete; non-pass results require a disclosed limitation. Approval records require source/quote/scope. |
| Skill frontmatter/scaffold validator | Passed. |
| Ruff / format | Both new Python files passed. |
| Local Markdown links / source visibility / whitespace | Passed for new Markdown links, new skill source visibility and `git diff --check`. |
| Existing `scripts/check_ui_workflow.py` | **Nonzero: one pre-existing frozen-source hash mismatch**, detailed below. No new checker failure was repaired by changing application files or preservation metadata. |

Raw local logs, initial preservation snapshot, CLI results and synthetic
simulation are retained at `/tmp/motionmate-workflow-validation-0f05l78e/`.
Temporary evidence may disappear; this source report and
the runnable suite preserve the procedure and findings. No commit occurred.

## Appointments workflow simulation

Only existing documents/source were read; all phase completions and consent
records in the simulation are marked **SIMULATION ONLY**. No real task consent
was generated and no historical approval was modified.

| Synthetic progress | Observed next action |
| --- | --- |
| Map retained audit, brief, connected prototype and validation documents into a new synthetic state | Stop at **A**. |
| Supply synthetic design consent; complete integration audit reference | Stop at **B**. No implementation permission inferred from appearance. |
| Supply synthetic manifest consent and simulated BEFORE/implementation/validation/comparison/report evidence | Stop at **C**. No acceptance inferred from completion/tests. |
| Supply synthetic candidate acceptance | Workflow complete; no Git, cleanup or deployment action follows. |

The historical-reference test also verifies that all four referenced documents
retain their original hashes. It deliberately stops at B. The broader A→B→C
simulation runs only in temporary state; it neither reopens nor validates the
actual Appointments implementation. Deferred D1–D9 decisions remain historical
inputs, never automatically authorized features.

## Existing checker limitation and preservation proof

The retained checker expects the earlier Step 7 hash of `src/apps/crm/tests.py`:

```text
Historical expected: c4fc60270a62cb107c707bcb5af55d2fc1a453d957093ca19c9673d47280301f
Pre-edit snapshot:  2f87d446cbc25ef9c14f4c21546965abb6753470d2acdfb8752feb0751fd1523
Current file:       2f87d446cbc25ef9c14f4c21546965abb6753470d2acdfb8752feb0751fd1523
```

The mismatch is present in the starting bytes. Application tests and historical
preservation metadata were left unchanged. The existing checker reported this
single failure while inspecting its 147 proposed paths, 18 essential screenshots,
11 protected Step 7 files and 22 frozen references. This setup does not claim
the repository's broader checker is green.

A pre-edit SHA-256 inventory covered **15,390 existing files**, including tracked/
nonignored source, the existing UI skill and ignored Phoenix reference library.
Final comparison retained **15,389 unchanged files**; `.gitignore` is the sole
authorized existing-file change. Branch, HEAD and index remain unchanged.
No application source/template/CSS/JS, historical evidence or reference file was
added, removed or modified by this setup.

## Verification limits

The helper checks offline consistency, hashes, ordered phases and recorded
approval bindings. It cannot authenticate a user quote, prove runtime ownership
from a saved assertion or enforce every semantic scope restriction. The skill
requires the agent to verify current authorization, actual disposable resource
identity and meaningful evidence before acting.

No Django/backend/browser/PDF application tests, interactive previews or provider
checks were run; they are unnecessary for infrastructure-only setup and would
not follow from these offline passes. No ordinary or disposable database was
accessed or created. No dependency installation, migration, schema change,
application-data write, external-provider operation, branch/worktree mutation,
staging, commit, push, merge or deployment occurred. Historical runtime/browser
limitations remain unverified in this task.
