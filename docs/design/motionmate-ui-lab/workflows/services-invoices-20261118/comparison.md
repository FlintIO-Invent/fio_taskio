# Services invoices: real Django comparison

Review the actual working-tree baseline and the approved local implementation:

- [BEFORE](http://127.0.0.1:8870/billings/)
- [AFTER](http://127.0.0.1:8871/billings/)
- [Accounts and local password](http://127.0.0.1:8872/)

Use `invoices.owner@preview.test` for the populated Services workspace. The launcher
also lists the other Services scenarios/roles and Logistics accounts. Financial
POSTs remain intentionally blocked in these human review apps. Actual write journeys
were validated separately in the owned test environment.

| Identity | BEFORE | AFTER |
| --- | --- | --- |
| Source SHA-256 | `ed88487711b0554f6115d02068523d6b3f081cac93396a200a81d49a1193b083` | `c9cbeaeefdea6a09a02cb5d00671d4461a98bd0b409c2c7f49ba37d4bd3b719c` |
| Source | `/tmp/motionmate-preview-session-7su4ughv/sources/before` | `/tmp/motionmate-preview-session-7su4ughv/sources/after-1795049987598458527` |
| PostgreSQL port | 55620 | 55621 |
| Cluster system identifier | `7709661534386697836` | `7709661648349910964` |

Session: `/tmp/motionmate-preview-session-7su4ughv`, ID `7ba203f43eb3acb5`.
Settings: `ui_preview.settings`. Initial canonical inventory hash:
`6bd089e47b55014449539120cf3f053c6f8b719b05cf867d6676084c8b18da57`. Full financial/client fact comparison and
the two initial receipt timestamp differences are recorded in
[saved-record-parity.json](saved-record-parity.json).

The immutable BEFORE came from the actual working tree, including accepted prior
work, before application edits. Only AFTER was refreshed. Review writes are not
silently synchronized. Source/HTTP/cluster identities were independently checked
again after validation; see [runtime-final.json](runtime-final.json). The screen
matrix source precedes one final print-only text-color rule; all other application
bytes and screen rules match. Twelve actual print cases use the current AFTER
source. See [exact source delta](final-print-source-delta.json) and
[print evidence](django-print-summary.json).

The implementation replaces the Services directory, details/actions, create/edit
and payment composition; retains the authoritative internal ledger/status sections;
preserves the native Print action with customer-safe print presentation;
and gives customer documents a clean Subtotal/Tax/Total Amount/conditional Notes
presentation. Phoenix remains the production foundation. Customer documents omit
internal Draft/lifecycle labels and routine settlement summaries. Server lifecycle,
payment/refund, tenant/role/subscription/quota and issuance rules are unchanged.

All eight original non-Services template bodies are byte-identical to the baseline.
The Logistics PDF drawing stream/geometry/text comparison passes against the frozen
renderer. Thirty Logistics screenshot comparisons show 24 exact full
screenshots, 2 differences confined to sidebar animation/hover, and
4 debug-page differences confined to the displayed listener port.
The invoice content and all route/access results match; no Services region/assets
are introduced on Logistics. Existing debug-error overflow is preserved.

## Selected actual evidence

| Review | BEFORE | AFTER |
| --- | --- | --- |
| Detail, desktop light | [Screenshot](/tmp/motionmate-preview-session-7su4ughv/before/evidence/invoices-capture-1795046449367098164/detail-1440-light-viewport.png) | [Screenshot](/tmp/motionmate-preview-session-7su4ughv/after/evidence/invoices-capture-1795049755975821904/detail-1440-light-viewport.png) |
| Create, mobile dark | [Screenshot](/tmp/motionmate-preview-session-7su4ughv/before/evidence/invoices-capture-1795046449367098164/create-320-dark-viewport.png) | [Screenshot](/tmp/motionmate-preview-session-7su4ughv/after/evidence/invoices-capture-1795049755975821904/create-320-dark-viewport.png) |
| Customer PDF | [PDF](/tmp/motionmate-preview-session-7su4ughv/before/evidence/invoices-capture-1795046449367098164/partial.pdf) | [PDF](/tmp/motionmate-preview-session-7su4ughv/after/evidence/invoices-capture-1795049755975821904/partial.pdf) |
| Long customer PDF | [PDF](/tmp/motionmate-preview-session-7su4ughv/before/evidence/invoices-capture-1795046449367098164/many-lines.pdf) | [PDF](/tmp/motionmate-preview-session-7su4ughv/after/evidence/invoices-capture-1795049755975821904/many-lines.pdf) |

Full final capture directories:
`/tmp/motionmate-preview-session-7su4ughv/after/evidence/invoices-capture-1795049755975821904` and `/tmp/motionmate-preview-session-7su4ughv/after/evidence/invoices-supplement-1795049755969656499`.
Real write-journey evidence: `/tmp/motionmate-preview-session-7su4ughv/after/evidence/invoices-journeys-1795047797488801649`.
[Browser summary](django-browser-summary.json) records each designated evidence
folder and comparison outcome. Earlier iterations remain separate.

Gate C was explicitly approved on 19 November 2026; see [approval](gate-c-acceptance.json).
Acceptance is separate from release authorization. Finalization does not change or
clean up the retained preview resources. No staging, commit, push or deployment is
included. Existing older Clients previews and the approved UI Lab are retained.
