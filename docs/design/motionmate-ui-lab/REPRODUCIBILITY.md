# Reproduce Motionmate UI reviews

This is the setup/runbook for a new developer or Codex session. Follow
[AGENTS.md](../../../AGENTS.md), the [UI skill](../../../.agents/skills/motionmate-ui/SKILL.md)
and the [nine-step workflow](PREVIEW-WORKFLOW.md). Services and Logistics stay
separate; shared template/component changes require both verticals' regressions.
Phoenix 1.23.0 remains the production UI. Tailwind/DaisyUI are lab-only tools.

## Authorization boundary

Read-only source checks need no database. Installation changes the local
environment and may access the network; browser runs write evidence; captures
write temporary source copies; preview creation initializes new PostgreSQL
clusters and applies existing migrations only inside them. Obtain authorization
for the relevant actions before execution. Never connect to ordinary local,
staging, production or Test Lab databases. Do not run release/build hooks.
Nothing here authorizes staging, commits, pushes, merges, deployment or cleanup.

## Linux and tool prerequisites

- Linux with `/proc`, a non-root Unix account and private writable temporary
  storage. Ownership/process verification uses `/proc`, `pwd` and `os.getuid()`;
  this launcher is not a Windows/macOS-compatible process manager.
- Python 3.12 (the project's `.python-version`) and `uv`; existing application
  dependencies are locked in `uv.lock`. Phase 1 observed Django 5.2.11,
  Playwright 1.63.0 and Pillow 12.2.0. The lock, not this observation, selects versions.
- PostgreSQL **server tools**, with `pg_config` on PATH and `initdb`, `pg_ctl`,
  `pg_controldata` in its bindir. Historical validation used PostgreSQL 14.24.
  Preview setup requires the `C.UTF-8` locale. It does not require or use a
  pre-existing database, system database service or ordinary application role.
- Five free loopback ports: default HTTP 8780/8781/8782 and PostgreSQL 55488/55489.
  The launcher refuses occupied ports and PostgreSQL port 5432. Use its explicit
  port flags for a second pair. Step 7 browser checks also need port 8768.
- Chromium and its Linux shared-library dependencies. Install OS packages only
  through a separately approved host setup; these tools do not run sudo/installers.
- Node/npm only for optional prototype builds and axe tooling. Historical builds
  used Node 24.2.0/npm 11.4.2. Exact npm dependency versions/integrities are locked.

## Fresh-checkout dependency setup

After environment/network installation approval, from the repository root:

```sh
uv sync --locked --extra dev --extra ui --no-install-project
.venv/bin/python -m playwright install chromium
npm ci --prefix ui-lab/services-dashboard/tools --ignore-scripts --no-audit --no-fund
```

`--no-install-project` installs the Django checkout's locked dependencies without
building the unrelated historical `src/fio_taskio` wheel target. The optional
`ui` extra pins Playwright; production installs do not request it. Browser
installation is separate from Python dependency installation. The npm tools
package supplies axe-core 4.11.1 for the retained browser/accessibility checks.
Do not copy an ordinary `.env`, media, database dump or provider credentials.
The preview generates its own process-local configuration and synthetic accounts.

All UI validators use Playwright's installed Chromium by default. To select an
existing compatible system browser, set `PWA_CHROMIUM` to its executable path;
for example, if Chromium is installed on PATH:

```sh
export PWA_CHROMIUM="$(command -v chromium)"
```

Unset `PWA_CHROMIUM` to return to Playwright's browser. An optional
`PLAYWRIGHT_BROWSERS_PATH` must be consistent during installation and validation.
The launchers never download a missing browser implicitly. Browser/version
differences can change screenshot pixels; historical pixel equality is tied to
the recorded browser, fonts, viewport and operating environment.

## Static verification

These commands do not initialize Django, create fixtures or contact a database:

```sh
.venv/bin/python -B scripts/check_ui_workflow.py
.venv/bin/python -B scripts/motionmate_preview.py --help
.venv/bin/python -B scripts/motionmate_preview.py capture --help
uv lock --check --offline
.venv/bin/ruff check --no-cache scripts/motionmate_preview.py scripts/ui_preview scripts/check_ui_workflow.py scripts/archive_ui_history.py
git diff --check
```

The static checker verifies declared/locked UI dependencies, protected Step 7
source hashes, essential screenshot hashes, proposed manifest availability,
documentation/skill links and browser-path portability. Historical gallery
references are identified separately because their full bundle lives outside Git.

## Capture current BEFORE and start applications

After explicit disposable-runtime authorization:

```sh
.venv/bin/python -B scripts/motionmate_preview.py capture
# Save the returned path, including its owner.json, as BEFORE_SNAPSHOT.
.venv/bin/python -B scripts/motionmate_preview.py create \
  --before-snapshot BEFORE_SNAPSHOT --route /crm/agent/dashboard/
```

Use the returned session path and launcher URL. Both apps initially use equivalent
synthetic fixtures. Real login/CSRF/forms/navigation remain Django behavior;
provider routes, financial writes, external networking, real email and workers
are unavailable. Cookies and databases are independent. No ordinary database is
used. Snapshots include uncommitted/untracked runtime sources, not customer data.
Keep the session and source identities for review; do not publish its credentials.

## Original Services dashboard from Git

The verified pre-Step-7 baseline is commit
`34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c`. Phase 1 matched all 6,749 original
runtime files to this tracked baseline; the four changed originals matched its
Git blobs. [Preservation metadata](preservation-manifest.json) records the proof.
Ensure this commit exists locally. A shallow clone may require a separately
authorized history fetch; the preview never fetches history automatically.

```sh
git cat-file -e 34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c^{commit}
.venv/bin/python -B scripts/motionmate_preview.py capture \
  --git-ref 34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c
# Use the returned historical snapshot path in the normal create command.
.venv/bin/python -B scripts/motionmate_preview.py create \
  --before-snapshot HISTORICAL_SNAPSHOT --route /crm/agent/dashboard/
```

Git blobs are read directly into an owned snapshot. No checkout/reset, worktree
replacement, temporary Step 7 runner or old `/tmp` backup is involved. Its
`source.json` records the resolved commit and source hashes. For future screen
work, capture the actual current worktree before implementation instead of
assuming HEAD is its baseline. The legacy `--before-step7` adapter remains only
for old local artifacts and is not needed by this procedure.

## Validation

After the scoped design/implementation approval, implement only authorized
files, then freeze the new AFTER source:

```sh
.venv/bin/python -B scripts/motionmate_preview.py refresh-after --session SESSION_PATH
.venv/bin/python -B scripts/motionmate_preview.py validate --session SESSION_PATH
```

`validate` writes screenshots/JSON and performs real login/onboarding POSTs in
the reserved validation account, cookie/CSRF isolation and role/theme/navigation
checks. It independently restarts BEFORE. Human review accounts are not reset.
It currently targets the Services dashboard; extend audited fixtures/checks for
another screen. `--route` changes the launcher destination, not the test adapter.

For retained Step 7 server/static contracts and optional Chromium/axe regressions,
authorize disposable **test database** creation and evidence output separately:

```sh
.venv/bin/python -B scripts/motionmate_preview.py check-dashboard --session SESSION_PATH
.venv/bin/python -B scripts/motionmate_preview.py check-dashboard --session SESSION_PATH --browser
```

Use a freshly created historical/current pair for the browser comparison.
The portable wrapper verifies the owned AFTER cluster before Django creates
`test_services_rollout`, supplies the actual user/port/identity, uses frozen source
without reading the ordinary `.env`, and disables provider/network access.
Browser mode first captures the original BEFORE view/templates in that isolated
test harness, then runs AFTER assertions, axe and unchanged-page comparisons.
It does not alter either interactive preview's fixture database. Evidence is
written under `SESSION_PATH/after/evidence/`; repeats overwrite that test output.
Preserve it or create a new pair before repeating. No old `/tmp/run_checks.py`
is required. The historical broader 267-test failures remain documented in Step 7;
these focused commands do not claim to reproduce or repair that entire run.

The tooling unit suite creates temporary files and sockets but no application
database; obtain permission before running it:

```sh
PYTHONPATH=scripts .venv/bin/python -B -m unittest ui_preview.test_tooling -v
```

Retain raw accessibility incompletes and failures. Check 1440/768/390px and both
themes, keyboard/focus, empty/restricted/long states, affected routes/forms and
both verticals for shared changes. The debug allocator remains a local runtime
workaround, not release readiness. Chromium/synthetic evidence does not verify
ordinary databases, providers, production collectstatic/PWA or other browsers.

## Compare, approve and manage the session

Open both real URLs from the launcher and compare the reviewed source/fixture
context. Review writes persist independently and clocks advance; no silent sync
occurs. Human UI approval is followed by separate release authorization.

```sh
.venv/bin/python -B scripts/motionmate_preview.py status --session SESSION_PATH
.venv/bin/python -B scripts/motionmate_preview.py stop --session SESSION_PATH
.venv/bin/python -B scripts/motionmate_preview.py start --session SESSION_PATH
# Optional independent side: --side before or --side after.
```

Even `status` performs owned database identity/HTTP checks; it is not an offline
file-only check. Stop/start verifies ownership and retains fixtures. AFTER refresh
refuses changed migration sources. No command updates an ordinary database.
Cleanup is destructive, requires separate explicit approval and both sides stopped:

```sh
.venv/bin/python -B scripts/motionmate_preview.py cleanup \
  --session SESSION_PATH --confirm EXACT_SESSION_ID
```

Do not clean up the only saved BEFORE/evidence. Nothing is deleted automatically.

## Optional prototypes and Phoenix reference

For a new synthetic screen, install the pinned lab build tools only after approval:

```sh
npm ci --prefix ui-lab/services-dashboard/daisyui --ignore-scripts --no-audit --no-fund
node ui-lab/tools/build.mjs services-appointments
.venv/bin/python -B ui-lab/tools/capture.py --screen services-appointments
.venv/bin/python -B ui-lab/services-appointments/check.py
```

Keep the approved Step 4 distribution frozen. Historical galleries and optional
Tabler/Appointments build output are in the [local archive](PRESERVATION.md), not
fresh-clone runtime requirements. If repeating the old Tabler build, install its
own committed npm lock. Historical hash-scope reports describe their original
project state; use a newly captured preservation map for a new task.

Obtain the licensed **Phoenix 1.23.0** distribution from the project's license
holder or authorized vendor download. With acquisition permission, extract a
local copy at `design_references/phoenix/` and check its `package.json` version.
The [Phoenix map](../../../.agents/skills/motionmate-ui/references/phoenix-map.md)
describes expected paths. Keep it read-only and ignored; do not build it, copy
its bundles over patched application assets, or force-add the library. A clone
already contains the application's served Phoenix assets and can run previews
without this optional component-reference distribution. If absent, report the
reference limitation rather than inventing examples.
