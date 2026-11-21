# Employees & Team Management — Gate A review

21 November 2026 · Design version **v1** · Awaiting explicit design-direction approval

Directory first, existing invitation form and pending list, truthful role/access presentation.

Read the [design brief](brief.md), [Django source audit](audit.md) and
[prospective validation plan](validation.md). The [authorization log](approval-log.md)
records the current request and absence of later consent.

Scope-bound design SHA-256:

`edd7fd937770227d5e748b8bafa0a6bc3fdc4b26887fe412d094d8004fc54cf8`

| Bound artifact | SHA-256 |
| --- | --- |
| [brief.md](brief.md) | `2e4d95f31775785ee7d51505cc5ad9a8c57c4653b3aa8a0340d0fed11147bebd` |
| [audit.md](audit.md) | `3ec44f5ddf232b1868208499ccc89d8c6cb4904e832ae6e3e547a989f6d2923e` |
| [source-audit.json](source-audit.json) | `a55ccc6f8bd1ca3f7991ee963e0458022bfd869f1de593df2d7e4093811afd3a` |
| [validation.md](validation.md) | `59e10c0c21e4369ce6adf1db0ff1ad74338be5f0e3dca4292069207e9f891016` |

Approve this named workstream's v1 direction independently. Approval permits
preparing its separate Gate B production integration/manifest/resource proposal
and then stopping. It grants no implementation, preview/fixture setup, schema,
data, provider or release permission, and does not approve the other workstream.

All approval fields remain null. Application manifests, target baselines,
resource authorizations and candidates are absent. No standalone prototype is
required or generated. No actual Django browser audit/interactive BEFORE exists
yet; existing GET side effects preclude ordinary-database visits. Real BEFORE/
AFTER uses authorized disposable resources only after Gate B.

The user explicitly requested this Gate A stop. The
[Motionmate UI workflow skill](../../../../../.agents/skills/motionmate-ui-workflow/SKILL.md)
also requires: “Stop for explicit approval.” This is the requested design gate.

Offline source/artifact/link/state/preservation checks are recorded in
[offline-checks.json](offline-checks.json). These establish documentation and source
consistency, not Django, browser, accessibility, database or provider health.
