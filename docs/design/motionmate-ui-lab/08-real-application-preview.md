# Step 8 — real application interactive previews

15 November 2026 · local tooling/documentation only. The user approved Step 7's
Services dashboard design before this work. Its application files remain intact.

The user subsequently approved this Step 8 workflow. This document records the
historical session; use [fresh-checkout setup](REPRODUCIBILITY.md) for current
commands and [preservation](PRESERVATION.md) for archived evidence. Session paths
and listener availability below are provenance, not fresh-clone requirements.

## Open the applications

- [Local launcher and test accounts](http://127.0.0.1:8782/).
- [BEFORE — Original Services dashboard](http://127.0.0.1:8780/crm/agent/dashboard/).
- [AFTER — Approved Services dashboard](http://127.0.0.1:8781/crm/agent/dashboard/).

Both are actual Django applications, including real sign-in forms, sessions,
CSRF, views, templates, database reads/writes and Bootstrap/Phoenix interactions.
They are separate processes and source copies, not an HTML mock, screenshot
viewer, iframe simulation or UI Lab controller. Use `owner@preview.test` first;
the launcher displays the generated preview-only password. Sign out on one side
to change its account; the other side stays signed in.

Accounts cover Services owner/admin/staff/accountant/viewer; empty, locked,
grace, restricted, welcome, long and EUR states; Logistics owner/staff; and a
reserved validation owner. All addresses end in `@preview.test`. Validation may
change its dedicated onboarding account; it does not reset human review accounts.

## Isolation and provenance

Session directory: `/tmp/motionmate-preview-session-el3ei0h7`.
Session ID: `55997314777f1d39`.

| Side | HTTP | PostgreSQL | System identifier | Disposable database |
| --- | --- | --- | --- | --- |
| BEFORE | `127.0.0.1:8780` | `127.0.0.1:55488` | `7708446643223039185` | `mm_preview_55997314777f1d39_before` |
| AFTER | `127.0.0.1:8781` | `127.0.0.1:55489` | `7708446723162934712` | `mm_preview_55997314777f1d39_after` |

Their actual data directories are respectively `before/pgdata` and
`after/pgdata` inside that owned temporary session. Each cluster was newly
initialized, verified empty before migration/seeding, and fingerprinted using
its live listener, process, actual directory and PostgreSQL system identifier.
Commands verify identity first; every new Django connection rechecks it.
An identity mismatch stops the workflow without falling back to another database.

BEFORE was reconstructed from the Step 7 saved original files under
`/tmp/motionmate-step7-rg6s8g_0/original/` and the saved 13,829-file checksum map.
Every included original runtime file was verified. The four changed files were
restored **in the copy only**; Step 7 additions were excluded from BEFORE.
AFTER was copied from the current working tree, including its uncommitted and
untracked application files. Git HEAD was not used as either baseline.

Snapshots contain only runtime source, templates and static assets. They exclude
ordinary records, uploads/media, `.env`, databases, logs, Git internals, caches,
collected static output and lab JavaScript. Copies are independent files with
integrity manifests; no live worktree links or hardlinks are used. The installed
virtual environment is reused without dependency installation or modification.
The ordinary development server on port 8000 was inspected through process
metadata only and left untouched; it was not used for HTTP or database checks.
The earlier Step 7 cluster and evidence were also preserved.

Both databases were seeded by the same local fixture adapter, using one shared
seed timestamp and identical records/IDs, Services roles, plans/entitlements,
appointments, requests, invoices, booking availability and onboarding context.
Full fixture inventories are compared before startup. Both apps subsequently use
the real current clock; appointments and grace periods age normally.

Cookie names include the session ID and BEFORE/AFTER side for session, CSRF and
language. Messages use the native Django session backend. Browser storage/themes
are origin-isolated by port. Both versions can therefore coexist with each other
and with the ordinary application's differently named cookies.

## Safety wrapper and intentionally unavailable interactions

All overrides live under local tooling, outside `src/taskio/` and the frozen
application sources. The production configuration and business code are unchanged.
Child processes receive a clean environment, explicit owned database settings,
unique preview secrets, private media paths, local-memory email/cache and no
provider credentials. They do not read the ordinary `.env` or customer uploads.

Python networking rejects external DNS/connects and other database listeners.
Browser CSP prevents external fetches/assets/workers/frames/form submissions;
external redirects/contact links are disabled locally. Google font CSS is mapped
to an existing local Nunito font, keeping the shell's actual typography. No lab
controller is loaded. External preconnects are removed. Unicons/Turf/maps and PWA
service workers remain unavailable; no replacement success is simulated.

Provider routes and financial POSTs return an explicit HTTP 409. A connection
wrapper additionally rejects financial/subscription SQL writes and runtime DDL,
including writes reached through another application route. Existing invoice
reads/navigation work; subscription checkout, payment/recovery, customer payment
recording and other financial operations are intentionally unavailable. Native
booking/onboarding/authentication forms remain real; email generated by them is
in-memory only. This sandbox is not billing/provider/deployment verification.

The original BEFORE mobile search still points to a missing modal. The approved
AFTER dashboard omits that trigger. The tooling does not repair the legacy UI.

**Runtime limitation:** the first disposable migration process reproduced a
segmentation fault previously documented in this checkout. Preview processes now
use `PYTHONMALLOC=debug` and fault reporting. This local process workaround allowed
setup and interactive checks without application edits. It is not a claim of
ordinary-runtime stability or release readiness. An initial fixture setup also
caught duplicate synthetic provider identities; those are now unique per state.
A fresh pair was created for the successful setup; failed setup logs/copies were
retained separately under `/tmp/motionmate-preview-session-mnokz2xt` (stopped).

## Start, stop, refresh and clean up

From the repository root:

```sh
.venv/bin/python scripts/motionmate_preview.py status \
  --session /tmp/motionmate-preview-session-el3ei0h7
.venv/bin/python scripts/motionmate_preview.py stop \
  --session /tmp/motionmate-preview-session-el3ei0h7
.venv/bin/python scripts/motionmate_preview.py start \
  --session /tmp/motionmate-preview-session-el3ei0h7
# Stop/start only one version by adding --side before or --side after.
```

Start re-verifies identity/source and retains synthetic data and sessions.
It never resets an existing database. Working-tree edits do not affect a running
version. Following a separately authorized UI implementation, update AFTER alone:

```sh
.venv/bin/python scripts/motionmate_preview.py refresh-after \
  --session /tmp/motionmate-preview-session-el3ei0h7
```

Refresh freezes a new current-source copy, checks unchanged migration sources,
and restarts only AFTER. BEFORE and both databases remain intact. Interactive
changes stay on their side and can make data differ; there is no silent data sync.
For a fresh matched pair, stop the old session and create another from the saved
BEFORE capture plus current AFTER source.

To recreate this historical comparison without the old temporary backups:

```sh
.venv/bin/python -B scripts/motionmate_preview.py capture \
  --git-ref 34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c
# Use the returned historical snapshot path.
.venv/bin/python -B scripts/motionmate_preview.py create \
  --before-snapshot HISTORICAL_SNAPSHOT
```

Default HTTP ports are 8780/8781/8782 and PG ports 55488/55489. Occupied ports
cause a stop; specify `--before-port`, `--after-port`, `--launcher-port`,
`--before-pg-port`, `--after-pg-port` for an additional pair. No existing process
is taken over. Use `capture` and `--before-snapshot` for future tasks rather than
reusing the historical Step 7 backup adapter. See the
[default review workflow](PREVIEW-WORKFLOW.md).

Cleanup is explicit and only accepts a stopped, owned temporary session:

```sh
.venv/bin/python scripts/motionmate_preview.py stop \
  --session /tmp/motionmate-preview-session-el3ei0h7
.venv/bin/python scripts/motionmate_preview.py cleanup \
  --session /tmp/motionmate-preview-session-el3ei0h7 \
  --confirm 55997314777f1d39
```

This removes that session's synthetic clusters, snapshots and evidence only.
Retain required BEFORE/evidence elsewhere before cleanup. Nothing is removed
automatically on failure, validation completion or task completion.

## Validation report

**Passed:** nine tooling safety tests; 30 real login/role/state checks; both
versions at 1440/768/390px in light/dark; native menus/themes, appointment/request/
invoice destinations and public booking; real onboarding selection, Next/Back/
close POSTs and keyboard containment; independent BEFORE stop/restart; and
AFTER-only source refresh with both authenticated sessions preserved.

The launcher links were clicked in Chromium and opened the real Django sign-in
pages. Both versions were authenticated simultaneously in one browser context.
BEFORE logout/role switching left AFTER's owner session intact. Cross-side CSRF
was rejected with HTTP 403. Disabled financial/provider POSTs returned HTTP 409.
No unhandled browser errors were recorded. External browser resources were
blocked by CSP; backend guard logs contain only the deliberate disabled-route
probes and no network attempts.

Other Services appointment/client/invoice pages and Logistics owner/staff
dashboard content match between versions, after normalizing their intentionally
different local origins. New dashboard assets remain absent from those pages.
BEFORE's 6,749 runtime files and AFTER's 6,755 runtime files pass their source
integrity checks. All 12 approved Step 7 handoff-file hashes still match the
working tree. No current application source changed in Step 8.

Evidence is under `/tmp/motionmate-preview-session-el3ei0h7/evidence/`:

- [Validation JSON](/tmp/motionmate-preview-session-el3ei0h7/evidence/validation.json).
- [Launcher/refresh/session checks](/tmp/motionmate-preview-session-el3ei0h7/evidence/lifecycle.json).
- [BEFORE desktop](/tmp/motionmate-preview-session-el3ei0h7/evidence/before-1440-light-viewport.png)
  and [AFTER desktop](/tmp/motionmate-preview-session-el3ei0h7/evidence/after-1440-light-viewport.png).
- [BEFORE phone/dark](/tmp/motionmate-preview-session-el3ei0h7/evidence/before-390-dark-viewport.png)
  and [AFTER phone/dark](/tmp/motionmate-preview-session-el3ei0h7/evidence/after-390-dark-viewport.png).
- Both native onboarding panels and unchanged-page captures are also retained.

Tooling safety tests cover independent snapshots/untracked root and app code,
excluded ordinary data/secrets, source tampering, symlink/ownership gates,
original-source proof, sanitized environment, external DNS/ordinary-port denial,
financial/DDL denial, identity failure before connection, and unrelated-process
protection. Setup/development failures were corrected in tooling/fixtures only;
the final validation above supersedes unfinished/failed attempts. The temporary
logs are `/tmp/motionmate-step8-create.log`, `motionmate-step8-validate.log`,
`motionmate-step8-tooling-tests.log`, and the owned side-specific runtime logs.

This is Chromium/local-sandbox validation. It does not establish ordinary-runtime,
provider, production asset collection, PWA/offline, Firefox/WebKit or assistive
technology readiness. The broader Step 7 test failures documented in its report
were not repaired or rerun as part of this tooling-only task.

Run the focused tooling safety suite without any application/database setup:

```sh
PYTHONPATH=scripts .venv/bin/python -m unittest ui_preview.test_tooling -v
.venv/bin/ruff check scripts/motionmate_preview.py scripts/ui_preview
```

Run the actual interactive checks only against this verified owned pair:

```sh
.venv/bin/python -B scripts/motionmate_preview.py validate --session SESSION_PATH
```

The validator does real login and onboarding POSTs in disposable data. On repeat
runs it can reopen the existing native Bootstrap welcome component for its
reserved validation account after that account completed welcome; it does not
reset user data or simulate server responses.

## File boundary and handoff

New tooling: `scripts/motionmate_preview.py` and `scripts/ui_preview/` containing
`__init__.py`, `core.py`, `cli.py`, `settings.py`, `guard.py`, `runtime.py`,
`fixtures.py`, `launcher.py`, `validate.py`, `test_tooling.py`.
Updated workflow/skill: `PREVIEW-WORKFLOW.md`,
`.agents/skills/motionmate-ui/SKILL.md`. The UI Lab `README.md` and launcher
`index.html` now explicitly label synthetic previews as prototypes. This report
is new. Approved Step 4/5 reference assets and evidence remain frozen.

No application source/design, models, routes, migrations, production settings,
dependencies or unrelated Services/Logistics behavior were changed. Step 7's
application/source handoff checksums remain unchanged. No ordinary database
connection/migration, provider operation, commit, push, deployment or release hook
was performed. Both real preview applications are left running for human review.
