# Logistics usage dashboard and monitoring — Block D

Built on the retained, uncommitted A–C work on `feature/mm-testing-phase`.
Block D adds usage visibility and nonblocking monitoring, without activating
prices, changing subscriptions, resetting labs, or implementing E/F.

## UI and permissions

The existing Subscription page now shows Logistics plan name, catalog annual
price in the subscription currency, seven operational usage cards, UTC month/reset
dates, and a distinct monitoring/planning section. Annual prices come from the
existing pricing configuration; absent USD prices remain unconfigured.

Owners retain the existing billing controls. Logistics admins can open the same
URL as a read-only usage page, with no billing actions; POST remains owner-only.
SERVICE admin access is still denied. Staff/accountants cannot access this page.
Navigation exposes the usage link to Logistics owners/admins without changing
the existing owner-only billing/recovery role flag. Location/record permissions
are unchanged; these are authorized business-wide aggregates.

All seven metrics show count, resolved allowance and percentage. Unlimited legacy
allowances display **Unlimited**, with percentage **Not applicable**. Unavailable
effective entitlements display **Unavailable**, including missing/incompatible or
inaccessible subscriptions. A malformed usage counter shows **Unknown**, rather
than zero. Zero allowances show **No capacity**, avoiding division by zero. Bars
cap visually at 100%, while numeric utilization can exceed 100%.

Staff seats include the owner and reserved distinct pending invitations, matching
C's consuming-action boundary; supporting text separates active accounts from
reserved seats. Active locations, Clients and Services use C's definitions. The
Logistics page omits SERVICE-only appointments/public-booking usage, manual SERVICE
plan cards, misleading trial prompts and the empty SERVICE-plan warning.

Browser screenshots use a disposable Core fixture with its actual capacities,
including 200/250 Clients at the 80% threshold:

- [Desktop, 1440px](screenshots/logistics-block-d-desktop.png)
- [Mobile, 390px](screenshots/logistics-block-d-mobile.png)
- [Admin mobile read-only view](screenshots/logistics-block-d-admin-mobile.png)

Chromium/Playwright checked ten metric cards, threshold copy, mobile horizontal
overflow, absence of admin billing forms and JavaScript page errors. Screenshots
were inspected. No existing application database or customer account was used.

## Usage and measurement architecture

`logistics.subscription_usage.logistics_subscription_usage()` produces one bounded,
read-only snapshot per page/monitor invocation. It reuses the central effective
`resolve_business_plan_limit()` and C's counters; no new entitlement system exists.
The collector's query-bound test permits at most sixteen queries and verifies
initialized creation counters do not trigger Parcel/Shipment/Invoice recounts.
No cross-request cache hides changes or leaks tenant data.

| Signal | Measurement and semantics |
| --- | --- |
| Staff, active locations/Clients/Services | Existing indexed tenant counts and C's deduplicated invitation reservations |
| Parcels/Shipments/Invoices per month | C's persisted creation counters; legacy uses indexed UTC ranges; deletion never refunds C-metered creations |
| ParcelEvents | Persisted valid, same-business events by immutable `timestamp` in `[UTC month start, next start)`; includes STATUS and NOTE events |
| Transactional email total | **Not measured**: no comprehensive tenant-attributed delivery ledger/receipts exists |
| Attributable email subset | SENT SubscriptionNotification rows with `sent_at` in UTC month and matching business/subscription ownership; successful backend acceptance, not delivery confirmation |
| Private storage | **Not measured**; 1/3/6 GB are informational planning allowances, with no request-time scans |
| Database size | Optional command-only PostgreSQL `pg_database_size(current_database())`; whole database bytes, not per-business storage or a cost |
| Tracking traffic | Structured logging of tracking lookup function outcomes/durations; excludes throttled requests that never call lookup, and contains no bearer codes/IPs |
| PDF and manifest generation | Structured success/error/duration signals for Logistics Invoice PDFs, shipping-label PDFs and manifest generation; no document contents |

ParcelEvent counts have a new `(business, timestamp)` index. Existing unique
event retry keys/domain services avoid a second event for an idempotent replay.
The new code never changes event history or blocks events, arrival, delivery,
cancellation, scanning or status transitions because of a monitoring budget.
Its fair-use percentages are displayed separately from hard limits, and only
hard-limit rows generate warning outbox entries.

Email queued/processing/failed records and SENT records without a completion
timestamp do not count in the supported subset. Completed retries count once per
outbox row; SENT rows cannot be reclaimed by the existing dispatcher. SMTP/provider
acceptance is not proof of delivery. An acceptance followed by a process/database
failure remains the existing at-least-once delivery ambiguity: without provider
receipts, physical retry duplicates cannot be measured exactly. Invoice emails,
invitations, security mail and other non-outbox flows are not silently included
in that subset. The main total and utilization remain **Not measured**, with the
configured 300/900/1800 allowance shown separately. Nothing blocks essential mail.

Storage audit found no tenant-owned FileField/ImageField or reliable byte ledger;
CSV upload forms are not storage ownership metadata. Import previews are database
records, PDFs are generated on demand, and test-lab handoff/temporary files do not
form a complete tenant storage inventory. Default file storage and WhiteNoise
static assets are distinct from customer-private storage. No storage enforcement,
object-listing request or synthetic zero-byte measurement is added.

`Motionmate_Pricing_Simulation_With_Logistics.xlsx` was not present in the checkout
or provided attachments. Section 7 of the supplied pricing specification does
provide the following planning inputs. They are **unverified assumptions**: they
have not been reconciled against the unavailable workbook or current vendor prices.

| Supplied planning input | Unverified assumption |
| --- | --- |
| Heroku Basic web dyno | USD 7/month |
| PostgreSQL Essential-2 | USD 20/month |
| Other fixed infrastructure initially | USD 0/month |
| Stripe EEA payments | 1.5% + EUR 0.25/payment |
| Stripe Billing | 0.7% of subscription revenue |
| Postmark | USD 15/month including 10,000 emails |
| Postmark overage | USD 1.80/1,000 emails |
| Amazon SES Essentials | USD 0.16/1,000 emails |
| Support/operations reserve | 10% of revenue |
| Target contribution margin | 80% |
| FX planning input | USD 1 approximately EUR 0.855 |

The same specification supplies shared SERVICE infrastructure budgets of USD
27/45/80/135/245 per month for 1–25/26–100/101–250/251–500/501–1,000 businesses,
respectively, and future Logistics sensitivity cases of 2×/3×/5× those budgets.
These remain unverified planning inputs, not measured costs or a Block F financial
simulation. Annual subscription revenue must remain distinct from monthly cash
receipts; the FX input does not define USD subscription prices.

Catalog prices, measured signals and financial estimates remain separate. No
actual infrastructure costs or per-request costs are inferred. Operators can
compare database-byte snapshots over time and aggregate existing console logs;
no external observability service is required.

## Warnings and outbox behavior

Dashboard warnings appear immediately at exact 80% and 100% hard-capacity
thresholds, using integer comparisons rather than rounded percentages. Essential
accepted-work operations retain their original authorization and lifecycle rules.
The dashboard performs no notification enqueue or send on GET.

`monitor_logistics_usage` reuses the SubscriptionNotification outbox. It defaults
to read-only discovery; `--enqueue` explicitly creates pending warnings without
sending. Existing `send_subscription_notifications` performs delivery/retries.
Active owners/admins with active user accounts are the recipients.

Unique keys contain business, metric, UTC reporting month, threshold and recipient
email digest. This gives one notice per recipient/threshold/month, including
concurrent discovery. Active-record quotas do not reset monthly; their warning
cadence is monthly. Monthly creation counters reset on the displayed UTC boundary.
Dropping below and recrossing the same threshold within a month does not re-email.
First discovery at/above 100% queues the 100% warning only, rather than two emails.

Delivery revalidates recipient membership/role/email, tenant/subscription identity,
reporting month, current allowance and threshold. Resolved, stale or unauthorized
warnings are cancelled. Verification errors mark only that warning failed, rather
than aborting notification dispatch. Existing atomic claims and SENT-state guards
prevent concurrent workers from sending the same outbox row twice. No provider
exactly-once guarantee is claimed across the existing external-send/DB-commit gap.
The dispatcher prioritizes ordinary subscription/billing mail ahead of usage
warnings, keeping the original chronological order within each group. Capacity
warnings cannot consume a limited batch ahead of essential billing mail.
SERVICE notification type behavior and reminder scheduling remain unchanged.

Examples for an operator-selected environment, not executed against a deployment:

```sh
python src/manage.py monitor_logistics_usage --limit 100
python src/manage.py monitor_logistics_usage --business-id <ID> --database-size
python src/manage.py monitor_logistics_usage --limit 100 --enqueue
python src/manage.py monitor_logistics_usage --after-business-id <LAST_ID> --limit 100 --enqueue
python src/manage.py send_subscription_notifications --limit 50
```

Schedule warning discovery explicitly using the existing scheduler/command runner.
No scheduler, sender, deployment or customer subscription was activated here.
For more than 100 businesses, paginate with `--after-business-id`, using the last
business ID printed, or schedule explicit tenants. The bounded default command
does not promise to scan all businesses automatically.

## Files and migrations

New files:

- `src/apps/logistics/subscription_usage.py`: shared read-only commercial snapshot.
- `src/apps/logistics/usage_warnings.py`: deduplicated discovery and stale-recipient checks.
- `src/apps/logistics/monitoring.py`: privacy-safe, nonblocking logging hooks.
- `src/apps/logistics/management/commands/monitor_logistics_usage.py`: operator snapshots/outbox discovery.
- `src/apps/logistics/test_subscription_usage.py`: nineteen monitoring/permission/delivery tests, including PostgreSQL races.
- `src/templates/businesses/logistics_usage.html` and two
  `src/templates/businesses/includes/logistics_usage*.html` partials.
- This report and the three screenshots.

Extended files:

- `businesses/views.py`, `context_processors.py`, subscription template and shared
  dashboard navigation: Logistics-only display/admin access; owner billing retained.
- `businesses/models.py`, `subscription_notifications.py`: one additional outbox
  notification choice, email count index, warning relevance/content and acceptance signal.
- `businesses/usage_limits.py`: optional seat-count breakdown for presentation,
  retaining C's default integer contract and enforcement semantics.
- `businesses/management/commands/send_subscription_notifications.py`: preserve
  billing-mail priority over nonessential usage warnings.
- `logistics/models.py`: ParcelEvent range index.
- `logistics/usage.py`: documentation distinguishes existing business-local
  operational reports from the commercial UTC-month snapshot; no behavior change.
- `logistics/public_tracking.py`, `shipping_labels.py`, `shipment_services.py`,
  `billings/pdf.py`: existing-operation timing/outcome signals; original errors propagate.

Additive migrations, after C:

1. `businesses.0031_logistics_usage_monitoring`: notification choice and
   `(business, status, sent_at)` outbox index.
2. `logistics.0024_logistics_usage_monitoring`: `(business, timestamp)` event index.

There is no data migration, subscription reassignment, price/credential update,
new storage table or counter reset. No D migration was applied to the existing
local database by this work. Application-data checks used READ ONLY transactions;
all mutation/migration/seed tests used disposable databases.

## Validation and runtime investigation

| Check | Result |
| --- | --- |
| Final focused A–D compatibility, usage/outbox and existing sender-command tests, PostgreSQL 14 UTF-8 | 88 tests, OK; eleven concurrency tests executed |
| Same final focused suite, SQLite | 88 tests, OK; eleven PostgreSQL-only skips |
| SERVICE accounts/businesses/CRM/billings/appointments/notifications | 1022 tests, OK; seventeen PostgreSQL-only skips |
| Chromium desktop/mobile/admin checks | Passed; 390px viewport without horizontal overflow, no JavaScript page errors |
| Extended Test Lab/PDF/barcode/checkout/usage suite, ordinary allocator | 156 tests, OK; three PostgreSQL-only skips |
| Full Logistics diagnostic run, `PYTHONMALLOC=debug`, faulthandler | 916 tests, OK; 64 skipped; completed in 1103.669 seconds |
| Ruff, Black, Django checks, migration drift, whitespace | Passed |

Focused tests cover all seven 80%/100% thresholds; UTC boundaries/reset dates;
legacy unlimited versus missing/inaccessible allowance; no GET enqueues; recipient,
period and threshold deduplication; concurrent discovery/claim; failure/retry/SENT
accounting; stale/former-admin notices; ParcelEvent over-budget operations/replays;
storage fallback without scanning; bounded queries; read-only command defaults;
privacy-safe logs and logging failures; owner/admin/staff/SERVICE/tenant access.
A–C tests also retain CSV unlimited semantics and exact lab migration snapshots.

Raw logs are `/tmp/logistics-block-d-postgresql-verified.log`,
`/tmp/logistics-block-d-sqlite-complete.log`, `/tmp/logistics-block-d-service.log`,
`/tmp/logistics-block-d-dataset-final.log`,
`/tmp/logistics-block-d-logistics-debug-final.log`, and
`/tmp/logistics-block-d-browser-final-verified.log`. Static checks are saved in
`/tmp/logistics-block-d-checks-final.log`. PostgreSQL used a separate UTF-8 cluster,
which was stopped after validation. Test mail/providers and account hashes are
isolated; provider operations are mocked or use the test mail backend.

Initial failing checks were retained: a cached Django timestamp-default test clock,
a Decimal/float comparison, an overly broad SQL assertion matching an expected
event-to-Parcel join, and a SQLite-only expected database-size fallback reused on
PostgreSQL. Fixture/assertion fixes did not weaken business checks. Browser setup
used the installed Chromium executable after the default Playwright revision was
unavailable; a fixture DB update was moved out of Playwright's event-loop thread.
The initial broad diagnostic was interrupted after 119 tests when its already-loaded
fixture needed correction; that partial run is not claimed as a full pass.
The complete diagnostic was restarted, without disabling any tests, GC, middleware,
native PDF rendering or QR/Code128 decoding.

The preceding C broad run exited 139 during GC in scanner middleware/WhiteNoise
header construction; A had a different GC/query stack. The native cause was not
established. The completed D diagnostic used CPython's debug allocator and
faulthandler: `Ran 916 tests in 1103.669s`, `OK (skipped=64)`. It retained the
entire suite and all assertions. The ordinary-allocator extended subset also
passed (156 tests, three skips), but neither result proves that the full suite
passes under the ordinary allocator. The recurring ordinary-runtime GC
segmentation fault remains **unresolved**, with no verified native root cause or
fix. No tests, GC, middleware or native rendering were disabled to obtain the pass.

## A–D diff review and handoff readiness

The documentation handoff review inspected branch `feature/mm-testing-phase` at
`216aa7d`: 25 modified tracked files, 29 untracked files, and no staged changes.
The new files are the A–D reports, three disposable-fixture screenshots, eight
migrations, and the expected quota/monitoring implementation, templates and tests.
No stray dumps, database files, credential handoffs or test-log artifacts were
found among the untracked files. A scoped secret-pattern scan found no matching
provider secrets, private keys or credential-bearing database URLs. Screenshot
metadata was empty. Formatting-only hunks were left intact; no implementation
files were changed or discarded during this documentation pass.

Read-only inspection of the local database `taskio_database_dev` confirmed a
consistent migration history, no graph conflicts and no model-to-migration drift.
The six A–C migrations in this diff are already applied locally. Only
`businesses.0031_logistics_usage_monitoring` and
`logistics.0024_logistics_usage_monitoring` remain pending; the latter depends on
the former. D adds indexes and a notification choice, with no data migration.
B's existing guarded plan seed defines inactive plans without changing existing
subscriptions or Stripe records. Deployed migration states were not inspected.

The A–D changes are ready for commit review, including explicit inclusion of the
untracked source, migrations, reports and screenshots. The local D migrations are
ready for an operator-reviewed backup and index-build window. This documentation
pass applied no migrations, reran no broad tests, made no commit and started no
Block E work. Ordinary-runtime GC diagnosis and validation of financial assumptions
remain outstanding; email/storage measurement limitations remain as described above.

## Deployment, rollback and Block E prerequisites

Back up and inspect the target database/migration plan. Apply the two additive
migrations during an appropriate index-build lock window, then deploy web/workers.
Keep the three new plans and Stripe checkout inactive. Verify legitimate owner/
admin usage pages and default read-only discovery before deliberately scheduling
`--enqueue` and the existing sender. Do not run lab reset/seed commands or alter
subscription/provider metadata as part of this release.

To roll back D, stop usage-warning discovery and pause the sender. Allow in-flight
claims to finish, then drain or cancel **only** pending/failed
`logistics_capacity_warning` rows in a reviewed operator action before an older
sender that cannot render that type starts. Review any remaining PROCESSING
warnings separately; keep SENT audit records. Preserve ordinary billing
notifications and C's usage counters/guards. Retain additive indexes/choices where
possible; a schema rollback is unnecessary for the previous code. Reverting D
does not require subscription or Stripe changes. No operator action is automated.

Remaining measurement boundaries are explicit: total email delivery and private
storage are not measured; database bytes are shared; logs require operator
aggregation/retention; periodic warnings require scheduling; the native GC fault
requires separate diagnosis. No request count is converted into an infrastructure
cost. Privileged SQL/fixture loaders remain outside C's application writer boundary.

Block E must approve annual tier/currency pricing and real TEST-mode Price IDs,
extend validated checkout/enrollment/webhook mappings together, preserve legacy
contracts, verify renewal/grace/recovery behavior, and coordinate any tier movement
with C's locked usage/baseline rules. USD pricing remains an explicit commercial
decision. Obtain the workbook and verify the supplied planning inputs before
financial sensitivity/cost conclusions.
Provider delivery receipts and a tenant-owned storage inventory are prerequisites
for complete future email/storage measurement, not reasons to block essential work.
No E/F implementation or activation is part of this change.
