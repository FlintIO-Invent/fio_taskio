# Logistics operating-area classification

`Business.vertical` remains `LOGISTICS`. A business-owned `LogisticsProfile`
contains validated JSON lists of operating areas and transportation modes, plus
creation/update timestamps. Its one-to-one Business foreign key enforces uniqueness
in the database and cascades with the tenant. This is a new table, so no existing
Business relationship needs a nullable-FK rollout.

The centralized taxonomy in `apps.logistics.classification` defines Transportation,
Warehousing, Inventory Management, and Order Processing; transportation modes are
Sea, Air, Road / Truck, and Rail. Both dimensions allow multiple selections. Shared
validation rejects unknown values, duplicate values, and modes without Transportation.
The profile offers `has_operating_area()` and `has_transport_mode()` helpers.
Selections are stored in taxonomy order so reordering the same selections does not
revise an application's approval.

## Migration and historical compatibility

Migration `0010_operating_classification` creates the profile table and adds both
classification fields to `LogisticsApplication`. It backfills every existing
LOGISTICS business, including inactive businesses, with Transportation and no
assumed modes. SERVICE businesses receive no profile.

Historical application classification remains unrecorded (`[]` / `[]`): the
migration does not guess historical answers or rewrite decisions, revisions,
approvals, or timestamps. Existing unrecorded applications can receive unrelated
model-level corrections and can still enroll. Their enrollment creates a
Transportation profile with unknown modes. New applications require an operating
area and at least one mode when Transportation is selected. Public/admin forms
also require an explicit classification when editing an old application.

A profile permits unknown transportation modes for legacy compatibility. Modes
remain invalid when Transportation is absent. Normal model saves and forms validate
values; direct SQL and ORM bulk updates bypass model validation, as with other
validated models in this project.

## Application and operational state

The existing Operations step now includes checkbox groups for both dimensions,
with fieldsets, legends, individual labels, help text, and server error associations.
All original questions remain. Without JavaScript all questions are available and
server validation applies. With JavaScript the mode group appears when Transportation
is selected; deselecting Transportation clears and disables its modes. The wizard
requires a selection in each applicable checkbox group before advancing.

Classification is material application input and is included in immutable decision
snapshots. A classification change uses the existing revision, reevaluation,
enrollment-token revocation, and checkout-invalidation behavior. Eligibility reason
codes, pilot auto-approval, strict evaluation, and market territory eligibility are
unchanged. Classification never limits routes or Parcel/Shipment access.

Approved provisioning writes the profile within the existing enrollment transaction.
Authenticated enrollment retries return the original conversion and preserve later
profile edits. Profile edits never rewrite application history, and later application
revisions do not silently overwrite an already-provisioned profile.

## Administration and tooling

Application reviewers see readable operating-area/mode columns and validated
checkbox fields. LogisticsProfile has its own permission-controlled admin form;
its Business selector contains only LOGISTICS businesses. Workspace Settings exposes
the current business's profile as a read-only summary to its existing authorized
owners/admins.

Application inspection reports the historical classification. Business inspection
reports profile inventory and the current operating profile in its Logistics
summary. Both commands remain read-only.

Logistics demo seeding creates a missing profile or fills an existing Transportation
profile with unknown modes using Sea + Road, matching its demo routes.
An incompatible explicit profile is preserved and seeding is refused; select or
configure a compatible demo workspace first. Compatible profiles are kept, and
dry-run mode writes nothing.
The profile is operational state, so demo reset keeps it. SERVICE seeding is unchanged.
Deactivation retains the profile. Controlled business purge includes its explicit
inventory/deletion count and deletes it while retaining historical application
classification and the existing conversion snapshot/decision/token history.

No billing, pricing, navigation modules, PWA behavior, or Parcel/Shipment lifecycle
fields are added. Warehouse, Inventory/SKU, Order/Fulfillment, shipment modes, and
shipment legs remain future work.

## Verification

Automated coverage includes model/form/admin validation, database uniqueness,
multiple selections, material revisions and stable ordering, provisioning rollback,
retry/profile independence, tenant-scoped settings and unchanged operational access,
legacy backfill/history, inspection, seed/reset behavior, deactivation/purge, and
PostgreSQL simultaneous enrollment/profile creation.

The six-app regression suite covers accounts, businesses, CRM, billings,
appointments, and Logistics. PostgreSQL verification uses disposable databases with UTF-8 encoding and
`CONN_MAX_AGE=0`, so threaded tests close connections at teardown. The complete
regression rerun uses a fast password hasher only in temporary test settings;
the focused PostgreSQL run uses the normal password hasher. Tracking integration
tests isolate and clear their own in-memory test cache, preserving production
rate-limit behavior. The profile summary joins the existing Business query,
preserving the existing ten-query usage-summary budget. A separate strict-mode suite sets `LOGISTICS_AUTO_APPROVE_ALL=False`.
Browser verification covers desktop/mobile checkbox interactions and JavaScript-free
server validation/submission and tenant-specific Logistics/SERVICE settings content.
SERVICE settings also emits an existing `crm-dashboard.js:128` chart initialization
error; the same error reproduces using the original Workspace Settings template at
both desktop and mobile sizes. That shared script is outside this classification
change. No external provider checks are required by this block.

Final results:

- Full PostgreSQL six-app suite: 1,396 tests, OK; two optional real-Redis tests skipped.
- Focused PostgreSQL regression/classification suite with the normal password hasher: 60 tests, OK, no skips; includes both enrollment/profile concurrency tests and the existing query budget.
- Strict-mode SQLite application/enrollment/checkout suite: 171 tests, OK; four PostgreSQL-only concurrency tests skipped.
- Desktop/mobile application interactions and no-JavaScript validation/submission: passed, no application script errors.
- Desktop/mobile Logistics and SERVICE Workspace Settings content: passed; the existing SERVICE chart-script error also reproduced on the original template.
- Django system checks, migration-drift check, Ruff, formatting checks, JavaScript syntax check, and `git diff --check`: passed.

## Recommended next block

Define the smallest Warehousing workflow, roles, and tenant-owned data requirements
before implementing that module. Keep operating classification informational until
an explicit product capability/access policy is specified.

## Files changed

- `src/apps/businesses/business_data_inventory.py`
- `src/apps/businesses/business_data_purge.py`
- `src/apps/businesses/views.py`
- `src/apps/logistics/admin.py`
- `src/apps/logistics/demo.py`
- `src/apps/logistics/enrollment.py`
- `src/apps/logistics/forms.py`
- `src/apps/logistics/inventory.py`
- `src/apps/logistics/models.py`
- `src/apps/logistics/services.py`
- `src/apps/logistics/test_demo_data.py`
- `src/apps/logistics/test_enrollment.py`
- `src/apps/logistics/test_parcel_metadata.py`
- `src/apps/logistics/test_readiness.py`
- `src/apps/logistics/test_retention_migration.py`
- `src/apps/logistics/tests.py`
- `src/apps/logistics/usage.py`
- `src/static/assets/js/logistics-application.js`
- `src/templates/businesses/settings.html`
- `src/templates/logistics/application_form.html`
- `docs/LOGISTICS_OPERATING_AREAS.md`
- `src/apps/logistics/classification.py`
- `src/apps/logistics/migrations/0010_operating_classification.py`
- `src/apps/logistics/test_classification.py`
