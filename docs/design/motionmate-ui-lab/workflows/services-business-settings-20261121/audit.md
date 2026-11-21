# Business Settings — Django source audit

21 November 2026 · Full Redesign · SERVICE · source evidence only

Primary screen: `/businesses/settings/` (`business_settings`). The existing
operational sub-screen `/businesses/settings/booking/` belongs to this workstream.
This audit inspected actual Django sources without starting Django, contacting a
database/provider, visiting pages or submitting forms. Browser appearance and
runtime behavior are pending. `source-audit.json` records source/Git identities;
it is not an interactive BEFORE snapshot.

## Settings data and save boundaries

`src/apps/businesses/views.py:355–478` uses the existing current-Business and
membership resolvers. The page has login protection and GET/POST, with deliberately
different authorization for personal and company changes.

| Form/surface | Existing contract |
| --- | --- |
| Business form | `BusinessSettingsForm`, unprefixed, `id="business-settings-form"`, multipart POST, CSRF, hidden `section=business` (also the default if omitted). Owner/admin plus workspace modification access only. Saves the current Business, never a posted Business ID. |
| Company/contact | `name`, `business_type`, `email`, `phone`. No active website/tax-ID/brand-color editor; legacy profile values are not current Business configuration. |
| Address | `country`, `address_line_1`, `address_line_2`, `city`, `region`, `postal_code`, `address`. Country-dependent form labels and postcode normalization; optional legacy freeform notes remain. |
| Region | `timezone` is an existing IANA-named text field; `default_locale` is optional text with future-formatting help. Do not imply a language translation switch, currency conversion or new timezone validation. |
| Invoice defaults | `currency`, `tax_label`, `tax_rate`, `invoice_prefix`, `invoice_start_number`, `invoice_logo`, `remove_invoice_logo`. Existing logo preview, corrupt-logo fallback and mutually exclusive replacement/removal. Keep currency in this save scope. |
| Personal form | `PersonalAccountForm(instance=request.user, prefix="account")`; own first/last name, sign-in email, phone, date of birth and address. POST `section=account` to `business_settings#my-account`; own Save personal details. Available with restricted/no workspace too. |
| Security | Existing `password_change` link; no password fields in these forms. Password/login/logout/reset flow is shared authentication and excluded from implementation. |
| Configuration links | Team; guarded Services and import links; booking availability capability; owner-only Subscription. Retain current named routes and exact gates. Redesigning their destinations is outside this task except the booking settings sub-screen. |
| Online booking | Existing `public_booking_share_card.html`, readiness supplied by `get_public_booking_share_context`, guarded by capability/editability on Settings. Existing Copy/Finish setup/open behavior is retained; no new booking-state calculation. |

Business/logo updates are atomic and lock the Business. PNG/JPEG normalization,
size limits, replacement/removal conflicts and rollback on invalid fields are
existing behavior (`forms.py:200`, `invoice_logos.py`, `docs/invoice_logos.md`).
The company logo is an **invoice** logo; it is not workspace-shell branding.
Newly generated PDF/HTML uses the current logo, including regenerated old invoices;
already downloaded/sent files are unchanged. This screen must explain that scope.

Business changes from Staff/Accountant/Viewer are 403. Owner/admin without write
access follows the existing subscription redirect. Personal changes remain
allowed. Unknown sections return 400. Legacy `/accounts/profile` GET redirects
to permitted anchors, without creating a profile; compatibility POSTs keep their
own validation/profile binding and do not update Business defaults. Retain
`SaaSUserProfile`, stored defaults and fallback properties without copying data.

## Operational settings and availability

`views.py:481–669`, the existing `booking_settings.html` and booking/availability
forms define an independent page, not fields in the company settings POST.

| Surface | Existing behavior to preserve |
| --- | --- |
| Access | Owner/Admin/Staff and `business_module_required("booking_availability")`, current Business, existing write/module checks. Staff sees only own active availability and own inactive count, with server-bound staff selector. Accountant/Viewer denied. |
| Request rules | Owner/Admin only: `form_kind=settings`; `booking_enabled`, `default_duration_minutes`, `minimum_notice_hours`, `maximum_days_ahead`, `buffer_minutes`, `confirmation_mode`, `public_booking_instructions`, `cancellation_policy_text`, `reschedule_policy_text`. Staff receives the existing limited read summary. |
| Single entry | Own CSRF form, `form_kind=availability`; `staff_member`, `day_of_week`, `start_time`, `end_time`, `is_active`. Owner/Admin can choose eligible current-tenant staff or business-wide; Staff is bound to self. |
| Bulk entry | Separate CSRF form, `form_kind=bulk_availability`; `staff_member`, `days`, `start_time`, `end_time`, `is_active`. Existing checked-day rendering, atomic create and end-after-start validation. |
| Tabs | Preserve `availability-entry-tabs`, single/bulk tab and panel IDs, `data-bs-toggle`, targets, server-selected `availability_form_kind` and invalid-form tab. No replacement calendar, merged submission or automatic save. |
| Existing records | Active list: staff/business-wide, day, time and POST Deactivate; inactive count is retained. No existing edit/reactivate/calendar action. Tenant-scoped `business_weekly_availability_deactivate`; Staff can deactivate only own block. |
| Booking status/share | Existing allowed/enabled/readiness facts and server-provided checklist. Public-booking entitlement and availability preparation are separate; lack of public booking does not automatically remove all preparation fields. |

## Source findings and discrepancies

1. Current Settings places two large workspace/account summaries above a long
   anchor-navigation form. Heading starts at h2. Small metadata/navigation text
   and repeated card framing compete with form content. Booking settings places
   the full share panel above rules and narrow availability editors. These are
   composition findings, not measured browser results.
2. Booking settings GET uses `get_or_create` for `BusinessBookingSettings`
   (`views.py:491`). The current-Business resolver also maintains session context.
   Do not visit ordinary applications as if these were guaranteed write-free.
3. Booking form help/template says manual confirmation only, while the model
   exposes both `request_only` and `auto_confirm_later`. Retain values, choices and
   downstream behavior; do not add an automation promise or silently remove a
   stored choice. Clarifying actual booking policy is separate functional work.
4. Single and bulk forms are unprefixed and render repeated generated field IDs
   (for example `id_start_time`). This is a source-level accessibility concern;
   real rendering/label association must be checked before any proposed ID repair.
   Do not change hooks/prefixes silently during presentation work.
5. `docs/unified_business_settings.md` contains historical SQLite verification;
   the current workflow requires explicitly authorized disposable PostgreSQL.
   Prior test counts are history, not a current pass or runtime authorization.

## Shared consumers and preservation

Settings template/CSS/field include, the account form/resolver, profile aliases and
booking share include have shared consumers. Logistics uses additional transport-
name forms, country choices, cancellation service charge, location configuration
and operating profile. Its `section=logistics_transport`, names/default retention,
forms, links, JS and operational access must be unchanged.

A future integration should branch only for resolved `SERVICE`, use independent
Services composition/assets, and keep current Logistics and no-business fallback
rendering. Do not retheme the global shell or edit shared settings CSS/field/share
includes in place. Existing Manrope assets and licenses can be reused unchanged.
The completed catalogue/import/subscription screens are link destinations, not
implementation scope. Team files belong to the independent Team workstream.

Relevant source tests were inspected: `UnifiedSettingsTests`,
`BusinessSettingsViewTests`, `BusinessBookingSettingsTests`,
`InvoiceLogoSettingsTests`, legacy profile tests and invitation/location settings
coverage. No tests ran. Validation resources, real browser evidence and frozen
BEFORE require Gate B authorization; see `validation.md` for the planned matrix.
