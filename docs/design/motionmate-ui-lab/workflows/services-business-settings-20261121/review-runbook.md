# Local Gate C review runbook

Both pairs are real Django applications on independently verified disposable
PostgreSQL with synthetic records. Ordinary databases and providers are excluded.
Open a launcher to view the locally generated password; it is not stored in these
repository records. Each pair has its own password and independent cookies.

| Pair | Launcher | Synthetic accounts |
| --- | --- | --- |
| Team | http://127.0.0.1:8812/ | `team.owner@preview.test`, `team.admin@preview.test`, `team.staff@preview.test`, `team.accountant@preview.test`, `team.viewer@preview.test` |
| Settings | http://127.0.0.1:8822/ | `owner@preview.test`, `admin@preview.test`, `staff@preview.test`, `accountant@preview.test`, `viewer@preview.test` |

Review Team at `/businesses/team/`; Settings at `/businesses/settings/` and its
existing operational page `/businesses/settings/booking/`. Owner is the main
review account. Team remains denied to Staff/Accountant/Viewer. Settings permits
personal fields for all signed-in roles; only Owner/Admin with write access may
edit Business settings. Staff availability remains self-only.

Initial fixtures matched across each pair. Browser verification writes remain
independent: AFTER has synthetic saved names, invitation/member and availability
changes described in each review. Do not reset/reseed/synchronize for comparison.

These commands affect only the named owned review resources and verify ownership:

```sh
.venv/bin/python -B scripts/motionmate_preview.py status --session /tmp/motionmate-preview-session-g2_q9ufd
.venv/bin/python -B scripts/motionmate_preview.py status --session /tmp/motionmate-preview-session-6_a8stg9
# If explicitly asked to stop/restart a review:
.venv/bin/python -B scripts/motionmate_preview.py stop --session /tmp/motionmate-preview-session-g2_q9ufd
.venv/bin/python -B scripts/motionmate_preview.py start --session /tmp/motionmate-preview-session-g2_q9ufd
.venv/bin/python -B scripts/motionmate_preview.py stop --session /tmp/motionmate-preview-session-6_a8stg9
.venv/bin/python -B scripts/motionmate_preview.py start --session /tmp/motionmate-preview-session-6_a8stg9
```

Cleanup is a separate destructive authorization and remains unperformed. After
separate explicit cleanup authorization, both sides must first be stopped and
the session's exact ID must be supplied. Retain source snapshots/evidence first.

```sh
# Only after separate explicit cleanup approval:
.venv/bin/python -B scripts/motionmate_preview.py cleanup --session /tmp/motionmate-preview-session-g2_q9ufd --confirm c019c960b5d5b1d6
.venv/bin/python -B scripts/motionmate_preview.py cleanup --session /tmp/motionmate-preview-session-6_a8stg9 --confirm 7e575f86ce5aa2fb
```

No staging, commits, pushes, merges or deployment is authorized. Gate C acceptance
binds each reviewed candidate and limitations separately; commit preparation may
follow acceptance, but a commit still requires explicit user authorization.
