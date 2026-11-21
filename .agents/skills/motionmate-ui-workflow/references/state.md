# Durable state, artifacts and resume

New tasks use **schema_version 2**. Their conventional directory is
`docs/design/motionmate-ui-lab/workflows/<task-id>/`. Initialization creates only
`state.json`, `brief.md`, `integration.md`, `validation.md`. No prototype package,
prototype report, build, screenshots or database is created. Save concise audit,
design, approval and test records there. Store no credentials, cookies, connection
strings or customer data. External disposable output is referenced, not copied in.

## Compatibility

Schema 1 remains readable with its original phase order and digest calculations.
Never automatically convert it, recalculate old approvals, rewrite completed
records, or force historical evidence to satisfy v2. Missing archived evidence
is a disclosed limitation, not permission to remove a hash or invent a pass.
Unknown task metadata is preserved by checkpoint. New v2 commit preparation is
for new tasks; historical accepted candidates and packaging stay frozen.

## Phases and bindings

Full: `audit, brief, integration, before, implementation, validation, comparison,
report`. A precedes integration, B precedes before/implementation, C follows
report. Optional prototypes add no required phase. After C, automatically prepare
the commit manifest as a documentation handoff, with no further implementation.

Quick: `audit, plan, before, implementation, validation, report`. Implementation
consent may be the initial bounded request; no extra approval prompt, A or C.
A missing runtime can be disclosed as blocked validation for Quick Change.

Each completed phase needs evidence objects with `kind`, `reference`, `summary`.
Never mark an unperformed check passed. Results use `check`, `status` (`pass`,
`fail`, `blocked`, `not_applicable`), `evidence`, and `limitation` for nonpasses.
Shared changes require passing regression evidence tagged with `vertical` for
SERVICE and LOGISTICS before Full Redesign comparison can complete.

- `design_version`, `design_artifacts`: immutable exact repository paths → SHA-256
  for the brief and any actual design records. V2 A binds task/vertical/route/
  objective plus design bytes; Services approval cannot become Logistics approval.
- `manifest`: exact `path`, `action` (add/modify), `purpose`, `category`, `vertical`,
  `shared` boolean, `before_sha256` (null for additions). Shared entries use
  `vertical: SHARED`, `shared_impact`, `shared_regression`, and
  `regression_verticals: [SERVICE, LOGISTICS]`; other entries match task vertical.
- `approvals`: design/implementation/acceptance or null. Each actual user record
  has `source`, exact `quote`, `scope`. A adds `design_version`, `design_sha256`;
  B adds `design_version` (null for Quick), `manifest_sha256`; C adds
  `candidate_sha256` and `review_sha256`. C binds the real preview/environment/
  validation identities as well as candidate bytes. Use digests returned by
  `check`, not fabricated values.
  Saved quotes are consistency records; verify actual consent and later revocation.
- `optional_prototype`: defaults to `enabled: false`. Enabling needs a `reason`
  (explicit request or major design uncertainty) and `authorization` with actual
  source/quote/scope. An authorized prototype cannot substitute for Django review.
- `baseline`: branch/HEAD/status; `protected_workspace`: status and hashes for
  unrelated dirty/untracked files plus a staged-diff digest, captured by baseline.
  Approved files and the
  conventional task directory are separately scoped. Do not edit these baselines
  to conceal concurrent changes. `implementation_checkpoint` saves exact approved
  file hashes during partial work; `before_identity_sha256` freezes the actual
  BEFORE record at its first checkpoint. Ignored references still need agent
  protection.

## Real Django review record

Full Redesign cannot complete `before` without actual Django identity and cannot
complete `comparison` without AFTER identifying the current candidate. The shape
below documents keys, not evidence that anything ran:

```json
{
  "kind": "django",
  "vertical": "SERVICE",
  "synthetic_records": true,
  "contracts": ["templates", "routes", "authentication", "forms", "permissions"],
  "before": {
    "url": "http://127.0.0.1:8781/actual-route/",
    "source_sha256": "record the actual source digest",
    "initial_fixture_sha256": "record the initial canonical fixture digest",
    "environment_id": "owned-before"
  },
  "after": {
    "url": "http://127.0.0.1:8782/actual-route/",
    "source_sha256": "record the actual refreshed source digest",
    "initial_fixture_sha256": "same initial canonical fixture digest",
    "environment_id": "owned-after",
    "candidate_sha256": "current check output"
  }
}
```

Each `environments` entry identifies `id`, `engine: postgresql`, `disposable: true`,
`ownership_verified: true`, `settings`, sanitized `database`, `cluster_directory`,
`system_identifier`, `port`, `process`, `identity_evidence`. BEFORE/AFTER use
independent clusters and URLs. Each ID needs a `resource_authorizations` record
with `environment_id`, actual source/quote/scope. Verify live ownership using the
existing preview guards; booleans and test-looking names are not live proof.
The helper only checks record consistency. No ordinary database is accessed.

Preserve BEFORE identity and equivalent initial fixtures; review writes diverge
independently. No automatic reset, reseed or historical-baseline substitution.

## Artifact and commit classification

`artifact_inventory` supplements the implementation manifest and auto-discovered
task/design records. Each entry has an exact `path`, `category`, `purpose` and
`ownership` (`task` or `unrelated`). Never claim concurrent files as task-owned.

| Category | Commit treatment |
| --- | --- |
| `implementation` | Include approved application/fixture/tool source. |
| `tests` | Include reproducible test/check source. |
| `documentation` | Include essential audit, design, approvals, test summaries and selected representative screenshots. |
| `required_asset` | Include runtime fonts/images/CSS/bundles, licenses and reproducibility assets even when generated. |
| `generated` | Exclude unnecessary browser output, logs, caches, temporary databases, redundant captures and rebuildable lab output. Never delete it automatically. |

Required asset status takes precedence over a generated filename or origin.
Do not classify served application assets as disposable. Manifest classifications
cannot be changed through inventory after acceptance. Use inventory to select
representative screenshots and record required dependencies explicitly.
External absolute paths are allowed only for excluded generated artifacts.
Repository paths must be exact, without traversal, wildcards or symlinks.

`prepare-commit STATE` runs only after v2 Full Redesign C acceptance. It verifies
candidate/checkpoint/concurrent-work consistency, gathers the accepted manifest,
design artifacts and task directory, applies explicit inventory, and writes one
`commit-manifest.json` containing exact paths/categories/hashes and exclusions.
Unknown source/binary task files require classification. Pre-existing unrelated
edits remain outside the selection. Newly changed files outside approved scope
block preparation rather than being silently included. The manifest includes its
own path as a self descriptor without a self hash. It does not rewrite state or
accepted artifacts. Repetition is idempotent; differing existing output requires
reconciliation. Recommend one commit per completed redesign, then wait for explicit
commit authorization. No Git mutation, push, merge, deployment or cleanup occurs.

## Commands and resume

Prefix commands with
`.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/workflow.py`.

| Command | Effects |
| --- | --- |
| `init --task ID --vertical SERVICE --mode full --route /path/ --objective TEXT` | New pending schema 2 task; refuse existing output. `--output DIRECTORY` supports external synthetic simulations. |
| `baseline STATE` | Save Git/target/protected-file baselines before B; refuse rebaseline or approved implementation. |
| `check STATE` | Read-only structure, hashes, phase order, approval bindings and scope checks. Pending gates return 0; stale/invalid state fails. |
| `check STATE --pre-implementation` | Require B, matching initial Git and target baselines; run immediately before edits. |
| `check STATE --resume` | Also require approved target hashes to match the last implementation checkpoint, or original baseline if none. |
| `checkpoint STATE` | Atomically save derived phase/action/time and approved target hashes after reviewed progress. Does not complete phases or grant consent. |
| `prepare-commit STATE` | After C, write only the exact reviewable commit manifest. No staging/commit. Requires conventional repository task directory. |

On resume read latest instructions, state and evidence; run `check --resume`,
check branch/status, artifact hashes, ownership and preview identities. Reuse
verified approvals; continue the first incomplete authorized phase. Investigate
drift before checkpointing: a new checkpoint must not bless unexplained edits.
Never overwrite accepted work or silently rebaseline. Custom task output inside
Git is not automatically excluded from status; use the conventional directory
or external output. Commit preparation requires the conventional directory.

Changes to design bytes/scope need renewed A and B bindings; manifest expansions
need updated B. Keep superseded approval history. Candidate changes after C need
acceptance of the new candidate. The helper is a consistency aid, not an execution
sandbox or authority to authenticate user consent or live resources.
