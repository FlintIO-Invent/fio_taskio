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
