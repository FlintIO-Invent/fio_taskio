# Durable task state

Each authorized task owns
`docs/design/motionmate-ui-lab/workflows/<task-id>/state.json` and four Markdown
reports copied from `assets/`. Keep evidence there or link to retained owned
preview resources. This is project workflow state, not Codex memory. Store no
credentials, cookies, ordinary database URLs or customer data. Do not edit old
approval records/reports when starting a new task.

`state.json` uses standard JSON, readable without extra packages. The template
defines the fields; preserve unknown task metadata when editing. Required data:

- Identifier, SERVICE/LOGISTICS/SHARED, quick/full, actual route and objective.
- Ordered completed phases, derived current phase and next permitted action.
- Design version and a map of versioned artifact paths to SHA-256 hashes.
- A closed implementation manifest: path, add/modify, purpose, shared impact,
  shared regression plan and baseline hash (`null` for absent additions).
- Design/implementation/acceptance approvals, each with the actual user quote,
  source reference and explicit scope. Design binds version/artifact digest;
  implementation binds design version/manifest digest; acceptance binds candidate
  digest. `null` means pending. A synthetic record is never user consent.
- Baseline branch/HEAD/status and manifest hashes, deferred decisions, known
  issues, resource authorizations and validation results/evidence.
- Per-phase evidence with `kind`, `reference` and `summary`. Reference a local
  report or retained source/session identity; never claim an absent artifact ran.

Approval evidence shape (fill only from a real user instruction):

```json
{
  "source": "conversation message or retained approval reference",
  "quote": "Exact relevant user instruction",
  "scope": "Concrete authorized presentation scope and exclusions",
  "design_version": "v1",
  "design_sha256": "digest emitted by check for Gate A"
}
```

Gate B uses `manifest_sha256` instead of `design_sha256`; Gate C uses
`candidate_sha256`. Quick Change B has `design_version: null`. The helper never
creates approvals or verifies a quote's authenticity. The agent must compare
them with the session/latest user instruction; a saved quote cannot override a
later revocation or an audit-only request. Do not copy synthetic test consent.

## Commands

From the repository root, prefix with
`.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py`:

| Command | Effects |
| --- | --- |
| `init --task ID --vertical SERVICE --mode quick --route /path/ --objective TEXT` | Create a new task with pending approvals and reports; refuse existing output. Optional `--output DIRECTORY` selects an owned task directory. |
| `baseline STATE` | Save branch/HEAD/status and target hashes before B. Refuse after implementation consent/completion; never silently rebaseline concurrent edits. |
| `check STATE` | Offline structural, phase-order, approval-binding and artifact checks; emit computed phase, gate and digests. No writes. A pending gate is valid state, not failure. |
| `check STATE --pre-implementation` | Also require B, a baseline, matching branch/HEAD/target hashes and unchanged Git status. Fail on overlap/drift. Run immediately before editing. |
| `checkpoint STATE` | Run the same validation and save derived phase/action/timestamp. Never advance completed phases or grant consent. |

Edit completed phases/evidence as the agent actually finishes them, then run
`checkpoint`. Full order is audit, brief, prototype, prototype_validation,
integration, before, implementation, validation, comparison, report. A precedes
integration; B precedes before/implementation; C follows report. Quick order is
audit, plan, before, implementation, validation, report; B precedes before.
No full prototype or Gate A/C is required for Quick Change.

Hash consent bindings cover design bytes and the closed manifest. The candidate
digest covers current manifest file bytes after implementation. The checker also
detects unapproved manifest edits, skipped phases and stale accepted candidates.
It is a consistency aid, **not an execution sandbox**: meaningful evidence,
authorizations for runtime resources and unrelated-file preservation still need
agent review. It never imports Django or executes commands found in state.

## Resume verification

1. Read state/reports and the latest instruction. Compare task, route, vertical,
   requested scope, source/fixture identities and actual artifact hashes.
2. Run offline `check`. Recheck Git branch/status and file ownership. Before
   implementation, use `--pre-implementation`. After partial implementation,
   compare the actual diff with the approved manifest and saved checkpoints;
   baseline equality no longer applies to intended edits.
3. Verify saved approvals against actual user evidence and latest scope. If
   evidence is missing, mark it pending and stop at its gate. Do not infer consent
   from a completed phase, tests, elapsed time or an earlier screen's approval.
4. Resume the first incomplete permitted phase. Keep missing runtime evidence
   pending and work only on independent authorized items. Preserve overlapping
   changes; reconcile them explicitly before refreshing a baseline/proposal.

Changed design artifacts require a new design version/A record and a new B
binding; changed manifest requires updated B. Keep superseded approval evidence
in the task report/history instead of erasing it. Candidate changes after C
require acceptance of the updated candidate. No automatic Git action is used.
