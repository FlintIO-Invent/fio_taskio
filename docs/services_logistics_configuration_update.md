# Services and Logistics configuration update

The settings/profile interface described below is superseded by [Unified Business Settings](unified_business_settings.md). Both products now use that single page, including personal settings; there is no separate Account Profile screen.

## Audit and scope

| Area | Existing implementation and boundaries | Focused change |
| --- | --- | --- |
| Team | `BusinessInvitationForm`, `business_team_members`, and the shared invitation utilities serve both products. Owner/admin role assignment, plan limits, email binding, seven-day expiry, and subscription checks already exist. Acceptance creates or reactivates `BusinessUser`; an active member's role stays unchanged. | Add an optional Logistics location to the invitation and carry it to the existing membership assignment during acceptance. |
| Location access | `LogisticsLocation` belongs to one business. `LogisticsLocationAssignment` holds access, current work context, and separately approved operational writes. Access remains blocked until location access is reviewed. Owners/admins already have business-wide access; their selected location is context only. Unassigned memberships are supported. | List active current-business locations only. Recheck tenant and active status under the existing Logistics business lock at creation and acceptance. New assignments cannot operate; administrator assignments are context only. Preserve existing grants/current locations, and add no access to existing active members. |
| Categories/services | Existing `ServiceCategory` and `BusinessService` models are separate. Categories already support nullable business ownership for legacy data. Service imports resolve only current-business categories by name/code, deduplicate new category keys, and support existing inactive categories for legacy compatibility. | Keep both models and the existing import implementation. Make the combined upload discoverable from Settings, Services, Categories, and Data Import. Do not alter legacy/global category consumers. |
| Import validation | The shared CSV parser, service form validation, authoritative stored preview, and transaction-based execution already provide Upload → Validate → Preview → Confirm → Result. Invalid/review rows block execution. External codes propose explicit previewed updates; duplicate codes require review. Execution rechecks actor, tenant, role, job expiry, capability, service matches, and categories. A business lock serializes imports and all service/category writes share a transaction. | Explain category creation/reuse, all-or-none writes, and existing external-code updates. Reuse the downloadable template, including its category and supported service fields. No new dependencies or parser/execution changes. |
| Business Settings | Owner/admin-only `BusinessSettingsForm` stores company identity/contact/address, country, locale, timezone, currency, tax label/rate, invoice prefix and start number on `Business`. Consumers include address/localization helpers, invoice creation/numbering/PDF, service default tax/pricing, public booking, and Logistics profile/location configuration. | Group links to the existing company form, team, catalog/upload, booking rules, Logistics locations/access, and owner-only subscription/payment screen. Keep existing URLs and daily operations. |
| Booking configuration | `BusinessBookingSettings` stores enabled status, duration, notice period, booking horizon, buffer, confirmation mode, public instructions, cancellation and reschedule policies. `WeeklyAvailability` stores business/staff availability. These feed the existing booking/appointment flow. Owners/admins manage business rules; staff keep their existing availability access. | Link the existing Services booking settings screen, including plans without public booking. No changes to booking or appointment behavior. |
| Logistics configuration | Location management stores tenant facilities: name/code, type, country, verified reference, address and active status. These feed route/site selection and location access. `LogisticsProfile` holds operating areas/modes and reviewed-access/verified-operation rollout timestamps. | Retain the existing profile summary and link existing location/access screens. No new editing screen for classification or changes to rollout gates. |
| Account Profile | Personal details are edited by `SaaSBasicInfoForm`; password/security keep existing account routes. Profile forms also retain legacy workspace contacts, currency/prefix/due days, appearance, payment instructions and footer fields in `SaaSUserProfile`. The current billing implementation does not consume the legacy payment-instruction/footer settings. | Keep compatibility forms/storage intact and direct business configuration to Business Settings. Do not reinterpret per-user legacy values as shared business data. |
| Payments | Motionmate subscription/payment management already lives on the owner-only subscription page. Customer receipt recording and adjustment are invoice operations, with existing financial permissions. There is no existing shared customer-payment configuration form. | Link subscription/payment configuration for owners. No new customer payment configuration, provider integration, financial-record changes, or operational workflow changes. Moving legacy payment instructions to shared business storage needs a separately scoped ownership/consumer migration. |

## Migration

`businesses.0032_businessinvitation_location` adds one nullable, protected FK to `logistics.LogisticsLocation`, depending on the current businesses/logistics migration leaves. Existing invitations keep `NULL`; no backfill, data rewrite, or membership migration is needed. Referenced locations cannot be deleted while invitations retain the reference; existing location archiving remains available.

## Files

- `src/apps/businesses/{models,forms,utils,views}.py`
- `src/apps/businesses/migrations/0032_businessinvitation_location.py`
- `src/apps/businesses/test_configuration_update.py`
- `src/apps/crm/test_combined_service_import.py`
- `src/apps/businesses/test_configuration_verification.py`
- `src/apps/accounts/views.py`
- `scripts/configuration_update_browser_check.py`
- `src/templates/businesses/{settings,team_members}.html`
- `src/templates/accounts/main/saas_profile.html`
- `src/templates/crm/settings/{business_service_import,business_service_list,service_category_list}.html`
- `src/templates/crm/importing/data_import.html`
- `src/templates/crm/importing/service_preview.html`
- This report.

## Manual verification

Use a disposable local database with migrations applied; do not use live business or Stripe data.

1. As a Logistics owner/admin, open Team Members on desktop and mobile. Check the optional location field, error display, and pending-invitation location. Invite a new Staff user and accept with that email. Verify the matching membership/location assignment, restricted location visibility after review, and no operational writes until separately approved.
2. Invite an Admin with a location. Verify it acts as work context. Accept a legacy location-free invitation and a Services invitation. Verify Services has no location selector. Attempt a foreign/inactive location POST and verify rejection without creating an invitation.
3. In each product, download the upload template. Include two services sharing a new category and another using an existing category. Check the preview, then confirm. Verify one new category and correct service relationships. An invalid price or duplicate external code must block confirmation; no catalog changes should appear. Review explicit updates for existing external codes.
4. In each product, check Business Settings on desktop/mobile as owner and admin. Follow the team, catalog, booking (Services), and location/access (Logistics) links. Only owners should see the subscription/payment configuration link. Staff, Viewer, and Accountant must be denied Business Settings GET/POST. Check Account Profile and existing password/security links remain usable.

## Initial implementation verification

- **140 tests passed** in 40.362 seconds using a disposable in-memory SQLite database, including 18 new tests. The selection covers existing invitation views/acceptance, Business Settings, service validation/execution, import UX/permissions, and Logistics location access.
- Ruff passed for changed Python files. `manage.py check`, `makemigrations --check --dry-run`, compilation of all six changed templates, and `git diff --check` passed.
- The new migration was exercised only in the isolated test database. No production migration, push, deployment, live business modification, or Stripe call was performed.
- PostgreSQL concurrency and browser desktop/mobile interaction were not tested in the initial implementation run. The pre-staging verification below supersedes that limitation. No live provider verification is implied.

## Pre-staging verification — 18 October 2026

The audit, tracked diff, new migration and previously untracked tests were reviewed before verification. All work stayed local and unstaged. The existing stopped PostgreSQL 14.24 test cluster at `/tmp/motionmate-e4-pg-j2ejIPa4` was started with its private Unix socket and TCP disabled. New empty base databases `mm_config_verify_20261018` and `mm_config_browser_20261018` were used; Django created disposable `test_` databases. No application database, customer records, provider configuration or Stripe data was used or copied.

Confirmed defects fixed:

1. **Concurrent first-time acceptance returned HTTP 500.** Two anonymous requests could both enter signup and race on the unique email before the invitation/membership lock. Reproduced on PostgreSQL. The signup branch now handles an integrity collision only when the invited email exists after rollback, redirects the losing request to sign-in, and does not authenticate it as the winning account. Other integrity errors still propagate. The PostgreSQL regression exercises both Services and Logistics and asserts one user/membership, one Logistics assignment, and only one authenticated request.
2. **Mobile action headers overflowed or compressed labels.** Reproduced in Services Team, Business Settings and catalog/category management at 390px. Existing action groups now wrap. The Business Settings identity card stacks the avatar on mobile so the workspace name remains readable.
3. **Import preview leaked horizontal page overflow.** Reproduced for valid and invalid previews in both products. Absolutely positioned accessibility labels inside the scrolling table escaped its containing block. Positioning the existing scroll wrapper contains the labels and preserves horizontal table scrolling and screen-reader text.
4. **Personal profile saves failed silently.** The required legacy `assigned_location` input and its errors were inside an HTML comment. A real browser submission reproduced the required-field error. Rendering the current value as a hidden input restores personal-detail saves without changing models, legacy storage, tenant configuration, or the separate Logistics assignment model.

Verified behavior:

- Real browser selection, signup acceptance and persistence work for Logistics locations and Services location-free invitations. PostgreSQL checks reject foreign/inactive locations, preserve legacy invitations and role binding, keep administrator business-wide access, and preserve an existing staff operational grant/current work site when reactivating membership. New location assignments never enable operational writes.
- Competing acceptances of one invitation create one membership/assignment. Duplicate legacy invitations do not add access to an already active member. Location deactivation while acceptance waits on the business lock rejects acceptance without membership writes.
- The nullable migration preserves an invitation's business, token, role and membership records, leaves its location NULL, and creates the expected PostgreSQL FK. All migration operations ran only in disposable test databases.
- Browser uploads cover new/existing categories, repeated names with different casing, proposed external-code updates, template download, confirmation and invalid prices. Every stored service field is compared against the authoritative preview after execution. Invalid uploads leave complete category/service snapshots unchanged. Mobile previews can scroll to changes and errors without scrolling the whole page horizontally.
- Owner/Admin hub links return successful responses; only owners see subscription/payment configuration. Staff, Accountant and Viewer receive 403 for Business Settings GET/POST. All five roles can access Account Profile; legacy sections remain explicitly labeled. Personal-profile saves are checked separately from business configuration changes.

Reproducible verification sources are `src/apps/businesses/test_configuration_verification.py` and the optional `scripts/configuration_update_browser_check.py`. Browser checks use the installed Chromium 148 executable selected through `PWA_CHROMIUM`, at 390×900 and 1440×900. External browser requests are blocked; email uses the in-memory backend. Physical devices, Safari and live email/provider integrations remain outside this verification block. Broader shared payment settings and legacy-profile migration remain separate work.

Final results:

- **147 PostgreSQL tests passed** in 79.378 seconds after the concurrency/layout fixes. This includes seven new role-preservation, acceptance-race and migration checks alongside the original focused selection.
- **15 affected PostgreSQL tests passed** in 37.520 seconds after the personal-profile template fix: the new verification module, existing invitation acceptance tests and existing profile tests.
- **Four browser scenarios passed** in 109.539 seconds after all fixes: signup invitations, catalog uploads, settings/profile access and links, and personal-profile saves. Each covers both products. The access matrix covers all five roles at desktop/mobile sizes; personal saves cover all five roles and assert unchanged business configuration. Preview fields match execution, invalid imports preserve snapshots, and mobile table scrolling exposes changes/errors.
- Browser summaries `imports.json`, `invitations.json`, `settings-profile.json` and `profile-save.json` in `/tmp/motionmate-config-verification` contain no JavaScript errors or horizontal page-overflow failures. Screenshots are in the same directory; `before-fixes/` contains the earlier overflow diagnostics.
- Logs: `/tmp/motionmate-config-postgresql-final.log`, `/tmp/motionmate-config-affected-final.log`, `/tmp/motionmate-config-browser-final.log`. Failure reproductions remain in `/tmp/motionmate-config-signup-race.log` and `/tmp/motionmate-config-profile-save.log`.
- Django system checks, migration-drift checks, compilation of all eight changed templates, Ruff, Black checks for the two new verification sources, and `git diff --check` passed.
- No blocker remains for this focused block within the tested environments. No staging, commit, push, deployment, production migration or live-data modification was performed. Disposable databases are removed after verification and the previously stopped private cluster is returned to that state.
