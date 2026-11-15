# UI source and historical evidence preservation

Phase 2 preserves the approved Step 7 dashboard and Step 8 real Django previews.
Source, instructions, the frozen Step 4 implementation and essential screenshots
belong in the proposed Git manifest. Complete historical galleries are kept in a
separate local archive. No staging, commit, push, merge or deployment occurred.

## Essential screenshots in Git

[essential-screenshots.json](essential-screenshots.json) is the exact 18-file
manifest, including hashes and provenance:

- Six original Step 4 populated **viewport** PNGs: 1440/768/390px × light/dark.
  `ui-lab/tools/capture.py` reads those exact paths for its reference comparisons.
- Twelve real Django Step 8 **viewport** PNGs: BEFORE/AFTER × the same widths and
  themes, copied without modification under `screenshots/real-django/`.

The Step 4 files stay in place. Full-page, alternate-state, interaction and
earlier comparison screenshots remain in the archive and their original local
locations. Do not rebuild the frozen Step 4 distribution to refresh history.
New review evidence belongs to its new session/screen rather than overwriting
these approved references.

## Local historical archive

This workstation's archive is:

`/home/mzero/motionmate-ui-archives/2026-11-15-phase2/ui-history.tar.gz`

It is outside the repository, mode 0600, approximately 267 MB, with **1,856
content files** plus an internal manifest and README. Its exact byte size and
SHA-256 are recorded in [preservation-manifest.json](preservation-manifest.json).
This location is local provenance, not a hard-coded runtime requirement; copy
the archive through an authorized local handoff if another checkout needs it.

| Archive path | Contents |
| --- | --- |
| `repository/ui-lab/` | Complete historical galleries, screenshots, JSON evidence, source, frozen distributions, optional built prototypes and licenses |
| `repository/docs/design/` | Historical design reports, metrics and original screenshots, captured before Phase 2 documentation changes |
| `runtime/step7/evidence/` | Original BEFORE and final AFTER gallery, interactions and comparison captures; excludes development attempts |
| `runtime/step7/*.json` | Original source/handoff hash maps, scope proof, selected regression comparison and test labels |
| `runtime/step8/evidence/` | Final comparison/onboarding/unchanged-page PNGs and validation/lifecycle/preservation JSON |
| `MANIFEST.json` | Original source paths, byte counts and SHA-256 for every content file |

No `.env`, dependency installation, database/cluster storage, session file,
credentials, raw log or duplicate 98 MB screenshot ZIP is included. The Step 8
launcher screenshot displays the generated password and is excluded. Failure
screenshots are excluded as unreviewed captures. No sensitive screenshot was
selected for archiving; original images were not edited. Selected images are
synthetic application/prototype captures, not ordinary customer records.
Text candidates were scanned for credential patterns and credential JSON fields
before archiving. This allowlist and exclusion policy is implemented in
[archive_ui_history.py](../../../scripts/archive_ui_history.py).

The archive preserves historical relative gallery links. Historical absolute
local URLs in reports record their original sessions and are not live services.
Raw logs and failed attempts remain at their original local paths, unchanged.
The archive is evidence, not a recoverable PostgreSQL/session backup.

## Verify and restore

Reading archive metadata and checking its SHA-256 does not require a database.
Restoration creates files and serving opens a loopback listener; obtain the
applicable authorization first. Use a **new** external directory so no current
checkout or evidence is overwritten. Set these variables to local paths:

```sh
UI_HISTORY_ARCHIVE=/absolute/path/to/ui-history.tar.gz
UI_HISTORY_RESTORE=/absolute/path/to/new-motionmate-ui-history
sha256sum "$UI_HISTORY_ARCHIVE"
# Compare with preservation-manifest.json before extraction.
mkdir -m 700 "$UI_HISTORY_RESTORE"
tar -xzf "$UI_HISTORY_ARCHIVE" -C "$UI_HISTORY_RESTORE"
.venv/bin/python -m http.server 8766 --bind 127.0.0.1 \
  --directory "$UI_HISTORY_RESTORE"
```

Open `/repository/ui-lab/` for the synthetic galleries or
`/runtime/step7/evidence/index.html` for the actual Django historical gallery.
Step 8 images/JSON are under `/runtime/step8/evidence/`. Verify individual
extracted files against the internal `MANIFEST.json` hashes when needed.
Stop the foreground server with Ctrl-C; nothing here authorizes deletion.

Do not extract over the worktree. For fresh interactive BEFORE/AFTER apps use
the [portable runbook](REPRODUCIBILITY.md), not archived sessions or old runners.
The verified original runtime commit is
`34eacc9ce9b412b0ffeb5ffa492a69f5de49ca4c`; Git captures do not need the archive.

## Proposed staging scope

[staging-manifest.txt](staging-manifest.txt) is the exact root-relative source and
essential evidence inventory. It is a proposal only. Every listed file must exist
and pass the static checker before separately approved staging. Ignore rules now
expose only the reusable Motionmate UI skill/reference and retain the essential
evidence exceptions. No force-add of `.agents/`, Phoenix or historical galleries
is needed or allowed by this manifest.

The archive, dependencies, caches, older screenshots, optional rebuilt output
and raw logs stay outside that scope. Exclusion never implies deletion; all
pre-existing files remain in place. Existing tracked collected static output and
unrelated application/deployment files remain untouched.
