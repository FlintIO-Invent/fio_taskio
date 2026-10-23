# Logistics Test Lab acceptance and promotion V2

This procedure validates the [06A foundation](logistics_test_lab.md) and
[06B connected dataset](logistics_test_lab_dataset.md). It does not deploy,
approve a release, provision Production, modify roles/passwords/subscriptions,
or copy databases. Missing evidence and failed checks block promotion.

## Commands and evidence

```bash
python src/manage.py accept_logistics_test_lab --help
python src/manage.py accept_logistics_test_lab \
  --environment local --business-id <owned-ID> --target development
```

Default inspection makes zero database writes. It verifies the exact owned lab,
foundation roles/grants/entitlement, dataset counts and fingerprints, reset
dependency/financial guards, all nine location querysets, and migrations. It
reports the application, database name/vendor/fingerprint, commit/release,
working-tree digest, configuration digest, fixture versions, business ID,
account identities/roles/sites, login results, operational counts/states,
verification limitations, remaining checks, approval and verdict.

Read-only output has `login_http=PENDING`. Explicit login execution requires the
same app/database opt-in and exact confirmations as provisioning:

```bash
python src/manage.py accept_logistics_test_lab \
  --environment local --business-id <owned-ID> --target development \
  --execute --confirm-business-id <owned-ID> \
  --confirm-database <configured-fingerprint> --reason-reference <QA-reference> \
  --credential-file /secure/local/credentials.age \
  --credential-identity /secure/local/identity.txt \
  --output /secure/local/acceptance-login.json
```

Shared environments also require `--confirm-app` and a confirmed, separate
PostgreSQL connection. Production/unknown environments are hard rejected before
credential access. Only the owned lab can be selected; business 133 is excluded.
Existing report paths are refused. JSON reports are created with mode 0600.

Credentials are decrypted into RAM, never console output, logs, documents,
browser traces/HAR, or plaintext files. Both inputs must be operator-owned
private files in a 0700 directory. Repeat `--credential-file` for the existing
owner bootstrap and eight-account handoffs; they are combined only in RAM.
The private identity must decrypt both. Use the existing password manager if
different recipients were originally selected. No password rotation is required
by acceptance. Controlled rotation remains exclusively the guarded 06A command;
`.test` email reset delivery is unavailable.

The execute mode uses normal Django HTTP login with CSRF validation, checks the
selected lab session, and performs normal logout. It updates `last_login`,
creates/destroys sessions, and retains an `acceptance-logins` audit reference.
It does not run over the deployed HTTPS router. Operator browser acceptance is
a separate requirement for shared environments.

## Isolated automated suites

Install project development dependencies, Playwright/Chromium, `age`/`age-keygen`,
Node and OpenSSL. Select a disposable Local test base database, never a customer
database. Django creates an independent test database; no database is copied.
The runner uses a fast password hasher exclusively inside the test runner.
Real lab password hashes are not changed.
Use PostgreSQL for the Logistics promotion suite too: existing race classes also
live in workflow modules. SQLite runs remain useful regressions, but their
PostgreSQL-only skips prevent passing promotion evidence. The PostgreSQL suite
includes these embedded race classes as well as the dedicated concurrency files.

```bash
export ENV=local DEBUG=True LOGISTICS_LOCAL_BILLING_BYPASS=False
export DATABASE_URL='<disposable local SQLite or PostgreSQL URL>'
export PWA_CHROMIUM='<installed Chromium executable>'
python scripts/run_logistics_test_lab_acceptance.py \
  --suite logistics --output-dir /secure/qa/logistics
python scripts/run_logistics_test_lab_acceptance.py \
  --suite service --output-dir /secure/qa/service
python scripts/run_logistics_test_lab_acceptance.py \
  --suite browser --output-dir /secure/qa/browser
python scripts/run_logistics_test_lab_acceptance.py \
  --suite pwa --output-dir /secure/qa/pwa
# Actual PostgreSQL URL and CREATEDB privilege are required for this suite.
python scripts/run_logistics_test_lab_acceptance.py \
  --suite postgresql --output-dir /secure/qa/postgresql
```

Every output directory must be new. Raw `tests.log` and `results.json` are private
artifacts with test counts, failures/errors/skips, exit code, database vendor,
commit/tree identity and raw-log SHA256. Zero tests, skipped tests, and failed
processes do not produce a passing evidence entry. Keep code unchanged throughout
the suite runs and report collection; rerun affected suites after code changes.

The Logistics suite includes normal nine-account login, route/POST/export/scan
authorization, all 40 scanner resolutions for each account, role management,
CSRF, foreign tenant/site requests, public tracking allowlists/throttling,
subscription guards, valid/invalid/stale transitions, duplicate scans,
shipment propagation and manifests, invoice accuracy, event actor/site integrity,
sender/recipient snapshots, Tracking Code V2 and raster-decoded labels, guarded
reruns/reset and real financial preservation. The connected workflow creates
its additional records only in the isolated test database.

The SERVICE suite runs accounts, businesses, CRM, billing and appointments:
registration, dashboard, clients/services/requests, scheduling, online booking,
invoices, roles, billing/Stripe adapters and existing SERVICE demo seed/reset.
Mocked Stripe tests verify application behavior, not provider readiness.

The PostgreSQL suite exercises real competing transactions for enrollment,
registration, events, metadata, shipment membership/dispatch, invoice/charge
creation, revocation/deactivation, work-location selection, cleanup locking,
foundation provisioning and dataset seeding. The runner consistently restores
data-migration fixtures between transactional/browser cases. No application
permission or lifecycle guard is disabled.

Browser checks use normal login for all nine independently provisioned fixture
accounts at 390px and 1440px, plus existing checks at 320/390/768/1440px. They
cover navigation, lists/details, scanner input/duplicate/retry/offline handling,
site selection, labels/PDF/Chromium print-to-PDF, shipment forms and invoices,
session/logout, synthetic camera permission/cleanup and real pixel decoding.
PWA checks actually install/launch/uninstall Chromium apps in temporary profiles,
exercise offline navigation and verify that only the public shell enters Cache
Storage. Pixel/iPhone/iPad profiles and synthetic media remain emulation.

## Assemble a report without inventing manual passes

Run inspection after the reviewed code and approved configuration are fixed.
Collect only successful matching suite artifacts:

```bash
python scripts/collect_logistics_test_lab_evidence.py \
  --report /secure/local/acceptance-login.json \
  --suite-dir /secure/qa/logistics --suite-dir /secure/qa/service \
  --suite-dir /secure/qa/browser --suite-dir /secure/qa/pwa \
  --suite-dir /secure/qa/postgresql \
  --operator '<accountable operator>' --output /secure/local/automated-evidence.json
```

The collector verifies raw-log digests, matching code and complete zero-skip
results. It does not attest physical devices, HTTPS, Stripe, deployed cache/proxy,
database separation, deployed browsers or promotion approval. A changed code
digest requires new evidence. Pending template entries can be generated with
`--evidence-template` instead of `--execute`. Evidence is valid for seven days,
requires an aware timestamp, exact environment/database/business/version/code/
configuration binding, and an accountable operator plus private reference.
Inspection and login results cannot be overridden by supplied evidence.
Keep the Test Lab opt-in and approved settings identical during inspection,
evidence collection and login execution. Configuration changes invalidate the
binding and require a fresh inspection/evidence file.

Add operator entries to that evidence file only after performing the checks
below, using the required kind from the template. Keep raw private evidence out
of Git/public CI artifacts. Provider/device entries are attestations whose
references reviewers must inspect; the tool does not authenticate their truth.
Replay the login command with `--evidence-file` and a new `--output` path to
generate the final report. Approval binds the exact commit and configuration;
it grants no database or application permission. A dirty/unidentified release
remains blocked regardless of operator overrides.
Use `--require-ready` in a promotion job to write the report and exit nonzero
when its verdict is BLOCKED. Interrupted/incomplete suites and executable code
changes during a run are also rejected. Documentation updates do not change the
executable-input digest; the commit/dirty-release checks still include Git state.

## Operator checks and promotion gates

| Check | Evidence to record |
| --- | --- |
| Deployed release | Same reviewed 40-character Git SHA and immutable release; clean Local tree. Enable trusted runtime commit/release metadata in Heroku. |
| Database separation | App/add-on/database identities and fingerprints for both environments; verify separate PostgreSQL databases and independently applied migrations. |
| Deployed browsers | All nine normal logins; each role's dashboard, list/detail, direct URL, forbidden POST, scanner lookup, PDF/manifest export; regional switching and unassigned restrictions. |
| Workflow | Create disposable, clearly identified acceptance cargo with repeated bill-to and distinct sender/recipient; register, scan/intake, dispatch, intermediate handling, receive/deliver, manifest and accurate draft invoice. Confirm actor/site history and stale/duplicate rejection. |
| HTTPS/PWA | Real HTTPS origin and cookies/CSRF; install/launch, rotate viewport, offline navigation, rejected offline writes, reconnect, logout/back navigation; inspect Cache Storage/HTTP cache for private payloads. |
| Cache/proxy | Actual shared Redis/Memcached atomic throttle across web processes; missing/unreachable cache fails closed; verify trusted router/socket identity and spoofed forwarding headers. Existing opt-in Redis tests use an isolated key prefix, not a cache flush. |
| Stripe TEST | Correct `sk_test_`/`pk_test_` configuration; legitimate test checkout, authenticated webhook activation, retries/idempotency and normal subscription/seat access. Record private provider evidence, never keys. A separately approved test entitlement does not prove checkout/webhooks. |
| Android | Physical model, OS/browser/version, camera permission, rear-camera behavior, QR and Code 128, orientation, network loss/recovery and installed PWA/logout. |
| iPhone | Physical model, iOS/browser/version, camera fallback decoding, QR and Code 128, orientation, install/offline/session/logout. Chromium's iPhone profile does not satisfy this check. |
| Label printing | Actual 4x6 printer/model/DPI/settings, printed sample, physical QR/Code128 scan from both devices; correct dimensions, quiet zones and readable party/tracking details. PDF/raster tests do not satisfy printing. |
| Approval | Reviewer/operator, exact SHA/configuration, environment, private change/acceptance reference, no unresolved high-severity failures, and promotion decision. |

Reset tests run only in isolated test databases. On a deployed lab, operator
workflow edits/new dependents deliberately cause the ownership reset guard to
refuse. Inspect and retain real financial data; do not bypass fingerprints,
delete genuine invoices, dispatch invoice emails or change subscription state to
make acceptance pass. Rebuild only after the existing guarded cleanup permits it.
Create fresh acceptance Clients and cargo for operator workflows. Keep the owned
scenario records intact so final inspection can verify their fingerprints and
safe reset independently of additional operator records.

Local -> Development requires the automated suites, all nine current logins,
location checks, safe fixture reset, browser/PWA checks, SERVICE regressions,
migrations and reviewed release/configuration approval. Development -> Staging
additionally requires actual PostgreSQL concurrency, independent app/database,
HTTPS, deployed browsers, shared cache/proxy and Stripe TEST verification.
Staging -> Pilot additionally requires physical Android/iPhone, QR/Code128 and
4x6 printing evidence. Any failed reported check blocks promotion. No minor-debt
classification is inferred automatically; mandatory safety checks cannot be debt.

Promote only the reviewed commit, migrations, fixture definitions/versions,
automated tests and approved configuration. Provision fresh independent 06A
accounts/passwords and 06B cargo per environment. Do not promote databases,
users/password hashes, actual tracking codes, record IDs, Stripe records or
customer data. Development is `mm-development-app`; Staging needs a dedicated,
configured non-production app and separate database. Do not use Production.

## Current environment acceptance record

This implementation is an uncommitted working tree based on
`a8be35a80c327265b9ac2547995809095e778f3e`. That parent SHA is not a reviewed release
of these changes. The current generated Local JSON report is the authoritative
inventory and per-account result; raw suite logs distinguish final passes from
earlier failed test setup runs.

| Required field | Local | Development | Dedicated Staging |
| --- | --- | --- | --- |
| Application/database | Local 8016; private isolated `lab.sqlite3`, Business 1 | `mm-development-app`; PostgreSQL `dat1puvumvgotr`, addon `postgresql-curved-15458` verified read-only | App/database not configured/verified |
| Release/migrations | Working tree; 0019 applied independently | Live v53; 0001-0018 applied, these changes/0019 not deployed; runtime SHA unavailable | Not deployed/verified |
| Fixture versions | `motionmate-logistics-test-lab-v2`, `motionmate-logistics-test-dataset-v2` | Same definitions required; independent provisioning unverified | Same definitions required; independent provisioning unverified |
| All nine login results | Recorded independently in Local JSON | All nine PENDING | All nine PENDING |
| Dataset | 12 Clients, 40 Parcels, 10 Shipments, 179 Events, 12 draft Invoices, 24 Lines/Charges | Counts unverified | Counts unverified |
| Role/site/scanner/label | Automated and Chromium evidence; physical checks PENDING | PENDING | PENDING |
| Stripe TEST | Existing guarded Local bypass; provider verification PENDING | PENDING | PENDING |
| SERVICE | Current isolated suite evidence | Deployed regression PENDING | Deployed regression PENDING |
| Physical devices/printing | PENDING | PENDING | PENDING |
| Approval/verdict | BLOCKED pending reviewed release/approval | BLOCKED pending independent acceptance | BLOCKED; NOT READY FOR SUPERVISED PILOT |

No shared-environment, real Stripe, physical-device or printer acceptance is
claimed by implementation or emulator results. Block 06C adds no schema migration;
fresh environments must independently apply the existing 06A migration 0019.
The actual Local browser run exercised all nine accounts at both 390px and
1440px (18 sessions), including scanner lookup, labels/PDF, forbidden details,
private cache headers and logout. Public tracking remains unavailable on the
pending Local Stripe subscription; the existing Local bypass authorizes private
operations only. Public tracking acceptance needs legitimate active entitlement.

Development's runtime `ENV=development` and connected database were checked
read-only. No reserved lab business exists, Test Lab opt-in is disabled, and its
Staging app setting is empty. No Development migrations, provisioning, customer
records, subscriptions, passwords or permissions were changed. Metadata checks
do not constitute Development workflow acceptance.

## Completed automated verification

All five final suites used unchanged executable inputs with digest
`cfcad8833c4450fc5def509f58d88bc6f17c9f8cdcf1ed6ae53a719c6bede175`.
Each completed every planned test, with zero failures, errors, skips or interrupts.

| Suite | Passed | Private raw log |
| --- | ---: | --- |
| Logistics, actual PostgreSQL | 724 | `/tmp/logistics-acceptance-logistics-complete/tests.log` |
| SERVICE, isolated SQLite | 927 | `/tmp/logistics-acceptance-service-complete/tests.log` |
| Dedicated PostgreSQL concurrency | 40 | `/tmp/logistics-acceptance-postgresql-complete/tests.log` |
| Browser, isolated fixture DB | 12 | `/tmp/logistics-acceptance-browser-complete/tests.log` |
| PWA/privacy/offline/installation | 11 | `/tmp/logistics-acceptance-pwa-complete/tests.log` |

Concurrency cases embedded in the Logistics suite also run in the dedicated race
suite; these counts are executions, not a sum of unique tests. Earlier failed,
interrupted or code-changing runs are excluded from collected passing evidence.
Django check, migration-drift check, command help, Ruff, Black and Git whitespace
checks passed. No new Block 06C schema migration is required.

Private 0600 reports and collected evidence are in
`/home/mzero/.local/share/motionmate-logistics-test-lab/local/`:
`local-acceptance.json`, `development-acceptance.json`,
`staging-acceptance.json`, and `acceptance-automated-evidence-v2.json`.
`live-browser-results-v2.json` records the 18 real Local browser sessions.
No passwords or hashes are included in these reports. The final Local report has
all nine logins and mandatory automated checks passing; its remaining promotion
blockers are the dirty/unreviewed release and missing operator approval.
