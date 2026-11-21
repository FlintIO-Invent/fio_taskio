# Commit preparation

Gate C acceptance authorizes preparation of an exact file selection, not staging
or committing. One commit per accepted redesign is recommended. Application and
test source remains exactly the accepted candidate; only workflow acceptance and
packaging documentation changes now.

The original protected-workspace baseline is retained. This is a per-module file
selection: subsequent independently authorized sibling acceptance documentation
can trigger the helper's broad workspace guard. Reconcile the disjoint ownership
and accepted source hashes; do not overwrite a baseline or weaken the guard.

Runtime CSS and all fixture/check sources are included. Existing tracked Manrope
WOFF2 and OFL files are reused unchanged. Only selected durable screenshots are
included; raw browser output, logs, database/session directories and caches stay
outside the selection and are not deleted. No new dependency or database work.

## Explicit peer-workstream reconciliation

The stock `prepare-commit` command was run and refused the broad protected-
workspace mismatch. [Exact diagnostic and ownership audit](commit-preparation-verification.json)
shows that every delta belongs to another approved source manifest or workflow
directory. All 62 candidate hashes, three approved design/integration identities,
branch/HEAD and empty index were verified. There is no source overlap or unowned
change. The original baseline objects remain intact.

`commit-manifest.json` is an independently prepared exact selection with explicit
provenance. It is **not a successful stock-helper result**. No helper was patched,
mocked or bypassed. The source candidate, accepted review and original proof are
unchanged. This resolves file ownership for a reviewable handoff while preserving
the helper warning; future Git operations require explicit authorization and
fresh hash/ownership checks. No tests or disposable environments were rerun.
