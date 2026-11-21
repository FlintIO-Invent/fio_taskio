# Services Catalogue v1 — Gate C

Implementation and validation are complete within the approved 15-file scope.
**Final human acceptance is pending.** No commit/release/cleanup is authorized.

- [Real BEFORE](http://127.0.0.1:8880/crm/settings/services/)
- [Real AFTER](http://127.0.0.1:8881/crm/settings/services/)
- [Local launcher and synthetic login accounts](http://127.0.0.1:8882/)

Both are actual Django applications with independent verified PostgreSQL databases
and matching initial synthetic fixtures. The immutable BEFORE is the actual working
tree captured before edits, not HEAD or a prototype. Read/write forms remain real
Django; financial/provider restrictions remain in the review guard.

| Identity | SHA-256 |
| --- | --- |
| Candidate | `6f333832eee6787bbe74d657fc567242285dcfec5d842bb34e231c3703ce16bb` |
| Review | `8ef835e47cbe1a0f10ca1a22c1565a2394bbd959140ce42d1271b4bcadffe5c7` |
| BEFORE source | `c9cbeaeefdea6a09a02cb5d00671d4461a98bd0b409c2c7f49ba37d4bd3b719c` |
| AFTER source | `8c859600639b4fd4c4d3b9a8d26094142a9075264aac1921333830cdb8bf89e9` |
| Equal initial fixtures | `a783d50bf9c9d53588105ff8fab624ba7cc6d47acf20698064bfda7619d965c0` |

See [validation results](validation-results.md), [implementation](implementation.md)
and [verified identities](runtime.json). 47 initial Django regressions passed;
8 focused Catalogue tests (overlapping) and one native browser journey passed.
Forty browser cases per side and four final current-source cases completed.
Existing Logistics bodies/rendering, tenant/role/CSRF/soft archive/tax behavior
and initial synthetic domain/financial inventories are preserved.

[BEFORE desktop](evidence/before-desktop.png) ·
[AFTER desktop](evidence/after-desktop.png) ·
[BEFORE mobile](evidence/before-mobile-dark.png) ·
[AFTER mobile editor](evidence/after-editor-mobile-dark.png)

Limits: module axe has no violations; raw incomplete findings and two pre-existing
shared-shell contrast failures remain. The named readonly preview account safely
redirects to billing attention; actual eligible read-only catalogue policy was
verified in isolated Django. Ordinary runtime/provider readiness is unverified.
Initial setup/browser harness failures remain in their external logs.

Keep these resources/evidence available. The user authorized continuing next to
Data Import without an intermediate prompt; this Catalogue candidate stays at
Gate C, unaccepted. Subsequent disjoint sibling source/record changes are separately
owned and will not silently rebaseline this frozen helper checkpoint.
