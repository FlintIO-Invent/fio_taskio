# Business Settings — Gate B implementation review

Design **v1 approved**; **implementation and disposable resources pending**.

Proposed exact scope: **21 files**, independently owned by this workstream.
Read [integration and impact](integration.md), [closed file manifest](implementation-manifest.json),
[proposal baseline](implementation-baseline.json), [resource requirements](validation-resources.json)
and [scope binding](gate-b-scope.json).

| Binding | SHA-256 |
| --- | --- |
| Approved v1 design | `fda72105714e92f4723c17c68a1495877229fc6876470f7ae230f8360399ec39` |
| Exact implementation manifest | `aa152af533dec2a8163f3cf089c20cbc09b236a9e96d74eba72f8c9171276a40` |
| Integration document | `fb48a766a1d68d181e6bb949f168127f832efd75b818478633952cedb1ed736c` |
| Proposed disposable resources | `c06facba198765048d023391b19b2ab7f2a4b34777004ee8a39b9fa2379ad63b` |
| Offline proposal baseline | `513e76252c2559ae90af0d81fec3b1174436e7dfa8a5cc24d556b0f50c7bf317` |

Settings explicitly proposes the Services-only bulk-field DOM namespace fix:
`id_bulk_staff_member`, `id_bulk_days` and choice IDs, `id_bulk_start_time`,
`id_bulk_end_time`, `id_bulk_is_active`, plus matching label/help/error targets.
Field names, Django form prefixes, POST discriminators, validation, Single IDs
and Bootstrap tab/panel hooks stay unchanged. A pure rendering helper performs
no query/save/permission change. This bounded exception needs Gate B authorization.

## Proposed real Django resources

| Resource | Proposed listener/settings |
| --- | --- |
| BEFORE Django | `127.0.0.1:8820` / `ui_preview.settings` |
| AFTER Django | `127.0.0.1:8821` / `ui_preview.settings` |
| Review launcher | `127.0.0.1:8822` |
| BEFORE empty owned PostgreSQL | `127.0.0.1:55520` |
| AFTER empty owned PostgreSQL | `127.0.0.1:55521` |
| Synthetic test DB | `test_services_rollout` on this AFTER cluster only; `taskio.services_test_settings`; serialized LiveServer `8768` |

All names/listeners are proposals, not created resources or ownership evidence.
Offline metadata/proc checks found installed tooling and no selected listener;
recheck/refuse occupied ports. Gate B includes creating fresh owned snapshot/
session roots, initializing two empty disposable clusters, applying existing
migrations there, adding matching synthetic fixtures and running isolated checks.
Identity/ownership proof precedes migration/fixture/test writes. No ordinary
`.env`, records/uploads/secrets, real email, providers or workers.

The exact offline proposal baseline is captured now. Settings helper execution
baseline remains unactivated until its serial preflight after Team ownership is
verified. No baseline is overwritten. The integration plan explains the helper's
sibling-directory hash limitation without weakening its guard.

## Requested authorization

Authorize **Business Settings v1**, this exact manifest and the listed disposable resources.
Team executes first and Settings second only when separately authorized. Keep
independent candidates/review pairs and Gate C acceptance decisions. Fixes remain
inside the closed manifest; material expansion needs a revised concrete proposal.
No new schema source, ordinary database mutation, shared authentication repair,
framework/dependency installation, staging/commit/push/merge/deploy or cleanup.

The user requested a Gate B stop after design approval. The
[workflow skill](../../../../../.agents/skills/motionmate-ui-workflow/SKILL.md)
says: “stop for explicit authorization of that manifest”. Therefore this review
stops before application implementation or runtime setup.

[Offline Gate B checks](gate-b-checks.json) cover source/design/manifest hashes,
JSON/links/whitespace and preservation only. No Django/browser/database/fixture/
provider checks ran. After B, preserve actual working-tree BEFORE, implement and
validate, refresh AFTER only, then stop at Gate C for human acceptance.
