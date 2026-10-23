# Logistics Location Foundation V1

The existing Business is the tenant. LogisticsProfile operating areas and SEA/ROAD/AIR/RAIL configuration are unchanged. No locations are created for SERVICE businesses.

## Stored concepts

- Parcel/Shipment `origin` and `destination`: retained geographic place/route text.
- Optional `origin_country_code` / `destination_country_code`: ISO 3166-1 alpha-2 country or territory. A route does not require a company branch.
- Optional `origin_location` / `destination_location`: protected foreign keys to the same Business's LogisticsLocation facilities. Shipment forms label these departure/arrival facilities.
- Optional `origin_reference_code` / `destination_reference_code`: controlled verified UN/LOCODE references; separate from facilities and sender/recipient addresses. Historical Parcel loading/discharge port text remains unchanged.
- LogisticsLocation: tenant, canonical name, stable uppercase short code, type, required ISO country code, optional verified reference and structured address, active flag. Case-insensitive canonical name and code uniqueness is enforced per tenant by PostgreSQL constraints. Ownership, code and country cannot change through ordinary model saves. Deactivate facilities instead of deleting referenced facilities.
- LogisticsApplication: derived nullable `country_code`, retaining its existing country text. Application and route models expose `location_review_required` for unresolved legacy geography.

Only existing workspace owners/administrators with operational subscription access can register/update facilities at Workspace Settings → Operating locations. Block 03 adds reviewed worker assignments and location-scoped access using the existing roles and scanner resolver; see [Logistics location access](logistics_location_access.md). Inactive facilities cannot be assigned to new records, but saved selections and identical creation retries retain them. Staff assignments and active work context use the same location registry through Block 03.

## References

Countries use pinned [pycountry](https://github.com/pycountry/pycountry) 26.2.16, backed by Debian iso-codes. The 249 ISO entries include Sint Maarten (Dutch part), Dominica, Anguilla and Curaçao. Exact names, official/common names and alpha-2/alpha-3 codes resolve; the explicit historical aliases Sint Maarten and Curacao resolve to SX and CW. There is no fuzzy or city-to-country inference. Existing territory eligibility configuration recognizes ISO-equivalent country names/codes without adding jurisdictions.

`src/apps/logistics/data/location_references.json` contains 22 port/airport-function records extracted from [UNECE UN/LOCODE production release 2025-1](https://unlocode.unece.org/publications/), under CC BY 4.0. The source archive SHA-256, release, original country, name, function and status are recorded. It deliberately covers a limited Caribbean reference set (AI, CW, DM, SX) plus USMIA, USNYC, NLAMS and NLRTM; only nondeleted AI/AS/RL-status entries with port or airport functions are included. Airport references use UN/LOCODE airport functions; no IATA codes are inferred or invented.

Reference data is local: deployment has no network/geocoding dependency. Updating the country package or curated reference snapshot requires review and tests. Missing ports/airports can be added only after verifying them against the official publication; company facilities outside this coverage use an empty reference. This is not a worldwide airport/port directory.

## Legacy migration and deployment

1. Install the updated lockfile with `uv sync`.
2. Apply normal Django migrations (`python src/manage.py migrate`): 0014 adds the registry and optional fields; 0015 backfills only frozen, exact ISO name/code matches and the two explicit aliases.
3. Collect static assets using the existing deployment process and restart the application.

Migration 0015 updates only new geography/review columns, retaining original text, timestamps, tracking codes, identities, events, shipment statuses and relationships. It never infers a company facility or port reference, creates no facilities, and does not overwrite LogisticsProfiles or change application decisions. Unmatched city/place strings and ambiguous names remain intact and flagged for manual review. Staff resolve route flags by choosing country/facility/reference selectors on existing edit forms. Application review flags are visible in the review admin.

The backfill scans existing Logistics records and runs inside the normal migration transaction; schedule the migration according to dataset size. Reversing the schema migration discards only the new structured metadata and preserves original text. No automatic demo reset/reseed is performed. Existing demo seeding still uses the same domain services; optional facility selectors are not filled with invented facilities. Business inventory/purge accounts for the new registry and blocks cross-tenant facility corruption.

No scanner changes, new label printing, address normalization, geocoding, staff assignment, billing or Shipment lifecycle features are included. Facilities remain private; public tracking continues to expose its existing limited fields.

## Verification for this block

Verification used disposable UTF-8 PostgreSQL 14 databases, without accessing or resetting Development data:

- 600 Logistics operational tests: OK, two shared-Redis integration tests skipped because no `TRACKING_REDIS_TEST_URL` was provided.
- Seven historical migration tests, run separately: OK.
- 372 SERVICE/business-safety tests: OK (registration, tenant-scoped CRM, public booking, appointments, billing, subscriptions, business inventory/purge, demo seed/reset).
- Final 99 focused compatibility tests: OK, including location authorization, tenant/reference constraints, inactive form/service retries, backfilled legacy registration retries, Parcel workflows and Shipment write receipts.
- Playwright: one browser test passed, exercising facility registration and searchable facility/country/port selection, plus 15 layouts across five pages at 320/390/1440 px. Screenshots were inspected for the facility settings page; browser evidence is in `/tmp/logistics-location-ux`.
- Django system checks, migration consistency (`makemigrations --check --dry-run`), targeted Ruff and `git diff --check`: passed.

An initial combined parallel test run was interrupted by a Python segmentation fault during historical migration model rendering. The migration suites passed on fresh databases when run separately; the interrupted run is not counted as passing evidence. External provider and deployed Redis/proxy verification is outside this block.
