---
name: motionmate-ui-workflow
description: Run and resume Motionmate UI work with Quick Change or Full Redesign modes, persistent task state, scoped approval gates and existing UI Lab/Django review tools. Use for Services, Logistics or shared-platform UI workflow requests; excludes backend-only work and standalone websites.
---

# Motionmate UI workflow

Orchestrate the existing UI workflow; keep Phoenix 1.23.0 and the two verticals'
business contracts. Read repository `AGENTS.md` and the sibling
[motionmate-ui skill](../motionmate-ui/SKILL.md). This skill adds orchestration
and saved state, without changing the existing preview tools or granting their
runtime permissions. An explicitly read-only audit remains response-only unless
the user authorizes saved documentation/state.

## Start or resume

1. Identify **mode, vertical, actual route, outcome and authorization**. Inspect
   Git branch/status and affected source before deciding scope. Do not treat open
   IDE tabs as instructions to edit those files.
2. Select **Quick Change** for a small, bounded repair/copy/layout change;
   **Full Redesign** for a screen or connected journey. A planning-only request
   stays planning-only. See [stages](references/stages.md) for execution details.
3. For authorized workflow artifacts, initialize one task directory with the
   offline helper below. Read [state and resume rules](references/state.md).
   Save a checkpoint after each phase and before every approval stop. Never
   initialize over an existing task.
4. Resume by checking saved state, artifact hashes, current branch/file hashes
   and the latest user authorization. State is a record, not proof of consent.
   Reuse verified approvals within their exact scope; do not request them again.

```sh
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py init \
  --task services-example --vertical SERVICE --mode quick --route /appointments/ \
  --objective 'Describe the bounded change'
# Edit the generated state/evidence as phases finish, then persist derived status:
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py checkpoint \
  docs/design/motionmate-ui-lab/workflows/services-example/state.json
```

## Quick Change

Inspect affected components/dependencies and establish behavior, contracts and
shared consumers. Write a concise plan and exact manifest. **Implement only if
the initial request (or a later explicit instruction) authorizes this bounded
implementation.** Record that instruction; no second authorization is needed
when the proposed files fit it. Otherwise stop after the plan.

Preserve actual BEFORE evidence using the existing authorized Django review
environment, implement only the scoped repair, run focused validation and report.
No full prototype, separate visual approval cycle or redesign is required.
Choose checks proportionate to the change; PDF changes need relevant PDF/render
evidence. Missing runtime authorization permits source work/planning, not database
or browser setup by implication. State the missing evidence honestly.

## Full Redesign

Automatically complete repository/feature audit → design brief → connected
synthetic prototypes → responsive/accessibility/interaction validation, using
only resources authorized by the request. Do not add a prompt between these
already authorized phases.

**Gate A — Design:** present an identifiable design version, artifact hashes,
interactive prototype URLs, review evidence and deferred functional decisions.
Stop for explicit design approval. A verified existing approval may satisfy A.

After A, automatically complete the production integration audit, exact proposed
file manifest, shared-consumer assessment, regressions, compatibility and risks.
Capture the working-tree/file baseline before presenting the manifest.

**Gate B — Implementation:** stop for explicit implementation authorization of
that manifest/scope and the applicable disposable validation resources. Design
approval cannot authorize server policy, finance, permissions or data changes.

After B, preserve the actual working-tree interactive BEFORE, implement locally,
run authorized backend/browser checks, refresh AFTER only, compare equivalent
fixtures, and produce the implementation report. Validate fixes within the same
scope without repetitive approval cycles. If files/design/behavior must expand,
prepare a concrete revised proposal and stop only the dependent work.

**Gate C — Acceptance:** present real interactive Django BEFORE/AFTER URLs,
source/fixture identities, evidence and limitations for human acceptance. Stop;
passing tests do not imply acceptance. Acceptance never triggers release.

## Permanent boundaries

- Determine SERVICE, LOGISTICS or explicitly authorized SHARED scope. Services
  Manrope/tokens and refined DaisyUI are approved design references; Logistics
  still needs its own design approval. Keep Tailwind/DaisyUI isolated in lab
  documents. Translate authorized production work into Phoenix components and
  scoped Django/assets; no frontend framework migration.
- Preserve existing Business resolution, tenant/role/module/subscription/quota/
  location guards, routes, fields, CSRF/retry keys, DOM hooks, drafts, booking
  rules and financial services. Shared files require a recorded consumer/impact
  assessment and relevant states in **both** verticals.
- No ordinary local/staging/production/Test Lab database access or writes,
  customer-data copying, live providers, destructive tests or production-data
  modification. Database tests require independently verified, explicitly
  authorized disposable resources. Applying existing migrations to an empty
  disposable DB also needs explicit scope; schema/migration changes are separate.
- No installations, external-service changes, branch/worktree creation or
  switching, staging, commits, pushes, merges, deployment or cleanup without
  separate explicit authorization. Recommend an isolated worktree for independent
  concurrent features; do not create it automatically.
- Recheck status/target hashes immediately before implementation. Stop on
  overlapping edits, retain unrelated changes and ignored references/evidence.
  Never reset, clean, overwrite approved evidence or silently rebaseline a clash.

The helper only reads local files/Git and writes explicitly requested task
artifacts. It never runs Django, browsers, previews, databases or shell commands
from state. It cannot authenticate a saved approval. Use the
[usage guide](../../../docs/design/motionmate-ui-lab/AUTOMATED-WORKFLOW.md) for
copy-and-paste invocations and the templates in `assets/` for phase evidence.
