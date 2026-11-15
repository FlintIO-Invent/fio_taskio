# Phase 2 — reproducible local UI workflow

15 November 2026. Local tooling/documentation/preservation implementation only.
No application presentation/business logic, configuration, models, migrations or
ordinary data changed. No staging, commit, push, merge, deployment or cleanup ran.
The Phase 1 audit in the conversation established the starting state: branch
`experiment/motionmate-ui-redesign`, no upstream, five tracked modifications,
1,396 untracked files and no staged files.

## Files changed in Phase 2

The following pre-existing files were edited, preserving their earlier work:

```text
.gitignore
AGENTS.md
pyproject.toml
uv.lock
.agents/skills/motionmate-ui/SKILL.md
scripts/ui_preview/cli.py
scripts/ui_preview/core.py
scripts/ui_preview/validate.py
ui-lab/.gitignore
ui-lab/README.md
ui-lab/services-dashboard/daisyui/README.md
ui-lab/services-dashboard/daisyui/tools/validate_refinement.py
ui-lab/services-dashboard/tools/validate.py
docs/design/motionmate-ui-lab/01-audit.md
docs/design/motionmate-ui-lab/02-design-brief.md
docs/design/motionmate-ui-lab/03-prototype-comparison.md
docs/design/motionmate-ui-lab/04-daisyui-refinement.md
docs/design/motionmate-ui-lab/05-design-system-and-workflow.md
docs/design/motionmate-ui-lab/06-production-integration-audit.md
docs/design/motionmate-ui-lab/07-services-dashboard-integration.md
docs/design/motionmate-ui-lab/08-real-application-preview.md
docs/design/motionmate-ui-lab/PREVIEW-WORKFLOW.md
```

New files:

```text
scripts/archive_ui_history.py
scripts/check_ui_workflow.py
scripts/ui_preview/dashboard_checks.py
docs/design/motionmate-ui-lab/REPRODUCIBILITY.md
docs/design/motionmate-ui-lab/PRESERVATION.md
docs/design/motionmate-ui-lab/09-reproducibility-and-preservation.md
docs/design/motionmate-ui-lab/essential-screenshots.json
docs/design/motionmate-ui-lab/preservation-manifest.json
docs/design/motionmate-ui-lab/staging-manifest.txt
```

Twelve new PNGs are copied byte-for-byte to `screenshots/real-django/`; their
exact names, hashes and provenance are in [essential-screenshots.json](essential-screenshots.json).
The six original Step 4 comparison PNGs remain in place and are also in that manifest.

## Reproducibility changes

- Instructions now specify the same nine-step request/audit/interactive BEFORE/
  proposal approval/implementation/validation/interactive AFTER/human approval/
  separate release authorization sequence. Both verticals retain their own
  workflow and permissions; shared components require both verticals' regressions.
- The optional Python UI extra declares and locks Playwright 1.63.0, with pyee
  13.0.1 and greenlet 3.5.6. All previously locked package versions are unchanged.
  Production dependencies
  and Phoenix assets are unchanged; no production Tailwind/DaisyUI dependency was added.
- Browser selection uses `PWA_CHROMIUM` or Playwright's installed browser; user-specific
  executable paths were removed from active validators and setup commands.
- `capture --git-ref` reads local Git runtime blobs without checkout/reset.
  The verified original runtime commit is
  `34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c`; 6,749 selected paths match the saved original.
- `check-dashboard` supplies a portable, guarded Step 7 runner using an owned
  preview cluster and sanitized child environment. Optional browser mode runs
  original-view/template baseline then current dashboard/axe comparisons.
- The runbook documents Linux/PostgreSQL, Chromium selection/install, optional
  npm tools, authorization boundaries, lifecycle, comparison and fixture aging.
  Phoenix reference acquisition remains licensed, read-only and excluded from Git.
- Historical approval wording is annotated/corrected. Original historical test
  results and existing failures remain distinguished from Phase 2 verification.
- Ignore rules expose only the reusable UI skill files and preserve essential
  screenshots while keeping full historical evidence local. No originals were removed.

## Evidence and proposed staging

The [preservation guide](PRESERVATION.md) records the external archive and safe
restoration instructions. Its 1,856 content files, hashes and four gallery link
graphs were verified without extraction. No missing gallery targets were found.
The duplicate screenshot ZIP, credentials/session files, databases, raw logs,
launcher screenshot and failed captures are excluded. Source originals remain.

The [exact proposed Git manifest](staging-manifest.txt) includes source, instructions,
dependency metadata, frozen references and 18 essential screenshots. Nothing was
staged. The two formerly ignored skill files are now visible without force-add.

## Validation and permission boundary

Static source/AST/lint, CLI help, documentation/skill links, ignore exceptions,
source/screenshot availability, approved Step 7 hashes and frozen Step 4 hashes
were checked. Eleven Step 7 source files and 22 frozen reference files match the
preservation hashes. Archive verification checked all 1,856 content-file hashes.

**Dependency lock resolved:** the user approved metadata-only network resolution
after the offline attempt lacked the required cached metadata. The command
`uv lock --no-python-downloads --no-build --python .venv/bin/python` added only
Playwright 1.63.0, pyee 13.0.1 and greenlet 3.5.6. No existing package version or
artifact record changed; the project's own record now includes the optional UI
extra. No package/browser installation or environment synchronization occurred.

The subsequent offline lock consistency check passed:
`uv lock --check --offline --no-python-downloads --no-build --python .venv/bin/python`.
`check_ui_workflow.py` also passed with zero failures across the 147 proposed
files, 18 essential screenshots, 11 protected Step 7 source files, 22 frozen
reference files and documentation/skill links. The 106 historical evidence link
targets are intentionally supplied by the separate archive. Tracked-diff
whitespace checks passed and the Git staging area remains empty.

No disposable database, fixtures, migrations, browser run, temporary-file unit
suite or fresh environment installation was executed. The new Git capture/test
runner paths have static verification only and require separately authorized
runtime checks. Existing Step 7 suite failures and the debug-allocator runtime
workaround remain; this task does not establish release/provider readiness.

Stop for review. Phase 3 and any release action require explicit approval.
