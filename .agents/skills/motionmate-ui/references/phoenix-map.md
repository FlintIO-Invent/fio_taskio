# Phoenix and application map

Use this map when selecting a component or locating its current integration. All code paths below are relative to the repository root. Recheck callers and loaded assets before editing; these are starting points, not certified examples or permission to change their consumers. Follow the root `AGENTS.md` links for domain rules rather than duplicating them here.

## Reference library

`design_references/phoenix/package.json` identifies Phoenix 1.23.0. The directory is read-only and Git-ignored; do not run its build, edit it, or force-add it.

| Need | Reference under `design_references/phoenix/` |
| --- | --- |
| Navigation and layout | `public/documentation/layouts/`, `public/demo/` |
| Cards, buttons, badges, alerts, modals, offcanvas, tabs and feedback | `public/modules/components/` and relevant form examples |
| Tables and pagination | `public/modules/tables/`, `public/modules/components/pagination.html` |
| Forms, validation, searchable selects, date pickers | `public/modules/forms/` |
| Wizard presentation | `public/modules/forms/wizard.html` |
| CRM composition | `public/apps/crm/`, `public/dashboard/crm.html` |
| Theme configuration | `public/documentation/customization/` |
| Token definitions | `src/scss/theme/_colors.scss`, `src/scss/theme/_variables.scss`, `src/scss/theme/_variables-dark.scss`, `src/scss/theme/_root.scss` |

Phoenix examples supply presentation and interactions, not Motionmate authorization, booking rules, settlement logic, or operational transitions. Do not copy demo data or nonfunctional actions into production templates.

## Existing application patterns

| Area | Inspect first | Integration detail |
| --- | --- | --- |
| Shared workspace shell | `src/templates/inheritance/dashboard_parent.html` | Shared role/module conditions, theme control, navigation, asset order; changes may affect both verticals |
| Theme and branding | `src/static/assets/js/config.js`, `src/static/assets/css/user.css`, `src/templates/includes/motionmate_logo.html` | Phoenix uses `data-bs-theme`; the shell loads `user.min.css` or `user-rtl.min.css`, so verify source/output handling |
| Services work list | `src/templates/appointments/workspace.html`, `src/apps/appointments/workspace.py` | Existing read projection, filters, pagination, and independent request/appointment entitlements |
| CRM list | `src/templates/crm/main/client_list.html` | List.js sorts/paginates rendered rows; preserve server-filter parameters and do not imply global search from a partial dataset |
| Draft client creation | `src/templates/crm/includes/draft_client_modal.html`, `src/static/assets/js/draft-client.js` | Preserve draft state, modal destination and JSON contract; Logistics and invoices have separate integrations |
| Logistics lists/mobile | `src/templates/logistics/parcel_list.html`, `src/templates/logistics/shipment_list.html`, `src/static/assets/css/logistics-mobile.css`, `src/static/assets/js/logistics-mobile.js` | Existing `.logistics-workspace` scope; mobile cards/stacked rows and desktop tables have different presentation needs |
| Logistics fields and registration | `src/templates/logistics/includes/form_field.html`, `src/templates/logistics/parcel_registration.html`, `src/static/assets/js/parcel-wizard.js` | Preserve error IDs, conditional fields, progress, POST actions and persisted workflow state |
| Scanner | `src/templates/logistics/scan.html`, `src/static/assets/js/logistics-scan.js`, `src/static/assets/js/logistics-camera.js` | Typed/pasted/keyboard input remains available; camera is optional |
| Invoice presentation | `src/templates/billings/includes/invoice_status.html`, `src/apps/billings/presentation.py` | Consume authoritative financial presentation after access checks; lifecycle is separate from payment indicators |
| Public booking | `src/templates/crm/forms/public_booking.html`, `src/templates/inheritance/split_forms_parent.html` | Custom booking wizard inside Phoenix; preserve slots, client-type conditions, validation and operation key |
| Marketing site | `src/templates/public_site/base.html`, `src/static/public_site/` | Separate Silicon theme and theme-state convention; do not mix its CSS with workspace Phoenix |

## Token and asset cautions

- Use semantic values such as `--phoenix-body-color`, `--phoenix-body-bg`, `--phoenix-border-color-translucent`, and `--phoenix-primary` where suitable; inspect both light/dark definitions and complete hover/focus/disabled states.
- Changing `--phoenix-primary` alone does not update every compiled button or utility value. Reference Sass imports user variables before defaults, but that does not establish an application build pipeline.
- Phoenix's type utilities differ from familiar Bootstrap assumptions: inspect `fs-8`, `fs-9`, and `fs-10` before choosing hierarchy. The workspace currently loads Nunito Sans.
- Existing Logistics mobile styles use 44px touch targets and Bootstrap's 992px navigation breakpoint. Treat these as useful existing conventions, not permission to apply Logistics styles to Services.
- `src/static/` contains served source assets; `src/staticfiles/` is collected output. Confirm the active parent and asset path instead of editing generated output or assuming `.min.css` reflects another file automatically.

## Verification starting points

Inspect relevant existing scripts such as `scripts/unified_appointments_browser_check.py`, `scripts/draft_client_browser_check.py`, `scripts/logistics_scan_browser_check.py`, and `scripts/invoice_terminology_browser_check.py`. They may write fixtures and screenshots: their presence does not authorize execution. Use only a suitable authorized disposable environment, and do not treat prior reports as current test results.
