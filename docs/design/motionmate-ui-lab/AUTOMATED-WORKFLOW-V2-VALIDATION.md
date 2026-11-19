# Motionmate workflow v2 validation — 19 November 2026

The existing skill was upgraded in place. Full Redesign now uses audit/design
brief → A → exact integration plan/manifest → B → actual working-tree BEFORE,
local implementation and validation → one Django BEFORE/AFTER review → C.
A standalone interactive prototype is optional and requires authorization.
Quick Change retains bounded initial implementation consent without A/C.

New tasks create four core records only. After C, automatic commit preparation
classifies exact files and preserves runtime/reproducibility assets, licenses,
fixture/check source and essential records. Generated exclusions are recorded
without reading/hashing disposable database/log contents or deleting anything.
One commit per accepted redesign is recommended; explicit commit authorization
is still required. The helper never stages, commits, pushes, merges or deploys.

## Modified files

- `.agents/skills/motionmate-ui-workflow/SKILL.md`
- `.agents/skills/motionmate-ui-workflow/agents/openai.yaml`
- `.agents/skills/motionmate-ui-workflow/assets/brief.md`
- `.agents/skills/motionmate-ui-workflow/assets/integration.md`
- `.agents/skills/motionmate-ui-workflow/assets/prototype-review.md`
- `.agents/skills/motionmate-ui-workflow/assets/state.json`
- `.agents/skills/motionmate-ui-workflow/assets/validation.md`
- `.agents/skills/motionmate-ui-workflow/references/stages.md`
- `.agents/skills/motionmate-ui-workflow/references/state.md`
- `.agents/skills/motionmate-ui-workflow/scripts/workflow.py`
- `.agents/skills/motionmate-ui-workflow/scripts/test_workflow.py`
- `docs/design/motionmate-ui-lab/AUTOMATED-WORKFLOW.md`
- `docs/design/motionmate-ui-lab/PREVIEW-WORKFLOW.md`
- `docs/design/motionmate-ui-lab/REPRODUCIBILITY.md`
- `docs/design/motionmate-ui-lab/AUTOMATED-WORKFLOW-V2-VALIDATION.md` (this report)

No ignore rules or dependencies were added. No application source/templates/
assets, migrations, existing workflow records or historical validation reports
were changed. Schema 1 keeps its original phases/digests; no record conversion.

## Offline results

| Check | Result |
| --- | --- |
| Workflow unit suite | 40 passing tests in the checkout and cold source copy; synthetic files/state only. |
| CLI smoke checks | 20 passed expected outcomes: init/check/checkpoint, existing-output refusal, pending A/B, premature commit refusal, read-only Git baseline/preimplementation/resume, rebaseline refusal. |
| Skill metadata validation | Passed skill-creator `quick_validate.py`. |
| Ruff lint/format | Passed for both workflow Python files. |
| Documentation links and diff consistency | Passed for updated skill/docs and templates; `git diff --check` passed. |
| Preservation | 12,867 intake files hashed; only the 14 authorized existing infrastructure/docs files changed. Remaining 12,853 files, including all 179 completed workflow-record files, unchanged. This report is new. |
| Repository historical checker | One existing failure: frozen Step 7 hash for `src/apps/crm/tests.py`; see below. |

The unit suite retains the original 17 schema 1 tests and adds 23 schema 2 tests.
Coverage includes A/B/C ordering, no implementation before B, scope-bound A/B,
real Django AFTER/current candidate requirement, immutable BEFORE/review acceptance,
authorized verified disposable PostgreSQL records, independent clusters and
equivalent synthetic fixtures, optional-prototype consent, Quick Change without
extra gates, missing-runtime disclosure, Services/Logistics isolation and shared
regressions, interrupted checkpoint preservation and drift detection, dirty/
untracked/staged-work protection, exact commit classification, required generated
assets, essential-record protection, unknown-source refusal, unrelated exclusions,
idempotent preparation and refusal to overwrite a changed manifest.

The cold copy contains the skill and four read-only historical document inputs
used by the original synthetic simulation. No Git repository, application runtime
or database was created there. CLI baseline checks read the current repository
but wrote only clearly labeled synthetic state outside it. Synthetic consent and
preview records are test data, never actual approval or evidence of a running app.

Commands:

```sh
.venv/bin/python -B .agents/skills/motionmate-ui-workflow/scripts/test_workflow.py -v
.venv/bin/ruff check --no-cache .agents/skills/motionmate-ui-workflow/scripts
.venv/bin/ruff format --check --no-cache .agents/skills/motionmate-ui-workflow/scripts
.venv/bin/python -B scripts/check_ui_workflow.py
git diff --check
```

Disposable cold-copy, CLI and preservation evidence is outside Git at
`/tmp/motionmate-workflow-v2-8jubgt3f/`. This directory is local temporary evidence,
not a runtime or fresh-checkout dependency. Tests regenerate their synthetic state
using the maintained test script. No standalone UI Lab, browser output, generated
build or database was created for this upgrade.

## Remaining limitations

The repository-wide checker reports `Approved Step 7 source changed:
src/apps/crm/tests.py`. Its current SHA-256 equals the pre-upgrade intake hash
`90c6365e6ee3099e07a43135a33a1890b2a1b14dd66048b0b04a2b46199b8399`;
the historical manifest expects
`c4fc60270a62cb107c707bcb5af55d2fc1a453d957093ca19c9673d47280301f`.
Neither the file nor its preservation metadata was changed to hide this finding.

Validation was intentionally limited to synthetic workflow state and offline
checks. No Django/browser/PostgreSQL runtime behavior, ordinary database or live
provider was exercised. The helper checks recorded consistency; real consent
authenticity, live PostgreSQL ownership and actual browser behavior still require
agent review and the existing preview guards during separately authorized tasks.

Commit preparation requires the conventional repository task directory; external
`--output` remains useful for simulations. Existing optional UI Lab tools can
hardcode in-tree output; v2 documents external output or a narrow new-task ignore
without changing those tools or completed evidence. Ignored reference protection
and ambiguous dependency ownership still need source/consumer inspection.
