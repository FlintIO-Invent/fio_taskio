# Real Django comparison for Gate C

Open the [local launcher](http://127.0.0.1:8862/) for synthetic review accounts
and the shared local password. Each app has independent sessions, theme storage,
CSRF and database state.

| Application | Interactive link |
| --- | --- |
| BEFORE: actual working tree frozen before implementation | [Open BEFORE Clients](http://127.0.0.1:8860/crm/staff/clients/) |
| AFTER: implemented Phoenix candidate | [Open AFTER Clients](http://127.0.0.1:8861/crm/staff/clients/) |

Sign into both as `clients.owner@preview.test` for the main populated workspace.
The launcher includes the other Services roles and scenario accounts. Use
`clients.no-history.owner@preview.test` for an unassigned profile that renders in
both versions. The assigned-staff BEFORE profile has an existing HTTP 500;
AFTER renders it safely. This difference is retained and documented.

For a directory comparison limited to the original thirteen populated clients:

- [BEFORE original directory](http://127.0.0.1:8860/crm/staff/clients/?q=populated.clients.preview.test)
- [AFTER original directory](http://127.0.0.1:8861/crm/staff/clients/?q=populated.clients.preview.test)

Both copies began with equivalent fixtures. Browser tests intentionally created
and archived additional synthetic clients and confirmed imports in AFTER. Those
records remain. The [preservation proof](final-preservation.json) compares the
original IDs and financial facts, excluding explicitly listed setup metadata.
There is no silent reset or synchronization.

## Review path

1. Compare directory filters, cards/table, sorting, pagination and selection at
   desktop, tablet and mobile widths. Switch the existing light/dark theme.
2. Open Alice's profile; review contact and business details, relationship,
   notes, appointments and invoices. Financial labels are existing authoritative
   presentation. Existing invoice links perform real local GET navigation.
3. Create or edit a synthetic client. Open all six form sections, exercise country
   layouts and error-summary links, and verify the existing return destination.
4. Open archive confirmation and cancel/Escape. Confirming performs the existing
   POST against that side's disposable record and keeps its obligations.
5. Review CSV upload/preview/confirmation/result, or create a client inline from
   an appointment/request draft. Writes stay on the selected review side.

Read [Django validation](django-validation.md) before acceptance: full-page shell
accessibility findings, one pre-existing unrelated regression failure and a
Python GC teardown crash remain disclosed. Providers/financial writes and
external contact destinations are disabled in this local review. The launcher
uses the existing debug-allocator workaround; it does not demonstrate ordinary
runtime stability.

Source hashes, verified cluster identities and matching candidate files are in
[final preservation](final-preservation.json). Exact screenshot/result paths and
candidate digest are in the final evidence index and workflow check artifacts.
All source/evidence and the independent BEFORE remain retained. No commit, push
or deployment occurred.

## Review environment lifecycle

The active session is `/tmp/motionmate-preview-session-p29z5cgt`.
The existing CLI supports `status`, `start`, and `stop` with `--session` using
`.venv/bin/python -B scripts/motionmate_preview.py`. A stop retains the sources,
databases and evidence. Cleanup is a separate authorization. Ordinary local
servers and other preview sessions were left untouched.

Acceptance is pending at Gate C. The workflow skill requires: “Stop; passing tests
do not imply acceptance.” Human acceptance binds the exact candidate digest;
it does not authorize any release operation.

## Final candidate screenshots

These six fresh captures use the final source, equivalent original records and
scroll-to-top capture. Screenshots supplement the real interactive applications.

| Screen | BEFORE | AFTER |
| --- | --- | --- |
| Original directory, desktop light | [View BEFORE](/tmp/motionmate-preview-session-p29z5cgt/after/evidence/clients-final-review-1794946020418026106/before-directory-1440-light-full.png) | [View AFTER](/tmp/motionmate-preview-session-p29z5cgt/after/evidence/clients-final-review-1794946020418026106/after-directory-1440-light-full.png) |
| Unassigned profile, desktop light | [View BEFORE](/tmp/motionmate-preview-session-p29z5cgt/after/evidence/clients-final-review-1794946020418026106/before-profile-1440-light-full.png) | [View AFTER](/tmp/motionmate-preview-session-p29z5cgt/after/evidence/clients-final-review-1794946020418026106/after-profile-1440-light-full.png) |
| Create client, mobile dark | [View BEFORE](/tmp/motionmate-preview-session-p29z5cgt/after/evidence/clients-final-review-1794946020418026106/before-create-390-dark-full.png) | [View AFTER](/tmp/motionmate-preview-session-p29z5cgt/after/evidence/clients-final-review-1794946020418026106/after-create-390-dark-full.png) |

The candidate digest for Gate C is `c9b2403b9f84ad7092ba294aafdf76bf8cc3df497965789dd63c31f60ea18041`.
