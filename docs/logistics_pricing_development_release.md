# Development pricing retirement release plan

Status: prepared for explicit operator approval; no deployment has occurred.
Target: `mm-development-app` only (`bb570390-7423-426e-83a3-5556a50dde9d`).
Release branch: `release/logistics-pricing-retirement-development`, based directly
on current Development v73, `6583bd60c1f6c623f34d1f94956e61ab2a795f90`.
The existing feature branch is retained. The release diff contains only the
pricing retirement implementation, its tests and documentation.

## Verified preparation, 16 October 2026

- Fresh ordinary-runtime runs: 197 PostgreSQL 18.4 pricing, admission, legacy/tier
  webhook, readiness, capacity and concurrency tests; 428 SERVICE/account tests.
  All passed. No debug allocator or GC workaround was enabled.
- No new migration files. Django model/migration comparison reports no changes.
  Read-only checks on deployed v73 passed with zero pending migrations.
- All three mapped EUR TEST Prices pass the candidate validator both with their
  actual provider data and after removing Price metadata: Core EUR 1,700,
  Growth EUR 2,300, Scale EUR 3,000; yearly, active, licensed and per-unit.
  Existing EUR/USD mappings, TEST keys and webhook settings are unchanged.
- Core, Growth and Scale remain inactive. Business 166 is active on local legacy
  `logistics`, has access, and has no Stripe provider identity. No subscription,
  role, location, password, capacity or financial record is reassigned.
- Preservation baseline covers all 49 public database tables, eight Stripe TEST
  subscriptions, 17 provider invoices and the provider Price catalogue. A second
  read found no changes. Two pre-existing legacy provider contracts reference
  absent Development tenants; they remain untouched and require separate review.
- No current-v73 runtime failure was found in the available log window. Fresh
  deployed read-only checks exited normally. Prior native-GC failures remain a
  reason to monitor the new release under normal Gunicorn execution; successful
  tests alone do not establish deployed runtime stability.

## Backup

Heroku backup `b004`, DATABASE: started 2026-10-16 11:33:44 UTC
(13:33:44 CEST); completed 11:33:56 UTC (13:33:56 CEST).
Archive: 334,201 bytes; SHA-256
`cc4678b2171bfbd98db17c7579dc647a065ed8af37dab84127b7acd3ec47d155`.
A PostgreSQL 18 client restored it into an empty, network-isolated disposable
database. All 49 restored tables exactly matched the fresh preservation baseline.
No database restore was performed against Development.

Private operational evidence and the downloaded backup are under
`/tmp/mm-pricing-release-28p6ww5j/`; no credentials or customer rows are committed.
The platform backup remains attached to Development.

## Deployment sequence after explicit approval

1. Verify the approved commit, clean release tree, Development app/database
   identity, current v73 SHA, complete config fingerprint, zero pending migrations
   and preservation fingerprints again. Stop on any unexpected difference. If
   approval is delayed, refresh the backup before deployment as necessary.
2. Enable Development maintenance for the controlled release window. Do not
   change config vars, formation, Stripe resources, subscriptions or plan flags.
3. Push only the approved commit to the Development Heroku Git target. Its Git
   `main` ref currently points to `e3edaf987fac109c01b0089c3111382ac01af9a1`,
   while the running v73 slug is `6583bd60`. The reviewed release is based on the
   running slug. A lease-guarded force update of this deployment-only Git ref is
   required; stop if the ref differs from the recorded value. Do not push to
   Production or GitHub branches. Record the resulting release and slug.

   ```sh
   git push --force-with-lease=refs/heads/main:e3edaf987fac109c01b0089c3111382ac01af9a1 heroku-development APPROVED_COMMIT:refs/heads/main
   ```
4. Require the existing `python src/manage.py migrate` release hook to succeed
   with no migrations applied. Confirm the released SHA and normal Gunicorn
   worker startup; do not introduce allocator, GC or application workarounds.
5. Run read-only deployed Django checks and migration-graph verification; verify
   the three current EUR TEST Prices with candidate code and all tiers inactive.
   Reconcile all baseline database tables, Stripe subscriptions, invoices,
   Prices and config; verify Business 166's local legacy access and SERVICE
   billing configuration. Do not repair drift automatically.
6. Reopen Development only after those checks pass. Run desktop/mobile browser
   smoke checks for public pricing, SERVICE registration/login, Logistics
   registration with inactive-tier behavior, legacy exclusion, static assets and
   private-page redirects. No valid registration, Checkout Session, payment or
   signed webhook delivery is created by this deployment.
7. Monitor normal Gunicorn logs and HTTP responses for at least two minutes.
   Stop and report any unexpected data/config drift, failed hook/check, worker
   crash, timeout or application runtime failure. Retain the evidence.

## Rollback and failure boundary

Current rollback release: **v73**, slug
`a9bbdae0-c611-430b-94cb-25f022164e3e`, code `6583bd60`.
If a failure occurs, stop the rollout and report it; keep or restore maintenance
as containment. Prepared operator recovery command:

```sh
heroku rollback v73 --app mm-development-app
```

Rollback copies the earlier slug and config, so compare current configuration
with the preserved v73 fingerprint before using it. It does not restore database
or Stripe state. See [Heroku rollback behavior](https://devcenter.heroku.com/articles/releases#rollback).
No automatic database restore, Stripe repair, subscription reassignment or tier
activation is authorized. Use the preserved backup only under a separately
reviewed database recovery instruction.

## Remaining TEST gates

This deployment keeps every tier inactive and leaves USD tier Checkout disabled.
Core activation requires separate approval. The first fictional Core EUR payment
and real signed-webhook delivery remain subsequent verification steps. Historical
orphan reconciliation is separate work; this release does not adopt those
subscriptions into current tiers.
