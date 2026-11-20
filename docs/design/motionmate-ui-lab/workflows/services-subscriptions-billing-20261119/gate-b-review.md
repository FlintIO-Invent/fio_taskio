# services-subscriptions-billing-20261119 — Gate B review

**Design v1 approved; implementation/resources awaiting explicit authorization.**

The user’s 20 November 2026 “proceed” approved Gate A for the three named v1
directions. See [approval record](approval-log.md). The approved design bytes
remain unchanged. This proposal covers **16 exact source files: 1
modifications and 15 additions**, independently of other modules.

- [Concrete integration, consumer impact, risks and sequence](integration.md)
- [Closed file/action/category/hash manifest](implementation-manifest.json)
- [Source/worktree review baseline](implementation-baseline.json)
- [Exact proposed disposable resources/actions](validation-resources.json)
- [Behavior, accessibility and regression coverage](validation.md)

| Identity | SHA-256 |
| --- | --- |
| Approved design v1 | `66c935e2d8b4c16b87049779a2783b251c98ce1295f15d3d3c15c8e027ad81f1` |
| Helper-bound implementation manifest | `0dd8564ddb540d772d8c181dbcbe7c5f142515f4ac47d0716bcd873bb74ee7df` |
| Integration source/worktree baseline | `cfb3ac7f0169c76b9955d08dd4077cab3304d22d736641fa6364853d69e39c13` |
| Proposed resource scope | `2895c5afc6546a285cb1dab14dbee05c1ec71b7d357ec07bf7517c75f1c00d6f` |

## Proposed fresh resources

| Purpose | Loopback port |
| --- | --- |
| before http | 8910 |
| after http | 8911 |
| launcher http | 8912 |
| before postgres | 55650 |
| after postgres | 55651 |

Runner-only test DB: test_services_rollout on this new AFTER cluster; separate
LiveServer on 127.0.0.1:8768. Serialize all test runs. Selected ports were not
listening in the read-only preflight; recheck before use. No reservation, database,
preview, source snapshot, fixture or browser was created. Actual ownership must
be proven through existing guards after authorization, before writes.

This module has the exact source/worktree review baseline above. Its helper execution baseline remains unactivated until it is selected for serial execution, before B is recorded and before any application edits; compare target/design/branch identities first.

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
