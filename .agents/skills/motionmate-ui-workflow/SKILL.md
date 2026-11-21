---
name: motionmate-ui-workflow
description: Run and resume Motionmate UI work with Quick Change or Full Redesign modes, persistent task state, scoped approval gates and real Django BEFORE/AFTER review. Use for Services, Logistics or shared-platform UI workflow requests; excludes backend-only work and standalone websites.
metadata:
  version: "2"
---

# Motionmate UI workflow v2

Use the existing workflow and preview tools; retain Phoenix 1.23.0 and the two
verticals' business contracts. Read repository `AGENTS.md` and the sibling
[motionmate-ui skill](../motionmate-ui/SKILL.md). This skill adds orchestration,
not runtime permission. Explicit read-only audits remain response-only unless
saved documentation/state is authorized.

## Start or resume

1. Establish **mode, vertical, actual route, outcome and authorization** from the
   request and source. Inspect branch/status and existing edits. Open IDE tabs
   alone do not authorize edits.
2. Choose **Quick Change** for a bounded repair/copy/layout change, **Full
   Redesign** for a screen/journey. Planning-only work stays planning-only.
3. For authorized artifacts, initialize one new task using the offline helper.
   Read [stages](references/stages.md) and [state/resume rules](references/state.md).
   Checkpoint after each phase and before each gate; never initialize over a task.
4. Resume with state, artifact/target hashes, branch/status and latest actual user
   authorization. Reuse verified approvals within their exact scope. State and
   synthetic test approvals are never consent.

```sh
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py init \
  --task services-example --vertical SERVICE --mode full --route /appointments/ \
  --objective 'Describe the screen improvement'
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py checkpoint \
  docs/design/motionmate-ui-lab/workflows/services-example/state.json
```

New records use schema 2. Schema 1 retains its original phases/digests; do not
migrate or rewrite completed approvals, manifests, evidence or accepted candidates.

## Quick Change

Audit affected components/contracts and shared consumers. Prepare a concise plan
and exact manifest. **Implement only when the initial request or a later explicit
instruction authorizes this bounded repair.** Record that instruction against the
manifest; do not ask for a second authorization when it already covers the work.
Otherwise stop after the plan. No prototype or separate Gate A/C ceremony.

Preserve BEFORE with existing authorized resources, implement the scoped repair,
run proportionate checks and report. Do not add tests for trivial markup/copy.
Missing runtime permission allows independent source work, not implicit setup;
record blocked browser evidence honestly. PDF changes need relevant rendering.

## Full Redesign

1. Automatically audit the actual Django functionality, contracts and consumers.
2. Prepare the design brief and proposed screen improvements using existing
   Motionmate references and Phoenix integration constraints.
3. **Gate A — design direction:** present a specific version and hashed brief/
   design artifacts, proposed interactions and deferred functional decisions.
   Stop for explicit approval. No interactive prototype is required.
4. After A, automatically prepare the exact production integration plan, closed
   file manifest, consumer/impact assessment, risks and validation resources.
   Capture working-tree and file baselines before presenting them.
5. **Gate B — implementation:** stop for explicit authorization of that manifest
   and applicable verified disposable PostgreSQL resources. A is not B.
6. After B, freeze the actual working-tree BEFORE before edits, implement only
   approved files locally, and use authorized synthetic fixtures/environments.
7. Validate actual Django forms, routes, authentication and permissions, backend
   contracts, responsive themes, accessibility and affected regressions.
8. Refresh AFTER alone and present **one real interactive Django BEFORE/AFTER
   review**, with equivalent initial synthetic records and recorded identities.
9. **Gate C — final acceptance:** present real URLs, candidate/source/fixture
   hashes, representative evidence and limitations. Stop for explicit acceptance.

Do not generate a standalone interactive UI Lab by default. Use one only when
explicitly requested, or when a major design uncertainty is explained and the
exploration is authorized. Record its reason/authorization; it neither adds a
mandatory phase nor replaces the real Django review. Retain existing references.

Fix and revalidate within approved scope without repeated approvals. A material
scope/design expansion needs a concrete revised proposal; stop dependent work.
Missing real preview capability keeps Full Redesign validation/review pending;
source checks or a prototype cannot substitute for it.

## After Gate C

Automatically identify task-owned implementation, tests, documentation, required
assets and generated artifacts. Run `prepare-commit STATE` to prepare the exact
hash-bound selection; resolve ownership gaps and verify concurrent edits first.
Recommend **one commit per accepted redesign**. Include runtime assets, licenses,
fixture/tool source and reproducibility dependencies. Exclude unnecessary builds,
logs, caches, databases and redundant captures without deleting them.

Commit preparation is authorized workflow documentation. **A commit still needs
explicit user authorization. Never automatically stage, commit, push, merge or
deploy.** No cleanup follows acceptance.

## Permanent boundaries

- SERVICE, LOGISTICS or explicitly authorized SHARED scope only. Services design
  approval never covers Logistics. Shared consumers need impact and regression
  evidence in both verticals; retain distinct workflows/permissions. Tailwind/
  DaisyUI stay optional lab references, never a production framework migration.
- Preserve Business resolution, tenant/role/module/subscription/quota/location
  guards, routes/fields/CSRF/retry keys/DOM hooks, drafts, booking rules, financial
  logic and data unless separately authorized.
- Use only independently verified, explicitly authorized **disposable PostgreSQL**
  for data-writing tests/previews. No ordinary local/staging/production/Test Lab
  database access, migrations or writes; no customer-data copying or live providers.
  Existing migrations on empty disposable databases need explicit runtime scope.
  Schema/migration changes remain separate authorization.
- No destructive operations, dependencies, external-service changes, branch/
  worktree creation/switching, Git release actions or cleanup by implication.
- Recheck branch/status and target hashes immediately before implementation and
  at resume. Checkpoint partial edits; stop on overlap/drift, retain unrelated
  work and ignored references/evidence. Never reset, clean or silently rebaseline.
- Keep durable audit/design/approval/test summaries; use representative screenshots.
  Put disposable browser output, logs, builds and databases outside Git where
  practical. Use only task-specific ignores if a tool cannot do so. Never alter
  historical evidence or ignore a required runtime/reproducibility asset.

The helper is offline: local files and read-only Git only. It never runs Django,
browsers, databases, commands from state or release operations, and cannot verify
consent authenticity or live database ownership. See the
[usage guide](../../../docs/design/motionmate-ui-lab/AUTOMATED-WORKFLOW.md).
