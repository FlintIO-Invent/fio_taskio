# Motionmate Logistics Scanner Input V1

This block adds an authenticated, online Parcel lookup/action workflow for manual
entry, paste, and scanners that type ordinary keys. It introduces no migrations,
Parcel/Shipment lifecycle changes, billing changes, camera decoding, DataWedge,
native wrapper, or offline queue.

## Existing patterns reused

- Parcel list search remains a general search. The scanner uses exact equality on
  `tracking_code`, accepting both legacy 48-character hexadecimal codes and V2
  `MM-PCL-` codes with 39 readable suffix characters.
- `parcels_for_business` enforces persisted tenant, vertical, membership, role,
  module and effective-access checks. Public tracking and its deliberately limited
  projection are unchanged and are not used by operational scanning.
- `ParcelEventForm`, the existing transition policy, and `record_parcel_event`
  remain responsible for allowed actions, expected-status validation, transactional
  mutation, and idempotent receipt replay. The scanner does not mutate models.
- Shipment context uses `shipments_for_business`; inaccessible shipment details
  are not shown. Full Parcel/Shipment links use existing detail routes.
- The shared dashboard, Logistics mobile shell, cancellation confirmation,
  session authentication, CSRF, and PWA offline/private-cache safeguards are reused.

## Routes and source adapter

- `GET /logistics/parcels/scan/` opens an empty scanner. Codes in GET query strings
  are not resolved.
- `POST /logistics/parcels/scan/` resolves the form's `tracking_code` for the active
  LOGISTICS Business. Invalid input returns 400. Missing and foreign-tenant codes
  return the same generic 404 response.
- `POST /logistics/parcels/scan/<parcel_id>/action/` accepts `status`,
  `expected_status`, `idempotency_key` and CSRF. It calls the existing event service.
- With `X-Requested-With: XMLHttpRequest`, these routes return the small HTML result
  panel. Ordinary forms work without JavaScript; successful ordinary action POSTs
  redirect to the scanner with a confirmation message.
- `normalize_scan_code` and `resolve_scanned_parcel` in `scan.py` are independent of
  input hardware. The optional browser entrypoint
  `window.MotionmateParcelScan.submitCode(decodedString)` feeds the same validated
  form and authenticated server resolver. Its Boolean return means submission was
  accepted locally; only the server response confirms a lookup or action.

## Normalization and focus

Boundary whitespace, CR/LF and tab suffixes are trimmed, then codes are uppercased.
The result must be a complete legacy or V2 code; raw input is limited to 256
characters. Interior whitespace, concatenated codes, URLs and arbitrary prefixes
are rejected rather than repaired. Paste validation occurs before the browser can
remove embedded newlines from a text input.

The scan field receives initial focus and uses native Enter submission. Focus and
selection return after a lookup, error, confirmed action, or Next Scan. Pending
requests make the input read-only and disable buttons. Editing a code clears the
previous Parcel result. The field has a visible label and focus outline; errors
and confirmations use live feedback and accessible roles.

## Results and actions

The compact result shows tracking code, Client, current status, route, accessible
Shipment and transport mode, and the latest event. Only current policy actions
allowed by the operator's effective write access appear. Read-only users can look
up parcels without action controls. Cancellation retains the existing confirmation.
Full Parcel details remain one link away.

A confirmed action clears the result and input and restores focus for the next
scan. A rejected action refreshes current state and permitted actions. A lost
response keeps the original action and retry key; it does not claim success or
automatically retry. Next Scan explicitly resets the workflow.

## Retry, security and offline behavior

Client-side pending-request suppression prevents duplicate Enter/button submits.
Server-side UUID receipts and expected-status checks protect repeated POSTs, replay
after later state changes, and conflicting or stale actions. These are the existing
Parcel service protections, not a second lifecycle implementation.

Both scanner endpoints send no-store cache headers and inherit private HTML cache
protection. Codes are sent in POST bodies rather than lookup URLs. Session, CSRF,
tenant, role, module and effective billing-access checks remain active. SERVICE
workspaces have no scanner entrypoint or scanner access. Public tracking is unchanged.

The existing PWA prevents offline POSTs. The scanner never creates an offline queue
or displays a successful write before confirmation. A changed session/access clears
the operational result and asks for a page reload.

## Changed files

New:

- `src/apps/logistics/scan.py`
- `src/apps/logistics/scan_views.py`
- `src/apps/logistics/test_scan.py`
- `src/templates/logistics/scan.html`
- `src/templates/logistics/includes/scan_panel.html`
- `src/static/assets/js/logistics-scan.js`
- `src/static/assets/css/logistics-scan.css`
- `scripts/logistics_scan_browser_check.py`
- `docs/MOTIONMATE_LOGISTICS_SCANNER_INPUT_V1.md`

Updated:

- `src/apps/logistics/urls.py`
- `src/templates/inheritance/dashboard_parent.html`
- `src/templates/logistics/includes/dashboard_snapshot.html`
- `src/templates/logistics/parcel_list.html`

The three navigation additions are limited to accessible Logistics Parcel screens
and dashboard/sidebar actions. Scanner CSS is scoped to its Logistics page.

## Verification

- Full SQLite regression suite: **1,501 tests, OK, 31 skipped**; includes the
  **21 scanner tests** covering normalization, exact lookup, cross-tenant rejection,
  repeat lookups, allowed/forbidden transitions, idempotent replay, stale requests,
  permissions, CSRF, SERVICE exclusion, billing restrictions and private caching.
- Scanner Chromium browser test: **passed** at **320, 390, 768 and 1440px**, with
  ordinary keyboard input/Enter, CR/LF/tab paste, duplicate Enter while pending,
  committed POST with deliberately dropped response and safe retry, future string
  adapter, invalid/missing codes, focus, offline suppression, no horizontal overflow,
  56px scan field, 48px buttons, and normal button text contrast in both themes.
- Existing mobile browser suite: **2 tests passed**, including **84 screen/viewport
  layout checks** and existing real action workflows.
- Existing PWA browser suite: **1 test passed**, covering **8 SERVICE/LOGISTICS
  desktop/phone/tablet Chromium profiles**, actual standalone launch, login/logout,
  navigation, forms, offline fallback and private-cache safety.
- Ruff, Black, JavaScript syntax, Django system checks, and migration drift checks
  pass. No migrations are added.

Reproduce the full suite:

```sh
LOGISTICS_LOCAL_BILLING_BYPASS=False DEBUG=True DATABASE_URL= \
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: PYTHONPATH=src:. \
.venv/bin/python src/manage.py test apps.accounts apps.businesses apps.crm \
apps.billings apps.logistics apps.appointments taskio.test_pwa --parallel 4 --noinput
```

Reproduce scanner browser checks with the installed Chromium executable:

```sh
PWA_CHROMIUM=/path/to/chromium LOGISTICS_LOCAL_BILLING_BYPASS=False DEBUG=True \
DATABASE_URL= DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: PYTHONPATH=src:. \
.venv/bin/python src/manage.py test scripts.logistics_scan_browser_check --noinput
```

Browser screenshots and layout metrics are generated in
`/tmp/motionmate-scanner-browser/`. Final full-suite evidence is in
`/tmp/motionmate-scanner-regression-final.log`; scanner, mobile and PWA evidence is
in `/tmp/motionmate-scanner-browser-final.log`,
`/tmp/motionmate-scanner-mobile-regression.log`, and
`/tmp/motionmate-scanner-pwa.log` respectively.

These are Chromium checks, including device-sized emulation, not physical Zebra,
USB/Bluetooth scanner, Android soft-keyboard, or Safari/iOS certification. The
configured PostgreSQL role has no CREATEDB privilege, so PostgreSQL concurrency
tests could not run here; SQLite does not establish row-lock/concurrency behavior.

## Recommended next block

Validate this workflow on real Zebra/USB/Bluetooth keyboard-wedge devices, including
configured Enter/tab suffixes and Android keyboard/focus behavior. Then add a
separate opt-in camera decoding adapter that submits decoded strings to this same
workflow; retain the existing resolver, access checks and action service.
