# Three Motionmate Services reviews — Gate C

**All three modules await separate final acceptance.** Designs and scopes remain
independent. No staging, commits, pushes, merges, deployments or cleanup.

| Module | Original Django | Updated Django | Synthetic logins |
| --- | --- | --- | --- |
| Services Catalogue | [BEFORE](http://127.0.0.1:8880/crm/settings/services/) | [AFTER](http://127.0.0.1:8881/crm/settings/services/) | [Accounts](http://127.0.0.1:8882/) |
| Data Import | [BEFORE](http://127.0.0.1:8900/crm/staff/data-import/) | [AFTER](http://127.0.0.1:8901/crm/staff/data-import/) | [Accounts](http://127.0.0.1:8902/) |
| Subscriptions & Billing | [BEFORE](http://127.0.0.1:8910/businesses/subscription/) | [AFTER](http://127.0.0.1:8911/businesses/subscription/) | [Accounts](http://127.0.0.1:8912/) |

Open the account launcher for each pair, then sign in with its module owner.
Catalogue: `catalogue.owner@preview.test`; Data Import:
`imports.owner@preview.test`; Billing: `subscriptions.owner@preview.test`.
Passwords are private to those loopback launchers. Synthetic scenario/role
accounts are listed there too. Each side has independent sessions/CSRF cookies
and PostgreSQL storage; review writes persist independently. Do not reset/reseed.

Catalogue and Data Import source candidates, completed state and original
validation/screenshots remain unchanged. The execution environment restart
removed their old temporary servers, databases and raw logs. Exact original
working-tree source digests matched reconstruction; fresh owned resources and
checks supplement the old evidence. Their saved Gate C runtime records are
historical. **Use this supplement for current running resource identities.**
No baseline, approval or historical evidence was overwritten.

[Machine-readable current identities](current-reviews.json) ·
[Exact source reconstruction](source-recovery.json) ·
[Fresh browser results](browser-results.json) ·
[Keyboard/draft results](recovery-keyboard.json) ·
[Peer preservation](recovery-preservation.json)

Fresh Catalogue validation: **48 Django + one native journey**; 40 core browser
cases per side, five state cases and ten role cases. Data Import: **221 Django +
one native CSV journey**; 48 core cases per side, eleven state cases and ten role
cases. Subscription: **142 Django + four native journeys**; eight core cases per
side, 26 state cases and ten role cases. AFTER module axe, overflow, checked
small-target and JavaScript findings are zero in these core runs. Keyboard focus,
theme-retained drafts and native disclosure/confirmation controls were checked.

The ten inherited portal fixture failures reproduced against BEFORE. Only test
setup changed; all portal assertions remain. [Subscription validation](validation-results.md)
and [fixture investigation](fixture-investigation.md) record the correction and
preserved raw failures. Review domains/configuration remain unchanged. Data Import
has 44 complete matching job facts and original seed audit timestamps; its fresh
full-job baseline was not captured before browser reads. Catalogue's old readonly
fixture lacks a valid synthetic price; grace-expired read/no-write policy passes
isolated Django tests. Those fixture limitations remain explicit.

Two pre-existing shared-sidebar contrast nodes remain outside scope. Raw module
axe incompletes: Catalogue 16 and Data Import 24 core-case findings; Subscription
zero. Full AA/screen-reader/provider/ordinary-runtime readiness is not established.
Existing debug allocator remains. Billing/provider writes stay blocked in the
review pair, as approved. Genuine billing POST/CSRF/redirect contracts passed on
the separately guarded test server with mocked SDK; no provider navigation sent.

[Catalogue original Gate C report](../services-catalogue-20261119/gate-c-review.md) ·
[Data Import original Gate C report](../services-data-import-20261119/gate-c-review.md) ·
[Subscription current Gate C report](gate-c-review.md)

## Services Catalogue

15 exact files. Candidate `6f333832eee6787bbe74d657fc567242285dcfec5d842bb34e231c3703ce16bb`.
Current resource review `f777048ec0fe74a6f74946f6238cc8a38d59d51b4f322f3602d3c5ed93ba332a`.
Supplemental current-resource review; original Gate C state, candidate and evidence are retained unchanged.

BEFORE source `c9cbeaeefdea6a09a02cb5d00671d4461a98bd0b409c2c7f49ba37d4bd3b719c`. AFTER source
`8c859600639b4fd4c4d3b9a8d26094142a9075264aac1921333830cdb8bf89e9`. Equal initial synthetic fixture inventory
`cc96761435dcfe109cabfee5bd4e5f4223fde60b669bdc7d3c85c63e0ace14f7`.

## Data Import

31 exact files. Candidate `3419fa3e05be53706084a8482771b780452e3306d46eb0e58177a4bb640625fe`.
Current resource review `552a7a4f360de7c36a08b812858c08c9332ab2a063f83a15ef26bd83b3cbedf4`.
Supplemental current-resource review; original Gate C state, candidate and evidence are retained unchanged.

BEFORE source `8c859600639b4fd4c4d3b9a8d26094142a9075264aac1921333830cdb8bf89e9`. AFTER source
`c310a29f7e32570246fa7034367da839eca435927f380b44a010423cd9839435`. Equal initial synthetic fixture inventory
`904a4023e415c69ba8ab41a9df5cb27243c687290b1479046f0b4b998b69a1ae`.

## Subscriptions & Billing

16 exact files. Candidate `ec6791a414ad1c7435f07efd1481a8af9983beb42dbf1186bd049400991ccf0c`.
Current resource review `16580d1e9aca403da16559b6ee135f653d9e21079667414a812f3ad3eda9eab9`.
Current workflow helper review; includes final current source and validation results.

BEFORE source `c310a29f7e32570246fa7034367da839eca435927f380b44a010423cd9839435`. AFTER source
`b8cd3a376449b0a9360a0a0f8a67d4dc5899d9caeaee02e32eca98d30c2ae1c3`. Equal initial synthetic fixture inventory
`554419a9d47d864d34a42b0f2e53f1df7d0a7cf4c46d5547a12164b873fbaf7f`.

Accept each module by its candidate and current resource-review binding above.
Acceptance is separate from release authorization. The requested workflow stops
here; all acceptance records remain empty.
