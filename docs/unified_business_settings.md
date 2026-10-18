# Unified Business Settings

This update supersedes the separate Account Profile experience described in the earlier configuration report. Services and Logistics now render the same Business Settings page.

## Fields and storage

- **My account:** first/last name, sign-in email, personal phone, date of birth and personal address. `PersonalAccountForm` reuses the existing account validation and saves only `request.user`. The existing password-change control uses the unchanged secure account-management flow.
- **Business details, address, region and invoicing:** the existing `BusinessSettingsForm` saves only the resolved current Business. Existing owner/admin and subscription write restrictions remain in force. Subscription/payment configuration stays owner-only.
- The duplicate user-level company/workspace/contact/currency/invoice controls, replicated default summaries and transition notices have been removed from the page. Their stored values are retained. Inspection found no active billing consumer of `SaaSUserProfile` invoice appearance, terms, instructions or footer fields; these have not been promoted into business settings or presented as effective invoice configuration.
- User `company_name`/`assigned_location`, every `SaaSUserProfile` field and existing fallback properties remain untouched by the new personal form. No copy from profile defaults to Business occurs. There is no model or migration change in this block.

## Access and compatibility

Every signed-in user can access their own personal section, including users with a restricted subscription or no current business. Business forms and configuration are shown only when the current owner/admin can modify the workspace. Restricted roles receive 403 on business POSTs; an owner/admin without workspace write access retains the existing subscription-access redirect. Changing the form section or posting another user/business ID cannot expand access.

All settings/profile navigation targets Business Settings. The old profile template has been removed. Old profile GETs redirect to `#my-account`, `#business-details`, `#invoice-defaults` or `#security` as permitted. Redirect GETs do not create a profile or change records. Existing profile POSTs keep their original form validation and signed-in-user/profile binding, then redirect to the unified page. Invalid compatibility submissions report validation errors without changing stored values. No compatibility path writes Business defaults.

## Focused verification

The regression module is `src/apps/businesses/test_unified_settings.py`. Existing profile and Business Settings tests were updated only for the intended redirects and personal access change. Only those focused tests and the two settings-related browser scenarios in `scripts/configuration_update_browser_check.py` are run for this block; invitation/import/billing suites are not rerun.

All write checks use disposable SQLite or a fresh Django test database in the existing private PostgreSQL test cluster. They use synthetic users/workspaces, never the normal local database or its records. Browser checks cover both products, all five roles, desktop/mobile layouts, personal saves, old-profile redirects, owner-only links and absence of old/duplicate configuration controls. Existing profile fallback values, other users and complete business snapshots are checked for preservation.

Results: **17 focused regression tests passed** in 6.183 seconds on in-memory SQLite. **Two selected browser scenarios passed** in 46.741 seconds using a disposable PostgreSQL test database and Chromium at 390×900 and 1440×900. Both products and all five roles were covered; no JavaScript errors or horizontal page overflow were reported. Django checks, migration-drift checks, compilation of the unified/navigation templates, Ruff and `git diff --check` passed. No full-suite run was performed.

Logs: `/tmp/motionmate-unified-settings.log` and `/tmp/motionmate-unified-browser.log`. Screenshots and empty-error summaries (`settings-profile.json`, `profile-save.json`) are in `/tmp/motionmate-config-verification/`. The old profile template is deleted and there are no references to its route, “Account Profile” or the removed default panels anywhere in the UI templates.

No blocker remains. The disposable PostgreSQL base was empty and removed after the test runner removed its test database; the existing private cluster is returned to its original stopped state. No normal local database connection, migration, record change, push or deployment was performed.
