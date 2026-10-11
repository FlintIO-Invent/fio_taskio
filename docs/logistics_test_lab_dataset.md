# Connected Logistics Test Dataset V2 (Block 06B)

This command adds cargo to the **owned Block 06A Motionmate Global Cargo lab**.
It never creates accounts, changes passwords or grants, updates the LogisticsProfile,
activates subscriptions, dispatches invoices, sends email, or contacts Stripe.
Use the existing [foundation credentials and environment setup](logistics_test_lab.md).
SERVICE `seed_demo_data` and existing `seed_logistics_demo_data` remain separate.

## Definition and actual domain counts

`src/apps/logistics/test_lab_scenarios.py` is the single version-controlled definition:
`motionmate-logistics-test-dataset-v2`. It defines stable customer and scenario keys.
Identifiers such as `parcel/miami-sea-delivered/01`,
`shipment/port-warehouse-handoff`, and `event/miami-sea-delivered/01/02` remain
the same when independently recreated in another database. Primary keys, shipment
references, invoice numbers, dates and secure Tracking Code V2 values are generated
independently through the normal services. No database copying is needed.

| Record | Count |
| --- | ---: |
| Fictional Clients | 12 |
| Parcels | 40 |
| Shipments | 10 |
| ParcelEvents | 179 |
| Draft Invoices | 12 |
| InvoiceLines | 24 |
| LogisticsCharges | 24 |
| Invoice creation ActivityLogs | 12 |
| Approved intermediate handling sites | 2 |
| Existing operating locations | 4 |
| Existing accounts | 9 |

Counts are checked after executing domain services. Unexpected domain behavior
rolls back the entire operation rather than forcing states or counts.

| Stable shipment scenario | Route | Mode | State | Members |
| --- | --- | --- | --- | ---: |
| miami-sea-delivered | Miami → Sint Maarten Port | SEA | COMPLETED | 4 |
| miami-sea-moving | Miami → Sint Maarten Port | SEA | IN_TRANSIT | 4 |
| port-warehouse-handoff | Sint Maarten Port → SXM Distribution Center | ROAD | COMPLETED | 4 |
| dominica-sea-arrival | Sint Maarten Port → Dominica | SEA | ARRIVED | 4 |
| local-sxm-ready | SXM Distribution Center → local SXM collection | ROAD | READY | 4 |
| miami-air-booking | Miami → Sint Maarten Port | AIR | DRAFT | 4 |
| dominica-sea-ready | Sint Maarten Port → Dominica | SEA | READY | 4 |
| miami-cancelled-booking | Miami → Sint Maarten Port | SEA | CANCELLED | 0 after cancellation |
| sxm-road-moving | Sint Maarten Port → SXM Distribution Center | ROAD | IN_TRANSIT | 2 |
| miami-air-arrival | Miami → Sint Maarten Port | AIR | ARRIVED | 2 |

Cancellation releases four RECEIVED parcels through the normal shipment service;
it does not cancel their cargo. Two additional ungrouped parcels are cancelled
before intake. The remaining two parcels travel Miami → Sint Maarten → Dominica:
an approved EXPECTED stop records arrival, transshipment inspection HOLD, release
to IN_TRANSIT and destination arrival. School supplies are delivered; repair supplies
remain READY for pickup. These are individual parcel journeys;
the existing shipment lifecycle does not support reassignment of arrived cargo into
a second shipment. No new shipment lifecycle or override was introduced.

Parcel states: DELIVERED 9, READY 1, IN_TRANSIT 6, ARRIVED 6, RECEIVED 12,
REGISTERED 4, CANCELLED 2. HOLD occurs as a valid intermediate inspection event.
Shipment states: COMPLETED 2, IN_TRANSIT 2, ARRIVED 2, READY 2, DRAFT 1,
CANCELLED 1. SEA and ROAD are required. When AIR is unavailable in the existing
profile, the two Miami AIR stories use SEA, with the fallback reported in preview.
The four standardized sites are retained; no airport location is invented.

Each customer has repeated parcels. Bill-to Client, fictional supplier sender, and
recipient customer are separate relationships; structured addresses and ISO countries
are stored as parcel snapshots. Each invoice contains freight and handling charge
snapshots. Nominal freight rates are 120 for SEA, 180 for AIR, 25 for ROAD, and
handling is 5 per package, in the existing business currency (USD in the standard
lab). Existing business currency and tax calculation remain authoritative.
All invoices remain DRAFT, without simulated paid/sent status or external processing.

Miami, SXM Port, SXM warehouse and Dominica workers perform intake, dispatch,
arrival and delivery at their existing authorized sites. Regional staff dispatch at
Miami and record intermediate arrival at Sint Maarten Port. Existing OWNER books
cross-site routes and handles billing. Work context selection uses the normal service
and restores the original assignment rows and flags within the transaction. No
permissions, accounts, credential hashes, subscription or profile fields change.

## Command and environment procedures

```bash
python src/manage.py seed_logistics_test_lab --help
python src/manage.py seed_logistics_test_lab --environment local --business-id LAB_ID
python src/manage.py seed_logistics_test_lab --environment local --business-id LAB_ID \
  --execute --confirm-business-id LAB_ID --confirm-database FINGERPRINT \
  --reason-reference CHANGE_REFERENCE
python src/manage.py seed_logistics_test_lab --environment local --business-id LAB_ID --inspect
```

The first command without `--execute` previews counts, routes, mode support, and the
connected database fingerprint with zero writes. All execution requires explicit
`LOGISTICS_TEST_LAB_ENABLED=True`, configured `LOGISTICS_TEST_LAB_DATABASE_ID`,
matching connected database fingerprint, exact business-ID confirmation and a reason.
The service repeats these checks inside the transaction; direct service use cannot
bypass the command's environment guards. Business **133 is always rejected**.

Local: use the isolated Block 06A SQLite/PostgreSQL database and existing local billing
bypass only under its normal LOCAL/DEBUG guards. The prepared local database is
`/home/mzero/.local/share/motionmate-logistics-test-lab/local/lab.sqlite3`, lab ID **1**.
Its existing login remains `http://127.0.0.1:8016/accounts/login/`. To address it:

The prepared local lab is already seeded with the counts above. Use `--inspect`
to explore it; seed preview/execution refuses duplicates. Preview guarded reset
before any intentional rebuild.

```bash
export ENV=local DEBUG=True LOGISTICS_LOCAL_BILLING_BYPASS=True
export DATABASE_URL=sqlite:////home/mzero/.local/share/motionmate-logistics-test-lab/local/lab.sqlite3
export LOGISTICS_TEST_LAB_ENABLED=True
export LOGISTICS_TEST_LAB_DATABASE_ID=428db2e64d459c78e04cbc3f8540154603ce60e4e73ad9c154a6ff2b5cddcf5e
```

Development: use **mm-development-app** with its confirmed PostgreSQL connection and
the independently provisioned Block 06A lab. Preview and inspect in that app before
execution; append `--confirm-app mm-development-app` to write commands. Do not pass
the local fingerprint or lab ID into another environment. Legitimate Stripe TEST
activation or the separately approved and audited foundation entitlement is required;
the dataset command never modifies entitlement or seats.

```bash
heroku run --app mm-development-app -- \
  python src/manage.py seed_logistics_test_lab --environment development --business-id DEV_LAB_ID
heroku run --app mm-development-app -- \
  python src/manage.py seed_logistics_test_lab --environment development --business-id DEV_LAB_ID \
  --execute --confirm-business-id DEV_LAB_ID --confirm-database DEV_FINGERPRINT \
  --confirm-app mm-development-app --reason-reference CHANGE_REFERENCE
```

Staging: first configure a dedicated app using `LOGISTICS_TEST_LAB_STAGING_APP`, a
separate PostgreSQL database and the Block 06A authorization settings. Provision the
same emails independently there; preview with `--environment staging`, then execute
with `--confirm-app EXACT_STAGING_APP`, its own business ID and database fingerprint.
Do not copy databases, accounts, passwords or ownership metadata from another environment.
Production and unknown/mismatched runtime environments are hard rejected regardless
of execute, opt-in or override flags. Shared environment deployment/provider verification
requires access to the configured apps and legitimate test entitlement.

## Ownership, reruns and guarded reset

The existing business-owned `DemoSeedRun` and `DemoSeedRecord` retain foundation
ownership. A separate `planned_counts.dataset` manifest records stable keys, owned
targets and SHA-256 snapshots of all dataset record fields. A duplicate preview or
execute safely refuses and directs the operator to inspection/reset.

```bash
python src/manage.py seed_logistics_test_lab --environment local --business-id LAB_ID --reset
python src/manage.py seed_logistics_test_lab --environment local --business-id LAB_ID --reset \
  --execute --confirm-business-id LAB_ID --confirm-database FINGERPRINT \
  --reason-reference CHANGE_REFERENCE --confirm-test-financial-data
```

Reset deletes only manifest-owned cargo, charges, draft invoices, lines, activity logs,
and intermediate handling associations, retaining the business, nine users, passwords,
memberships, sites, assignments, subscription, profile and original seed run.
Unrelated existing clients, invoices and normal login/billing metadata are also
preserved; they need not be adopted into fixture ownership. It validates
the entire ownership graph, tenant relationships, other seed claims and all incoming
foreign keys. Missing or edited fixture rows, real operator events, unowned dependents,
sent/paid/dispatched invoices, malformed metadata and cross-tenant links cause safe refusal.
Reset of invoice drafts requires explicit financial confirmation. It does not bypass
`purge_business` or enable financial deletion on a customer business. Full lab cleanup
still hits the existing invoice deletion gate; reset the dataset first.

Seed/reset are atomic, serialize on the Business row in PostgreSQL, and append durable
`LogisticsTestLabAudit` actions `dataset-seed` / `dataset-reset` with the reason reference.
No rebuild flag erases cargo automatically: preview reset, execute reset, preview seed,
then execute seed. Edited fixtures require manual review, rather than a force flag.

## Manifests, labels and validation

Use the existing private shipment manifest/CSV and parcel label preview, browser print,
and PDF endpoints. QR and Code 128 labels are generated on demand; fixture creation
stores no PDFs or public artifacts. Both symbols encode the actual V2 tracking code.

Focused tests cover zero-write preview, counts, relationship snapshots, valid event
chains, shipment states/manifests, staff attribution, unchanged foundation fields,
invoice lines/taxes/charges, every parcel's QR and Code 128 decoding at 203/300 DPI,
tenant/site authorization, production/customer/133 rejection, duplicate execution,
atomic failure, ownership checks and guarded reset/reseed. PostgreSQL concurrency
verification and SERVICE regression results are recorded after execution.

No additional model migration, package or product route is introduced by Block 06B.
Deploy Block 06A migration `logistics.0019_logistics_test_lab_audit` first. Existing
ReportLab label dependencies and optional PDF decoder development dependencies suffice.

Changed implementation files: `test_lab_scenarios.py`, `test_lab_dataset.py`,
`management/commands/seed_logistics_test_lab.py`, and the foundation ownership integration
in `test_lab.py`. Tests live in `test_test_lab_dataset.py` and
`test_test_lab_dataset_concurrency.py`. `shipping_labels.py` increases V2 Code 128
modules to 10 mils after a random-code 203-DPI decoding failure, while preserving
legacy sizing; `docs/logistics_shipping_labels.md` records the physical layout change.
This document and the foundation guide contain the operating procedures.

## Verified results (2026-10-11)

- Full six-app SQLite regression (`accounts`, `businesses`, `crm`, `billings`,
  `appointments`, `logistics`): **1,666 tests, OK, 42 skipped**, including existing
  SERVICE seed/reset, invoice and tenant behavior. Raw log:
  `/tmp/logistics-dataset-sqlite-full-final.log`.
- Final dataset/ownership tests: **15 SQLite tests, OK** and **16 PostgreSQL tests,
  OK**, including actual concurrent provisioning of one dataset, preserved paid
  invoice/billing notification, reset/reseed and transaction rollback. Logs:
  `/tmp/logistics-dataset-sqlite-ownership-final.log` and
  `/tmp/logistics-dataset-postgres-ownership-final.log`.
- Two additional preview/reset checks passed after clearing query-log buffers and
  asserting nonempty captured queries, verifying zero SQL writes without truncated
  query captures: `/tmp/logistics-dataset-preview-final.log`.
- Existing shipping-label compatibility plus dataset/PostgreSQL concurrency tests:
  **29 tests, OK**, `/tmp/logistics-dataset-postgres-final.log`. Every dataset label
  decoded both QR and Code 128 at 203 and 300 DPI. Additional randomized V2 label
  verification decoded **200 labels / 400 raster checks, zero failures**:
  `/tmp/logistics-lab-label-stress.log`.
- Ruff, Black, Django system checks, migration-drift checks, command help and
  `git diff --check` passed. Test processes use MD5 password hashing for speed;
  the persistent local accounts retain their original normal authentication hashes.
- Local preview and explicit execution seeded **business 1 only**, with one
  `dataset-seed` audit. All **315 dataset records** match their ownership snapshots.
  Before/after hashes of every foundation row match, including nine account hashes,
  memberships, locations/assignments, subscription and LogisticsProfile. Reset was
  previewed, preserving the live dataset. The refreshed local login returned HTTP 200.

The broad regression was followed by focused checks for the final added financial
preservation and query-capture coverage. SQLite skips include PostgreSQL concurrency
and unavailable optional cache checks; the dataset race was run on an isolated UTF-8
PostgreSQL cluster. Development/Staging execution, live Stripe TEST activation,
physical thermal printers and camera/browser scanner hardware were not exercised.
