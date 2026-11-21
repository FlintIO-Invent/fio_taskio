# Services Data Import v1 — Gate C

Approved 31-file implementation and validation complete. **Final human acceptance
is pending.** No staging, commits, push, merge, deployment or cleanup authorized.

- [Real BEFORE](http://127.0.0.1:8900/crm/staff/data-import/)
- [Real AFTER](http://127.0.0.1:8901/crm/staff/data-import/)
- [Local launcher and synthetic accounts](http://127.0.0.1:8902/)

The actual working-tree BEFORE includes completed Catalogue and original Data
Import. This is one real independent Django pair, with equal initial synthetic
fixtures and verified full 44-job facts, not a prototype or historical HEAD.

| Identity | SHA-256 |
| --- | --- |
| Candidate | `3419fa3e05be53706084a8482771b780452e3306d46eb0e58177a4bb640625fe` |
| Review | `b39740fdf66a38e425555d2a29d38975b18f340d3035bdc25d3c17177c2c714d` |
| BEFORE source | `8c859600639b4fd4c4d3b9a8d26094142a9075264aac1921333830cdb8bf89e9` |
| AFTER source | `c310a29f7e32570246fa7034367da839eca435927f380b44a010423cd9839435` |
| Equal initial fixtures | `851b07d5b0d28c105aba2f52910643be451c666d4ab389714131e753b8846fba` |

[Validation results](validation-results.md) · [Implementation](implementation.md) ·
[Verified identities](runtime.json)

221 Django tests and the native CSV journey passed. Forty-eight core browser cases
per side plus state/role checks and five current-source/keyboard cases completed.
The role checker was corrected to the existing Import policy and reran successfully.
Two legacy copy tests passed only on BEFORE; new guidance has replacement tests.
Original Client Import, Logistics and Catalogue source remain preserved, as do all
initial domain/financial and complete import-job facts on both review databases.

[BEFORE hub](evidence/before-hub-desktop.png) ·
[AFTER hub](evidence/after-hub-desktop.png) ·
[BEFORE mobile upload](evidence/before-upload-mobile.png) ·
[AFTER mobile preview](evidence/after-preview-mobile.png)

Limits: retained axe incompletes and unchanged shared-shell contrast findings;
module content has no reported axe violations. Ordinary/provider runtime and full
AA conformance are not established. Retain sessions and raw evidence.

The user authorized continuing to Subscription/Billing without an intermediate
prompt. This candidate remains at Gate C, unaccepted; later disjoint sibling
changes are separately owned and do not authorize silent baseline rewriting.
