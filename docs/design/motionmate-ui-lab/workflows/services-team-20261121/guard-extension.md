# Team preview guard extension proposal

Existing app source and backend tests are working. The interactive original and
redesigned Team GET returns 409 because invitation expiry executes an UPDATE with
a read-only subscription join. The guard currently treats any referenced financial
table as a financial write, including this read-only subquery.

Proposed extra implementation file: `scripts/ui_preview/guard.py` only.
Exact proposed patch: [guard-extension.patch](guard-extension.patch).

Permit only one ORM UPDATE targeting `businesses_businessinvitation`, with no
additional write/DDL keyword, SQL comment or statement separator. All direct or
nested subscription/financial writes, schema operations, external networking,
identity restrictions and provider routes remain blocked. Add negative/positive
checks inside already-authorized `scripts/ui_preview/test_team.py`.

On approval, extend Team manifest from 14 to 15 files and bind new consent/digest,
retain the original manifest/approval and baseline, and record the newly approved
file hash. Apply the same guard bytes to both owned review tooling copies, restart
only these owned apps and reverify. Frozen Django BEFORE source and fixture
identities remain unchanged. No application backend or ordinary database change.

This exact file is outside the approved closed manifest. The workflow skill
requires a concrete revised proposal for material scope expansion. Await explicit
approval before applying; Settings manifest/resources remain as approved.
