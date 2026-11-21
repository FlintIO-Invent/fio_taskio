# services-catalogue-20261119 — Gate B review

**Design v1 approved; implementation/resources awaiting explicit authorization.**

The user’s 20 November 2026 “proceed” approved Gate A for the three named v1
directions. See [approval record](approval-log.md). The approved design bytes
remain unchanged. This proposal covers **15 exact source files: 3
modifications and 12 additions**, independently of other modules.

- [Concrete integration, consumer impact, risks and sequence](integration.md)
- [Closed file/action/category/hash manifest](implementation-manifest.json)
- [Source/worktree review baseline](implementation-baseline.json)
- [Exact proposed disposable resources/actions](validation-resources.json)
- [Behavior, accessibility and regression coverage](validation.md)

| Identity | SHA-256 |
| --- | --- |
| Approved design v1 | `146bd111bff46aadb8f3574772e610bed838ba9f6521ea5c7a5d41421939ba5e` |
| Helper-bound implementation manifest | `5a0177576e4228f15796e6ef18239680febf9779654d7d1631ee9fc63dd16419` |
| Integration source/worktree baseline | `0dcd6a2c1d96a8cab56d12624f9e9f6181f1b9720dd9ab28686890a6de42e94d` |
| Proposed resource scope | `c411e9a31af3ef7ccc42ff3f57b9d6cb1d389945f76656a94b365527b9a5ce9b` |

## Proposed fresh resources

| Purpose | Loopback port |
| --- | --- |
| before http | 8880 |
| after http | 8881 |
| launcher http | 8882 |
| before postgres | 55630 |
| after postgres | 55631 |

Runner-only test DB: test_services_rollout on this new AFTER cluster; separate
LiveServer on 127.0.0.1:8768. Serialize all test runs. Selected ports were not
listening in the read-only preflight; recheck before use. No reservation, database,
preview, source snapshot, fixture or browser was created. Actual ownership must
be proven through existing guards after authorization, before writes.

The Catalogue helper execution baseline is activated after all three planning records are frozen.

No existing execution baseline will be overwritten. This coordination protects
other workstreams; it transfers no design or implementation consent. See the
integration plan for exact before-implementation checks and drift reconciliation.

## Requested decision

Authorize local implementation for this named module/design v1, limited to the
exact manifest identity above, plus the fresh owned resources/actions in
validation-resources.json: source capture, empty PostgreSQL review clusters,
existing migrations there only, synthetic fixtures and the guarded backend/real
Django form/browser/accessibility/regression tests. Present its real Django
BEFORE/AFTER review and stop at Gate C. Modules may be approved separately.

Financial/provider blocks remain on the interactive review pair. Write/CSRF/form
validation runs only in the separately guarded synthetic test database/LiveServer,
with provider SDK responses mocked and external browser transport blocked. No
ordinary DB or provider access, new schema source, dependencies, staging, commits,
push, merge, deployment or destructive cleanup is included.

The [workflow skill](../../../../../.agents/skills/motionmate-ui-workflow/SKILL.md)
requires: “stop for explicit authorization of that manifest”. Gate A is not B.

## Verification and limitations

Offline source/design/manifest/reference/dependency hashes, exact path actions,
non-overlap, documentation links/whitespace, branch/HEAD and unchanged application/
index were checked. Existing tools/assets were located; no runtime/browser or
data-writing test ran. All implementation/acceptance approvals remain null and
runtime resource authorization lists remain empty. Required missing runtime/form/
accessibility/Logistics evidence will keep Gate C pending; live provider-hosted
screens and ordinary-runtime readiness are not established by synthetic tests.
