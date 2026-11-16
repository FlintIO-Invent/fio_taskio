# Motionmate UI review workflow

**1. Request and scope → 2. Audit actual Django screen → 3. Capture interactive
BEFORE → 4. Design proposal and approval → 5. Scoped implementation →
6. Django/browser/accessibility/regression validation → 7. Interactive AFTER
comparison → 8. Human approval → 9. Separate release authorization.**

Real Django applications are the default for **implementation reviews**.
Optional synthetic prototypes support design exploration; they do not establish
application behavior, persistence, authorization or readiness to release.
Use the [UI skill](../../../.agents/skills/motionmate-ui/SKILL.md) and approved
[design system](../motionmate-design-system/DESIGN.md). Phoenix remains the
application foundation. Design approval and implementation authorization are
separate; release preparation never implies commit, push, migration or deployment.
Services and Logistics remain separate verticals. Never change one while
redesigning the other; shared components require regression checks in both.
Use [fresh-checkout setup](REPRODUCIBILITY.md) before following the commands below.
The [preservation guide](PRESERVATION.md) records essential evidence, the verified
historical baseline and archive restoration. Instructions are not authorization
to install packages, create fixtures, run migrations or clean up resources.

## Request and audit

Identify vertical, actual screen/route, intended improvement, authorized file
scope, workflows, roles, subscriptions, difficult states and unrelated edits to
preserve. Inspect real views/services, templates, forms, JavaScript, assets and
context. Read-only audit work does not authorize fixtures or application edits.

For an implementation review, identify and authorize disposable resources before
writing fixtures. Use the local tooling below; never use an ordinary database,
copy customer data or assume Git HEAD represents the user's working state.
If real application previews cannot run safely, report the missing capability;
do not substitute a prototype and call it a real application review.

## Preserve BEFORE and start a real preview

From the repository root:

```sh
.venv/bin/python scripts/motionmate_preview.py capture
# Save the returned /tmp/motionmate-preview-snapshot-... path as BEFORE_SNAPSHOT.
.venv/bin/python scripts/motionmate_preview.py create \
  --before-snapshot /tmp/motionmate-preview-snapshot-... \
  --route /crm/agent/dashboard/
```

The command returns a session directory and three loopback URLs. The launcher
links to two actual Django apps. BEFORE uses the captured source; AFTER initially
uses the current source. Both can be identical before implementation. Captures
include uncommitted/untracked runtime source, templates and static assets as
independent copies. They exclude `.env`, uploaded media, databases, logs, caches,
Git internals, collected output and the synthetic lab runtime. Source hashes are
verified before launch. Existing working-tree files are never reset or replaced.

Each side has a new PostgreSQL cluster and its own database, directory, port,
system identifier and synthetic fixtures. The tool verifies ownership, on-disk
identity, live listener/process and PostgreSQL identity before commands, and
rechecks every Django database connection. Migrations apply only there.
No ordinary database or data dump is used.

Login uses the application's real form and CSRF. The launcher lists local-only
accounts/passwords. Separate session/CSRF/language cookie names, session-backed
messages, databases and port-separated browser storage permit simultaneous tabs.
Real appointments, bookings, lists, menus, themes and setup forms use the frozen
application code. Financial writes/provider routes are intentionally unavailable;
email is in-memory. See the [Step 8 operations/report](08-real-application-preview.md)
for the network boundary, current runtime workaround and limitations.

## Implement, refresh AFTER and compare

Before implementation, present the proposed design, exact scope, workflow
contracts and validation plan for human approval. Reuse an approval already
given for that scope. Synthetic prototypes are optional references for this
decision; the implementation review uses real Django applications.

Only implement the separately authorized application changes. Running snapshots
do not follow working-tree edits. After implementation:

```sh
.venv/bin/python scripts/motionmate_preview.py refresh-after \
  --session /tmp/motionmate-preview-session-...
# Run the authorized Django/browser/accessibility/regression checks before review.
.venv/bin/python scripts/motionmate_preview.py validate \
  --session /tmp/motionmate-preview-session-...
```

Refresh creates another source copy and restarts AFTER only. BEFORE remains
immutable. Database/session contents persist; refresh refuses changed migration
sources and performs no schema work. This is a UI workflow, not a schema rollout.

Fixtures match at creation; interactive writes remain on their respective side.
They are not silently synchronized or reset. To compare freshly matched data,
stop the old pair and create a new pair using the saved BEFORE snapshot and
current AFTER source. App clocks remain real; appointments/grace states age.
The dedicated validation account may be modified by form checks; review accounts
remain available for human use.

The built-in validator exercises the Services dashboard, role/state accounts,
real login and onboarding, destinations, cookie/CSRF isolation, responsive themes,
other Services/Logistics content and independent restart. Extend its fixture
adapter and checks for a future affected screen; do not invent synthetic business
rules or infer new policies from a test fixture. Verify actual server-rendered
forms, route/query/field/CSRF contracts, role/module/subscription behavior, money,
business-local times, keyboard/focus, empty/error/restricted states and both
verticals where shared sources are touched. Retain raw failures and limitations.
For the retained Step 7 Django/static and axe/Chromium checks, use the portable
`check-dashboard` command described in [setup](REPRODUCIBILITY.md#validation).
Those checks create a disposable Django test database; obtain authorization first.

Review real URLs at desktop/tablet/mobile in both themes. Screenshots supplement
these functional applications. Approve an identifiable source revision and
fixture context, not just an image. Stop for human review; release preparation
and ordinary-runtime/provider/static deployment verification remain separate.
Final human UI approval is step 8. Explicit approval for staging/commit/push/
merge/deployment is a separate step 9; no release action follows automatically.

## Start, stop and remove disposable resources

```sh
.venv/bin/python scripts/motionmate_preview.py status --session SESSION_PATH
.venv/bin/python scripts/motionmate_preview.py stop --session SESSION_PATH
.venv/bin/python scripts/motionmate_preview.py start --session SESSION_PATH
# Optional independent side: add --side before or --side after.
.venv/bin/python scripts/motionmate_preview.py cleanup \
  --session SESSION_PATH --confirm EXACT_SESSION_ID
```

Stop affects only verified owned preview processes/clusters. Cleanup requires
both sides stopped and the exact session ID; it removes only that owned temporary
session, including its synthetic data and snapshots. Do not remove it while it is
still the only saved BEFORE/evidence. Captured source snapshots are independent
owned directories; retain them until the review and release handoff are complete.
No destructive Git operation, ordinary-database migration or release hook belongs
in this workflow.

## Optional prototype exploration

The separate [UI Lab](../../../ui-lab/README.md) is clearly a **prototype**.
Its Step 4 dashboard, Step 5 Appointments composition, pinned Tailwind/DaisyUI
tools, shared tokens/components, synthetic states and frozen evidence remain.
Use `ui-lab/<screen>/` and `previews.json` for design experiments, the existing
build/capture tools and prototype launcher for visual exploration. Its actions
and forms are simulations. Preserve approved references rather than rebuilding
them. Prototype approval never authorizes application changes; bind the approved
direction to real Django behavior under a separately approved implementation
scope and review the real BEFORE/AFTER pair.
