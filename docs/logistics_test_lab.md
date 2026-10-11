# Logistics Test Lab Foundation V2

For connected cargo, invoices, manifests and labels after provisioning, see
[Block 06B dataset procedures](logistics_test_lab_dataset.md).
For automated suites, operator evidence and promotion gates, see
[Block 06C acceptance](logistics_test_lab_acceptance.md).

`setup_logistics_test_lab` creates Motionmate Global Cargo, a uniquely marked
fictional LOGISTICS workspace. Fixture identity is
`motionmate-logistics-test-lab-v2`; reserved slug is
`motionmate-global-cargo-test-lab`. Each environment uses its own database,
accounts, password hashes, encrypted handoff, and audit entries. Never copy a
database between environments.

## Reused components and scope

The command uses Business, BusinessUser, TaskIOUser and normal business login,
BusinessSubscription/ClarivoPlan, normal seat helpers, LogisticsProfile,
LogisticsLocation model validation and offline reference data, location access
services, DemoSeedRun/DemoSeedRecord ownership, selective session invalidation,
and the existing controlled business purge. No SERVICE access or billing policy
changes. No parcels, clients, invoices, emails, payments, notifications or jobs
are created by this foundation.

Only `LogisticsTestLabAudit` is new: a small independent ledger of fixture version,
environment, business-ID snapshot, action and approval/change references. It
survives cleanup and contains no credentials, contact details or provider IDs.
The command and service are separate from the existing demo seed commands.
The foundation owns the tenant's seed run; existing cargo/demo commands safely
refuse to overwrite it.

## Accounts and authorization

All addresses end in `@globalcargo.motionmate.test`, identically everywhere.

| Account | Email | Existing role | Location access |
| --- | --- | --- | --- |
| OWNER | owner@globalcargo.motionmate.test | OWNER | Business-wide |
| ADMIN | admin@globalcargo.motionmate.test | ADMIN | Business-wide |
| MANAGER | manager@globalcargo.motionmate.test | ADMIN | Business-wide management |
| MIAMI STAFF | miami@globalcargo.motionmate.test | STAFF | Miami Cargo Hub |
| SXM PORT STAFF | sxm-port@globalcargo.motionmate.test | STAFF | Sint Maarten Port |
| SXM WAREHOUSE STAFF | sxm-warehouse@globalcargo.motionmate.test | STAFF | SXM Distribution Center |
| DOMINICA STAFF | dominica@globalcargo.motionmate.test | STAFF | Dominica Cargo Hub |
| REGIONAL STAFF | regional@globalcargo.motionmate.test | STAFF | Miami Cargo Hub + Sint Maarten Port |
| UNASSIGNED STAFF | unassigned@globalcargo.motionmate.test | STAFF | None |

There is no narrower Logistics manager permission. MANAGER uses existing ADMIN,
including billing/team permissions. No global Manager role, Django staff grant,
superuser flag, group or global permission is added.

| Facility | Code | ISO country | Type | Verified reference |
| --- | --- | --- | --- | --- |
| Miami Cargo Hub | MIA-HUB | US | HUB | None (company facility) |
| Sint Maarten Port | SXM-PORT | SX | PORT | SXPHI |
| SXM Distribution Center | SXM-DC | SX | WAREHOUSE | None (company facility) |
| Dominica Cargo Hub | DM-HUB | DM | HUB | None (company facility) |

Existing reference validation does not permit a port/airport reference on a HUB
or WAREHOUSE. No reference data is invented. TRANSPORTATION is the operating
area; SEA, AIR and ROAD are supported profile modes. Worker grants are reviewed
and strict location operations enabled. Regional staff initially work in Miami
and can switch to their authorized port. OWNER/ADMIN/MANAGER initially select
Miami as work context; this context does not narrow their business-wide grant.
Unassigned staff authenticate but have no operational records or work location.

## Secure credentials

Install `age` and `age-keygen` in the execution environment; these are required
for password-producing operations and the automated lab tests. Keep the private
identity on the operator's machine. Generate an independent identity per
environment or use an authorized password-manager recipient.

```bash
umask 077
install -d -m 700 "$HOME/.local/share/motionmate-test-lab/local"
age-keygen -o "$HOME/.local/share/motionmate-test-lab/local/identity.txt"
age-keygen -y "$HOME/.local/share/motionmate-test-lab/local/identity.txt"
```

The last command prints a **public** `age1...` recipient. Give only that value
to provisioning. `--credential-file` must be a new path inside an existing
operator-owned 0700 directory without symlinks. The command encrypts credentials
in memory, writes only ciphertext to a new 0600 artifact and stores only Django
password hashes in the database. Encryption/write failure rolls back all fixture
writes. Console output contains inventory and references, never passwords.

Decrypt directly into a private file for password-manager import:

```bash
umask 077
age --decrypt -i /secure/local/identity.txt \
  --output /secure/local/credentials.json /secure/local/credentials.age
```

Use a fresh output path in a private directory outside the repository. Import
into the authorized password manager, remove the decrypted file, and follow the
operator's retention policy for encrypted backups and private identities.
Do not omit `--output`, use `cat` on the decrypted file, paste passwords into
shell arguments/chat/documents, or publish keys/credentials as CI artifacts.
Ordinary `.test` mail cannot deliver reset links. Lost credentials require the
guarded rotation action below; lost private keys require a fresh recipient and
rotation. Provisioning after owner initialization hands over only the eight new
passwords; retain the owner's earlier handoff.

## CLI and Local procedure

```bash
python src/manage.py setup_logistics_test_lab --help
```

Default action previews full provisioning. `--initialize` previews owner-only
bootstrap. `--inspect` always reads only. Every write requires `--execute`,
`--reason-reference`, opt-in and exact connected database confirmation.

Use a newly created isolated SQLite database or dedicated local PostgreSQL DB:

```bash
export ENV=local DEBUG=True
export DATABASE_URL=sqlite:////absolute/private/lab.sqlite3
export LOGISTICS_LOCAL_BILLING_BYPASS=True
python src/manage.py migrate
python src/manage.py setup_logistics_test_lab --environment local
```

Copy the preview's `database_id` into both configuration and the execute flag.
The fingerprint comes from the actual connection and never exposes database
credentials. The offering's existing seat limit must allow nine users (null
means the normal unlimited allowance). The command never changes plan limits,
pricing or plan activation. It checks entitlement and pending-invitation seat
usage again while provisioning. Local's existing bypass permits a compatible
pending STRIPE/yearly subscription without fabricating an active subscription;
it works only with ENV=local and DEBUG=True outside a Heroku process.

```bash
export LOGISTICS_TEST_LAB_ENABLED=True
export LOGISTICS_TEST_LAB_DATABASE_ID='<preview fingerprint>'
python src/manage.py setup_logistics_test_lab --environment local \
  --execute --confirm-database '<preview fingerprint>' \
  --reason-reference '<change reference>' \
  --credential-recipient '<age public recipient>' \
  --credential-file /secure/local/credentials.age
python src/manage.py setup_logistics_test_lab --environment local --inspect
python src/manage.py runserver
```

Local login: `http://127.0.0.1:8000/accounts/login/`.

This implementation's prepared local instance is outside Git at
`/home/mzero/.local/share/motionmate-logistics-test-lab/local/`. It contains
`lab.sqlite3`, encrypted `credentials-v2.age` and operator `identity.txt`, with a
private directory and 0600 files. To use it, set DATABASE_URL to that database,
ENV=local, DEBUG=True and LOGISTICS_LOCAL_BILLING_BYPASS=True before running the
server. Use inspection to obtain the fingerprint before any future mutation.
This checkout's running lab uses `http://127.0.0.1:8016/accounts/login/`, so the
existing server on port 8000 can continue running. For this prepared instance,
also set MOTIONMATE_PUBLIC_BASE_URL=http://127.0.0.1:8016 and use
`python src/manage.py runserver 127.0.0.1:8016`. Local inspection honors a
configured loopback base URL; its default is port 8000.
Local age tools are also installed outside the repository in
`/home/mzero/.local/share/motionmate-logistics-test-lab/tools/`; add that directory
to PATH for local credential retrieval and future rotations. Shared apps still
need their own age installation.

## Development and dedicated Staging

Development is exactly `mm-development-app`. Staging needs a separately created,
configured app and separate PostgreSQL database. Do not set Staging to the
Development app. Each deployment must configure ENV, HEROKU_APP_NAME (for example
via Heroku runtime dyno metadata), its own public base URL, age availability,
and the normal activated Logistics plan with at least nine seats.
Keep LOGISTICS_LOCAL_BILLING_BYPASS=False.

1. Deploy the code and apply migration `logistics.0019_logistics_test_lab_audit`.
2. Run `--environment development --initialize` on `mm-development-app`, or
   `--environment staging --initialize` on the dedicated app, without execute.
   Configure LOGISTICS_TEST_LAB_STAGING_APP to the Staging app name there.
3. Independently verify the target app, attached database and printed fingerprint.
   Set LOGISTICS_TEST_LAB_ENABLED=True and LOGISTICS_TEST_LAB_DATABASE_ID on
   that app. Every execution also needs `--confirm-app <app name>` and
   `--confirm-database <fingerprint>`.
4. Execute `--initialize` with a new encrypted handoff and reason reference.
   This creates only the fictional workspace, profile, owner and pending
   subscription. It does not activate access or call Stripe.
5. Obtain a separate, environment-specific test-entitlement approval. Configure
   LOGISTICS_TEST_LAB_ENTITLEMENT_APPROVAL to its auditable reference on that
   authorized environment. The request to create fixtures alone is not this
   approval. Preview, then execute:

```bash
python src/manage.py setup_logistics_test_lab --environment development \
  --activate-test-entitlement --business-id <lab ID> \
  --test-entitlement-approval '<configured approval reference>'
python src/manage.py setup_logistics_test_lab --environment development \
  --activate-test-entitlement --business-id <lab ID> \
  --confirm-business-id <lab ID> --execute \
  --confirm-app mm-development-app --confirm-database '<fingerprint>' \
  --test-entitlement-approval '<configured approval reference>' \
  --reason-reference '<grant change reference>'
```

6. Preview and execute the default provisioning action with that same business
   ID, environment/database/app confirmations, reason, recipient and a fresh
   credential artifact. It creates the remaining eight accounts and all four
   facilities using normal entitlement enforcement. Remove the approval config
   after the grant; the durable audit authorizes subsequent provisioning.
7. Retrieve encrypted artifacts before the one-off dyno exits. Use one Heroku
   one-off process to create a private directory, run the command with its
   credential artifact, and copy **ciphertext only** to a private operator file.
   Do not store a private age identity on the app or assume Heroku files persist.

The repository includes `scripts/logistics_test_lab_handoff.sh` for this single
process handoff. It requires explicit execution, creates a temporary private
directory, sends command inventory to stderr, emits ciphertext only on stdout
after success, and removes the dyno's encrypted artifact on exit. From the
operator's private directory, initialize Development as follows:

```bash
umask 077
heroku run --no-tty --exit-code --app mm-development-app \
  'bash scripts/logistics_test_lab_handoff.sh --environment development --initialize --execute --confirm-app mm-development-app --confirm-database <fingerprint> --reason-reference <change-reference> --credential-recipient <operator-public-recipient>' \
  > /secure/development/owner.age
```

Replace the angle-bracket placeholders with their actual values before execution;
shell angle brackets are not literal argument syntax. Keep Heroku CLI banners
outside the armored age block when importing. Repeat with a fresh directory and
artifact for the eight additional accounts. Substitute the dedicated app and
`--environment staging` for Staging. Login is
`<MOTIONMATE_PUBLIC_BASE_URL>/accounts/login/`, reported by inspection.

Legitimate Stripe TEST activation is also accepted when its existing entitlement
is active and TEST keys are configured. However, the foundation does not invent
an approved LogisticsApplication or enrollment history. Existing Stripe checkout
requires that approval binding, so a plain initialized lab uses the separately
approved test-entitlement path above. The command cannot waive a review hold,
replace Stripe references, fabricate webhook activation, or turn on a plan.

## Rotation, cleanup and rebuild

Preview password rotation, then execute with exact confirmation and a fresh
artifact. Rotation changes only owned users' password hashes, invalidates lab
sessions, and records a non-secret audit reference. Other tenant memberships or
changed fixture ownership cause refusal.

```bash
python src/manage.py setup_logistics_test_lab --environment local \
  --rotate-passwords --business-id <lab ID>
python src/manage.py setup_logistics_test_lab --environment local \
  --rotate-passwords --business-id <lab ID> --confirm-business-id <lab ID> \
  --execute --confirm-database '<fingerprint>' --reason-reference '<rotation reference>' \
  --credential-recipient '<age recipient>' --credential-file /secure/local/rotation.age
```

Cleanup previews with `--cleanup --business-id <lab ID>`. Execution additionally
requires matching --confirm-business-id, reason and environment/database/app
confirmations. It rechecks owned records and incoming relations, including
SET_NULL references, then uses normal purge eligibility, selective session
invalidation, audit and post-delete verification. Deactivation happens inside
the transaction only after all checks pass.

No financial override exists in this command. Any unowned record, invoice,
invoice line, Stripe reference, cross-tenant link, shared/privileged user or
unsupported ownership metadata blocks cleanup. Manually created records,
including profile/onboarding records after broader app use, may require a
separate reviewed lifecycle operation. No existing customer data is adopted.

```bash
python src/manage.py setup_logistics_test_lab --environment local \
  --cleanup --business-id <lab ID>
python src/manage.py setup_logistics_test_lab --environment local \
  --cleanup --business-id <lab ID> --confirm-business-id <lab ID> \
  --execute --confirm-database '<fingerprint>' --reason-reference '<cleanup reference>'
```

Rebuild is a separate normal provisioning operation after successful cleanup,
with a new encrypted artifact and fresh independent passwords. Duplicate setup
clearly refuses without overwriting passwords. Audit entries remain after cleanup.
Production and unknown environments reject every lab operation regardless of
opt-in, DEBUG, bypass flags or confirmations. Local mode also rejects cloud dynos.

## Validation and deployment boundaries

Lab tests cover actual business-login POSTs for all nine users, authorization,
regional switching, unassigned access denial, real parcel/shipment scoping,
tenant isolation, seat limits, preview SQL without writes, duplicate execution,
production/app/database rejection, real age encrypt/decrypt, rollback, rotation,
audit, cleanup protection and SERVICE preservation. A PostgreSQL concurrency test
verifies simultaneous first execution creates one lab and one handoff.

Run the six-app regression suite with age on PATH and an isolated database:

```bash
LOGISTICS_LOCAL_BILLING_BYPASS=False python src/manage.py test \
  apps.accounts apps.businesses apps.crm apps.billings apps.appointments apps.logistics --noinput
```

The test runner normally disables DEBUG, so leave the bypass disabled in its
process configuration; lab tests explicitly enable it only within local fixtures.
Shared deployment, Staging app/database selection, approval references and
provider/browser checks remain operator actions. No remote deployment or Stripe
activation is implied by automated tests.

Verified results for this implementation: the complete six-app suite ran 1,651
tests successfully on isolated PostgreSQL (2 skips) and SQLite (41 skips).
Regression processes used MD5 hashing only to accelerate test fixtures; the
persistent local accounts use normal PBKDF2 hashes. The latest focused SQLite
suite ran 26 tests successfully with its PostgreSQL-only concurrency test skipped;
that concurrency test and the lab lifecycle also passed on PostgreSQL. All nine
persistent accounts passed real HTTP login with CSRF validation against the local
server. Migration drift, Django checks, Ruff, Black and shell syntax checks passed.
