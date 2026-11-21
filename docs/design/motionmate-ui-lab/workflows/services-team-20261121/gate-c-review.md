# Employees & Team — Gate C review

Design v1; the 14-file Gate B scope plus explicitly approved one-file preview
guard correction is implemented. **Awaiting final acceptance.** No release action.

- [Real BEFORE](http://127.0.0.1:8810/businesses/team/)
- [Real AFTER](http://127.0.0.1:8811/businesses/team/)
- [Local launcher and synthetic sign-in details](http://127.0.0.1:8812/)

Use `team.owner@preview.test` for management, `team.admin@preview.test` for Admin,
and the corresponding Staff/Accountant/Viewer identities for denials. Password is
shown only by the local launcher. Each side has its own session/CSRF/database.

Candidate SHA-256: `75eff468999c7f9360ba94327784190615d008be0a896cf7e49dbb57de587319`

AFTER source SHA-256: `29ee204efa0027842d410bfb010f9f8eb6209cdebcb61363424104ddb32cc751`

Initial matching fixture SHA-256: `616bf86a5fb61099c28c0a6df268191c68d9a08be279ff2cd788896a65526b5b`

[Results and preservation](validation-results.json) · [Readable validation](validation-results.md)
· [BEFORE desktop](evidence/before-team-1440-light.png)
· [AFTER desktop](evidence/after-team-1440-light.png)
· [AFTER mobile dark](evidence/after-team-390-dark.png)

Directory-first layout, clear existing role/status information and readable
invitation form/pending URLs. All backend, tenant, subscription, quota, role,
authentication and Logistics workflow contracts preserved. No new employee CRUD,
role editor or invitation actions. Guard correction allows only a single invitation
UPDATE with a read-only subscription join; financial/schema negatives passed.

20 focused Django tests, 5 boundary tests and actual browser checks passed.
Limitations: three older Settings assertions also fail on BEFORE; the existing-user
acceptance-template gap remains excluded; full-page axe retains the untouched
shared sidebar contrast issue and incomplete; isolated debug-allocator Chromium
checks do not prove ordinary runtime/providers/full accessibility.

AFTER review contains one new synthetic invitation accepted and then deactivated
by browser verification. Initial fixtures matched; later writes remain independent.
No reset/reseed/synchronization or customer data. Settings work will preserve this
candidate and pair. Its authorized changes can trigger Team's broad workspace
helper warning; exact candidate hashes and sibling ownership remain the proof,
and no existing baseline is rewritten.

Review and accept this candidate independently. A commit/push/deployment still
needs separate explicit authorization. Keep previews available; no cleanup.
