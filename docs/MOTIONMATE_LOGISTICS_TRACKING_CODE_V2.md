# Motionmate Logistics Tracking Code V2

New Parcels receive `MM-PCL-<39 random characters>`. `MM` identifies Motionmate;
`PCL` identifies a Parcel. The alphabet is
`ABCDEFGHJKMNPQRSTUVWXYZ23456789` (31 symbols); `O`, `0`, `I`, `1`, and `L`
are excluded from the suffix. The full code is 46 characters.

## Security and creation

Legacy codes use `secrets.token_hex(24)`: 192 random bits encoded as 48 uppercase
hex characters. Public tracking treats the complete code as a bearer secret.
The prefix adds no entropy. Independent `secrets.choice` calls select all 39
suffix symbols uniformly, giving `39 * log2(31) = 193.213` bits. 38 symbols
would give only 188.259 bits, so 39 is the shortest suffix preserving the existing
security level. The illustrative `MM-PCL-A82719K4N` is not a valid complete code:
nine symbols would provide only 44.588 bits and include an excluded `1`.

The random space has `N = 31**39`, approximately `1.456 * 10**58` possibilities.
For one billion Parcels, the birthday bound on any collision is
`n*(n-1)/(2*N)`, approximately `3.435 * 10**-41`. A billion independent guesses
against a billion valid codes has hit probability at most `guesses*n/N`,
approximately `6.869 * 10**-41`. These conservative examples do not rely on
throttling: existing public tracking still limits each resolved client identity
to 30 lookups per minute and denies lookups when its configured cache fails.
Distributed guessing remains protected by the code's entropy; no shorter alias
or separate lookup token is needed. Codes must still be treated as bearer secrets.

`models.generate_tracking_code` remains the single generator and the Parcel
field default. `parcel_services.register_parcel` is the creation boundary for
dashboard, inline Client, mobile/PWA, demo tooling, and future API callers.
Callers cannot supply a tracking code. The existing global database UNIQUE
constraint remains authoritative. Registration tries at most five candidates,
using transaction savepoints to recover from concurrent database collisions as
well as validation-time collisions. Other validation/insertion errors propagate.
Exhaustion rejects registration and rolls back without an initial ParcelEvent.
Successful registration creates exactly one initial event. UUIDs are unchanged.

## Compatibility and UI

Shared server patterns accept legacy uppercase hex codes and complete V2 codes.
Model validation and immutable-code checks retain both. There is no data rewrite.
Public tracking still requires the exact uppercase code without whitespace,
keeps CSRF, public-field allowlisting, no-store responses, generic unavailable
responses, and existing fail-closed throttling/cache requirements.

Authenticated manual input, scanner wedges, and camera decoding use the same
resolver and retain case normalization and boundary whitespace trimming. The
server supplies the shared validation pattern to the scanner JavaScript through
the existing form widget. There is no new scanner library. URLs, shortened codes,
interior whitespace, ambiguous V2 suffix symbols, and concatenated codes fail.
Existing tenant, role, subscription, and access checks remain in effect.

Existing components display the stored value in parcel lists/details, registration
confirmation, scan results, public tracking, Client and Shipment listings,
dashboard references, manifests, and CSV exports. Copy Tracking Code continues
to copy the complete stored value. Input help now mentions both code formats.

Both formats can be encoded directly as QR and Code 128 payloads without a URL
or alternate lookup token. The full V2 code is required. Actual Code 128 label
width, quiet zones, resolution, and scanner distance still need validation with
physical equipment; no label-printing feature is included.

## Demo seed audit

`seed_demo_data`'s Logistics branch and `seed_logistics_demo_data` already call
`demo.seed_logistics_demo`, which registers each Parcel through the domain service.
New demo Parcels automatically receive V2 codes; no separate generator or prefix
ownership detection is added. Preview never allocates codes or writes data.
Existing `DemoSeedRun` metadata blocks repeated execute calls rather than appending
duplicate data. Reruns and reset previews retain legacy codes, invoices, lines,
events, shipments, and profiles. Explicit reset still removes only durably owned
records after the existing tenant and genuine-dependent checks, including owned
demo invoices/lines. Unowned genuine data is preserved. No automatic reset occurs.
Existing SEA/ROAD/AIR/RAIL planning and SERVICE seeding are unchanged.

## Deployment

Apply `python src/manage.py migrate` for Logistics migration
`0013_tracking_code_v2`. It alters only field validation state, retains the field
size/default import path/UNIQUE constraint, and contains no data migration.
Deploy templates and scanner assets together; run the existing static collection
pipeline. Scanner assets use the existing hashed static pipeline; the PWA
service worker does not persist scanner JavaScript or operational responses.
Existing deployments still need their shared atomic tracking cache and trusted
client-IP configuration. This block adds no environment variables or providers.
The existing local billing bypass must be disabled outside `ENV=local` with
`DEBUG=True`; verification uses local debug settings with the bypass disabled
without changing the checkout environment.

## Verification

PostgreSQL 14 verification used freshly migrated databases in a disposable UTF-8
cluster and passed with zero skips:

- 270 focused tests: Tracking Code V2, Parcel operations/metadata, manual scanning,
  public tracking/throttling, concurrency, Logistics demo ownership/reset,
  Shipments/manifests, registration workflows, mobile UX, and SERVICE seed/reset.
- 318 additional SERVICE regressions: Business/customer registration, CRM tenant
  scoping and imports, public booking, appointments, billing tenant scoping,
  current workspace resolution, and subscription access/effective-access policy.

The collision race synchronizes successful uniqueness validation in two tenants
before simultaneous INSERTs, then verifies database collision recovery and one
registration event per Parcel. Legacy registration replay and metadata edits
preserve the original tracking code; seed snapshots preserve every Parcel,
ParcelEvent, Shipment, Invoice, InvoiceLine and ownership record on rerun/preview.

Nine PostgreSQL/Playwright checks passed: one manual-scanner check, six camera
checks and two mobile checks. These include complete legacy/V2 clipboard payloads,
real QR and Code 128 decoding from synthetic video pixels, native detector and
permission simulations, installed PWA safeguards, mobile registration, and 84
route/viewport layout checks from 320 to 1440 pixels. Clipboard writes are stubbed
to verify the complete payload. No physical camera, scanner or printed label was
tested; deployed shared-cache/proxy behavior remains manual.

Django checks, migration-drift checks, Black, Ruff, JavaScript syntax validation,
and `git diff --check` passed. PostgreSQL `sqlmigrate logistics 0013` reports a
no-op. The checkout's default settings still trigger the pre-existing
`logistics.E014` billing-bypass configuration check; verification used valid
explicit settings without editing environment files. The full project suite was
not run. Live-server browser modules were run separately on fresh test databases
to preserve their existing serialized fixture behavior.
