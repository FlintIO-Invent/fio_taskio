# Subscription validation results

**142 Django tests and four native browser journeys passed.** All data-writing
checks used `taskio.services_test_settings` and runner-owned
`test_services_rollout` on the independently verified AFTER cluster. Existing
migrations ran only on these new disposable clusters. No ordinary database,
provider, email service, customer data or new dependency was used.

Django coverage includes local plan/trial/confirmation and record preservation,
CSRF, owner/tenant boundaries, bound errors, read-only/free-test policy, effective
access states, Stripe checkout/portal/webhook/lifecycle contracts, allowances,
capabilities and unchanged Logistics rendering/roles. The ten legacy portal
fixture failures reproduced on BEFORE. Nine bodies are inherited unchanged;
one retains its original cases/assertions with membership created before marking
its fixture inactive. No quota or financial guard changed. See
[fixture investigation](fixture-investigation.md).

The final four native LiveServer journeys exercised real login, HTML forms,
CSRF and server POST handling: keyboard Cancel/reselect/Confirm kept client rows;
Manage billing and read-only Fix payment produced expected server redirects;
checkout resume stayed pending. Provider SDK responses were mocked. Loopback
`Route.fetch(max_redirects=0)` captured actual Django 302 responses before a
local test response stopped provider navigation. External browser DNS and
non-loopback requests were blocked. Billing return did not restore access.

Final native log: `after/native-final.log`. Django successful batch:
`after/django-142-passed.log` is a verbatim first-batch excerpt from
`after/backend-validated.log`; the latter retains its earlier browser-harness
failure. Final CSS label allocation was checked with current-source browser
captures and native journeys. Django/template/financial code stayed unchanged.

Real BEFORE and AFTER each completed **eight core cases** (1440/768/390/320px,
light/dark), **26 state cases** and **10 role cases**. AFTER had zero module axe
violations, module incompletes, checked small targets, document overflow or
JavaScript errors. States cover empty/long, trial/pending/cancellation, grace and
read-only recovery, stale/missing periods, cancelled/beta/free-test and missing
subscription; the existing no-subscription UI guard is preserved. Native recovery
and confirmation screenshots show mocked eligible controls and impact review.
Four offline boundary/parity checks passed; Ruff, format and whitespace passed.

Full-page axe still finds the two pre-existing Phoenix sidebar contrast nodes,
4.41:1 against 4.5:1. That shared shell is outside this scope. Catalogue and Data
Import retain their raw incomplete findings. No full AA/screen-reader or live
provider certification is claimed. Existing debug allocator workaround remains.
Interactive review pair financial writes/provider routes stay blocked, as
approved; their genuine native form contracts were tested in the isolated server.

Both review databases retain their full initial business, plan and subscription
facts, including side-specific plan audit times, plus initial domain/financial
inventory. Canonical cross-side parity excludes only migration-time plan audit
timestamps; full raw facts remain separately preserved. See
[preservation results](preservation-results.json) and [runtime](runtime.json).

An execution environment restart removed earlier temporary resources/raw logs.
Durable completed Catalogue/Data Import records/screenshots are preserved. Exact
working-tree source digests were recovered and matched; fresh pairs supplement,
without rewriting, their historical review identities. Catalogue passed 48 Django
checks plus its native journey again; Data Import passed 221 plus its native CSV
journey. Fresh 40/48 core cases per side and affected state/role checks passed.
Keyboard/draft checks passed on both restored AFTER applications. Full current
44-job facts match across Data Import and retain seed audit times; its replacement
full-job baseline was not captured before browser reads, as disclosed in
[recovery preservation](recovery-preservation.json).

[Browser report identities](browser-results.json), [source reconstruction](source-recovery.json),
[all 15 preserved shared content blocks](source-contracts.json) and
[three-review handoff](review-index.md) distinguish current runtime from historical
proof. All 62 source paths remain disjoint; 46 peer candidate hashes are unchanged.
No commits, staging, push, merge, release or cleanup occurred.

Reproduce against this still-owned pair, using installed Chrome:

```sh
export PWA_CHROMIUM=/home/mzero/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome
PYTHONPATH=scripts .venv/bin/python -B -m ui_preview.subscriptions_checks --session /tmp/motionmate-preview-session-z9qu5gsy
PYTHONPATH=scripts .venv/bin/python -B scripts/services_subscriptions_browser_check.py --session /tmp/motionmate-preview-session-z9qu5gsy --side after
```

Preserve review writes independently; never reset or reseed. Use the existing
`motionmate_preview.py status/start/stop --session ...` commands for owned
resources. Stop/cleanup and release remain separate user decisions.
