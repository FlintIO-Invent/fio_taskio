# Employees & Team Management — Gate B implementation review

Design **v1 approved**; **implementation and disposable resources pending**.

Proposed exact scope: **14 files**, independently owned by this workstream.
Read [integration and impact](integration.md), [closed file manifest](implementation-manifest.json),
[proposal baseline](implementation-baseline.json), [resource requirements](validation-resources.json)
and [scope binding](gate-b-scope.json).

| Binding | SHA-256 |
| --- | --- |
| Approved v1 design | `edd7fd937770227d5e748b8bafa0a6bc3fdc4b26887fe412d094d8004fc54cf8` |
| Exact implementation manifest | `c15fe8b9c3d87783d5d74a74e9eb9f8efefbb35f9e64ef4d8162c8902c176848` |
| Integration document | `79b73cb533aaea371abfdd579e7238e4e8db5510fb0bf679fc2086c1d17bd9fe` |
| Proposed disposable resources | `7edd397e6d1fb6ea5969f03d706143535930ff4430648a1353cda6f9d234fd7f` |
| Offline proposal baseline | `04f8cae2c89a8571e726fef8a11a6c1b1c476c9faf6f92b5ad607cef71878852` |

No employee detail/edit/custom-role/search/bulk/resend/revoke/copy functionality.
The existing-user invitation acceptance repair remains a separate proposal.

## Proposed real Django resources

| Resource | Proposed listener/settings |
| --- | --- |
| BEFORE Django | `127.0.0.1:8810` / `ui_preview.settings` |
| AFTER Django | `127.0.0.1:8811` / `ui_preview.settings` |
| Review launcher | `127.0.0.1:8812` |
| BEFORE empty owned PostgreSQL | `127.0.0.1:55510` |
| AFTER empty owned PostgreSQL | `127.0.0.1:55511` |
| Synthetic test DB | `test_services_rollout` on this AFTER cluster only; `taskio.services_test_settings`; serialized LiveServer `8768` |

All names/listeners are proposals, not created resources or ownership evidence.
Offline metadata/proc checks found installed tooling and no selected listener;
recheck/refuse occupied ports. Gate B includes creating fresh owned snapshot/
session roots, initializing two empty disposable clusters, applying existing
migrations there, adding matching synthetic fixtures and running isolated checks.
Identity/ownership proof precedes migration/fixture/test writes. No ordinary
`.env`, records/uploads/secrets, real email, providers or workers.

Team helper baseline is activated once after both proposals are frozen;
see [state.json](state.json). No implementation or resources have been authorized.

## Requested authorization

Authorize **Employees & Team Management v1**, this exact manifest and the listed disposable resources.
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

Team first execution baseline is now captured and offline-verified in
[execution-baseline.json](execution-baseline.json); it protects the frozen Settings
proposal records. No existing baseline was replaced and no runtime was started.
