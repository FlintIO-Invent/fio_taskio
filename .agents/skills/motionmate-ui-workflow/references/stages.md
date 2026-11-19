# v2 phases and existing tools

Use the [preview workflow](../../../../docs/design/motionmate-ui-lab/PREVIEW-WORKFLOW.md)
and [setup](../../../../docs/design/motionmate-ui-lab/REPRODUCIBILITY.md). Commands
and historical runs grant no runtime permission. Read only relevant domain docs.

## Audit, brief and Gate A

Trace route → Business resolver/guards → view/service → form/model → templates/
assets and downstream effects. Inspect scripts before running them: some GETs
write data. Record existing contracts, shared consumers, unrelated edits and
known failures. Audit actual functionality automatically within authorization;
source findings and browser observations must remain distinct.

Use `brief.md` for the audit and versioned proposed improvements: hierarchy,
composition, controls, mobile behavior, themes, accessible interaction and the
actual workflow problem each change addresses. Consult approved design references
and read-only Phoenix examples. Defer finance/server/permission policy decisions.

At Gate A present the hashed brief/design direction and decisions for review.
A design brief is sufficient; do not build a duplicate interactive prototype.
If a user requests exploration, or authorizes a justified major uncertainty,
record `optional_prototype` and use `prototype-review.md` only then. Existing
UI Lab tools write into their package by default: inspect them and obtain the
exact scope before use; prefer an owned external build/output directory when
supported. Never rerun into historical evidence. Prototypes remain optional.

Quick Change uses `audit → plan`. Bind an already explicit repair request to the
exact manifest without a new approval prompt; otherwise stop at the plan.

## Integration and Gate B

After A automatically fill `integration.md`: exact paths/actions/categories,
vertical and shared impact, compatibility, risks, preserved contracts, excluded
files and validation plan. Include required runtime assets/licenses, tests and
fixture/check source. No wildcards or implicit follow-on files. Identify the
specific disposable PostgreSQL resources/actions and whether existing migrations
will be applied there. No ordinary databases, provider activity or schema changes.

Run `baseline STATE` before B to save branch/HEAD/status, target hashes and the
protected dirty-file baseline. Review ownership of pre-existing edits. B binds
this manifest/design and actual resource authorization. Design approval alone
cannot authorize implementation. Never silently rebaseline a clash.

## BEFORE, implementation and validation

Immediately before edits run `check STATE --pre-implementation`. Capture actual
working-tree bytes, including approved uncommitted/untracked runtime sources;
HEAD is not the baseline. Follow existing ownership-checked tooling only under
explicit disposable-runtime permission:

```sh
.venv/bin/python -B scripts/motionmate_preview.py capture
.venv/bin/python -B scripts/motionmate_preview.py create \
  --before-snapshot BEFORE_SNAPSHOT --route ACTUAL_ROUTE
# After scoped implementation:
.venv/bin/python -B scripts/motionmate_preview.py refresh-after --session SESSION_PATH
```

One pair is the review. Preserve BEFORE; refresh AFTER alone. Record actual
settings, sanitized database/owner, cluster directory/system identifier, port/
process, source/session identities and ownership proof for both sides. Do not
load ordinary `.env`, secrets, uploads or customer records. Disable providers,
email and workers; use distinct session/CSRF cookies. Equivalent initial synthetic
fixtures support comparison; later review writes persist independently. Never
reset/reseed them silently. No new schema/migration sources in this workflow.

`motionmate_preview.py validate` and `check-dashboard` target dashboard contracts;
`--route` changes the launch destination, not the validator. Inspect existing
screen adapters under `scripts/ui_preview/` (including Appointments, Clients and
Invoices) for guards, contracts and side effects. New adapters belong in B's
manifest. Do not weaken ownership, network or financial guards.

Use `validation.md` for actual POST/CSRF/retry/draft/navigation behavior and
permitted/restricted roles, modules, subscriptions, quotas and Logistics locations.
Shared files require both verticals; a scoped shared consumer must also prove the
other vertical unchanged. Check relevant PDF/email outputs, authoritative values
and forms. Keep static, isolated backend, real Django/browser, manual and provider
evidence distinct. Runtime workarounds do not establish ordinary-runtime health.

Exercise representative desktop/tablet/mobile widths (e.g. 1440/768/390), light/
dark, long/empty/error/loading/restricted states, keyboard/focus/labels/contrast/
touch targets and reduced motion; add 320px reflow/RTL/zoom where relevant.
Validation coverage is not a screenshot count. Save a small representative set
and exceptional failure evidence; use compact results for other cases, not a
full screenshot matrix. Keep meaningful initial failures and axe incompletes.
Repair in-scope failures and rerun affected checks only.

Keep logs, browser output, temporary source/builds and databases in the verified
owned session or external temporary task directory. Existing tools may hardcode
output paths: record that limitation and use a narrow new-task ignore only when
necessary, preserving required source/assets and historical evidence.

Checkpoint partial implementation and verify `check STATE --resume` before
continuing. Missing permission/tooling leaves Full Redesign review pending; do
independent authorized work and report the gap. Quick repairs may report focused
source checks with a disclosed blocked browser result, without adding A/C.

## Gate C and commit preparation

Present one actual interactive Django BEFORE/AFTER pair, immutable sources,
matching initial fixtures, current candidate, representative evidence and limits.
Stop for C; passing tests are not acceptance. Keep resources available.

After explicit C acceptance, automatically classify task files, dependencies and
disposable output, verify the accepted hashes and generate `prepare-commit STATE`.
Resolve any ownership gap/concurrent edit before proposing the exact selection.
One completed redesign should normally have one commit. The helper never stages
or commits; explicit commit authorization is separate. Do not reopen completed
v1 redesigns or revise their historical packaging. No automatic cleanup/release.
