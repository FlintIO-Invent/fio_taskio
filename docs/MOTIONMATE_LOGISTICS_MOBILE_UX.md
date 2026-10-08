# Motionmate Logistics mobile UX

This block adapts the existing Django workspace for touch use. It follows the PWA
foundation and adds no migrations, models, scanning, native integration, offline
writes, or billing policy changes.

## Rendered audit

Chromium inspected 14 populated screens at 320, 390, 430, 600, 800 and 1440px:
dashboard, Client list/detail, Parcel list/register/detail/update, Shipment
list/create/edit/detail, manifest, and Invoice list/detail. Fixtures include long
client/company names, routes, tracking codes, transportation references, invoice
lines, and 60 eligible Parcels. Screenshots and layout measurements are written
under `/tmp/logistics-mobile-ux/before/` and `/tmp/logistics-mobile-ux/after/`.

Confirmed baseline problems:

- Invoice detail header exceeded the document width by 172px at 320px and 70px
  at 390px, clipping its actions.
- At 390px, table containers held Client rows 1661px wide, Parcel rows 1093px,
  Shipment rows 1024px, assigned Parcel rows 1050px, manifest rows 963px,
  and Invoice rows 631px. Client-detail Parcel tables were also 800px wide.
- Buttons and form controls frequently fell below a 44px touch target. Client
  action menus depended on reveal styling; icon controls lacked useful names.
- At 390px, registration's submit action began around 1724px down the page;
  Shipment create/edit actions began around 1548/1906px. Recent Parcel events
  followed all optional metadata and billing sections.
- The dashboard stacked six large operational cards and finance cards ahead of
  quick actions. Attention items followed status distribution and activity.
- The narrow header's search action referenced an absent search modal. Workspace
  links lacked route highlighting. The dashboard linked to Public Tracking.

## Resulting presentation

The shared shell loads `logistics-mobile.css` and `logistics-mobile.js` only for
LOGISTICS businesses. Layout rules apply below Bootstrap's existing 992px
desktop navigation breakpoint. SERVICE retains its existing presentation;
shared icon/checkbox names and pagination labels improve accessibility.

Parcel and Shipment lists use compact mobile cards with their existing desktop
tables. Parcel cards show tracking code, client, state, route and, when accessible,
same-tenant Shipment/mode context. Shipment cards show reference, mode, state,
route, departure, ETA and a tenant-filtered Parcel count. Existing query filters,
pagination, tenant checks and assignment links remain authoritative.

Client, Invoice, assigned Parcel and manifest tables retain the original rows and
List.js behavior but stack as labelled records on small screens. Table roles and
header relationships remain explicit. Manifest print media retains the existing
table and totals; the screen-only adaptation does not change CSV output.

Parcel detail exposes route and Shipment mode at the top, compact operational
details, newest three events, and a full-history link. Existing Edit/Record Update
permissions remain in force. Shipment detail exposes its mode/count and a status
shortcut; mobile lifecycle actions precede transportation and billing detail.

Form actions stick inside their existing form near the viewport bottom. Required
fields, optional Parcel tabs, inline Add Client, UUID retry tokens, expected
status/revision fields and normal CSRF-protected POSTs remain intact. Shipment
forms prioritize mode, route and searchable Parcel assignment on mobile. Decimal,
quantity, phone and search fields receive suitable keyboard hints. Existing
Choices selects retain search, wrap long labels and expose named search inputs.
Mode-specific groups retain entries and keep erroneous fields reachable.

Mobile Shipment status buttons come from the existing status form's permitted
transitions. Cancellation uses a distinct danger button and confirmation. Parcel
and Shipment selectors display only currently permitted transitions after errors,
while form validation still accepts historical receipt values for existing service
replay checks. Services decide every lifecycle, assignment and idempotency outcome.

The mobile dashboard orders KPIs, quick actions, attention, active Shipments,
recent activity, status distribution and finance. Existing DOM nodes move at the
breakpoint so keyboard/reader order follows the layout, and return to their
desktop positions on resize. KPI content is retained and decorative icons are
reduced. Existing gated sidebar links remain, with route highlighting and a working
Parcel search link. Public Tracking stays outside workspace navigation; the
existing contextual Parcel tracking POST remains available.

## Security and compatibility

- Business/session authentication, CSRF middleware, tenant query constraints,
  role gates, module entitlements and subscription restrictions are unchanged.
- No write services, lifecycle policy, billing calculations or public tracking
  handlers changed. Shipment counts additionally filter both Parcel and Client
  ownership. Parcel-card Shipment context requires its own module entitlement
  and matching business.
- Private pages still send `private, no-store`. The PWA worker's seven-item public
  allowlist is unchanged; no mobile operational data enters persistent caches.
- New CSS/JS use Django static resolution and the existing production hashed
  WhiteNoise build. There is one app and one deployment path.

## Files changed

Presentation helpers/context:

- `src/apps/logistics/dashboard_forms.py`
- `src/apps/logistics/forms.py`
- `src/apps/logistics/shipment_forms.py`
- `src/apps/logistics/views.py`
- `src/apps/logistics/shipment_views.py`

Assets:

- `src/static/assets/css/logistics-mobile.css` (new)
- `src/static/assets/js/logistics-mobile.js` (new)
- `src/static/assets/js/logistics-workflows.js`

Templates:

- `src/templates/inheritance/dashboard_parent.html`
- `src/templates/crm/main/client_list.html`
- `src/templates/crm/main/client_detail.html`
- `src/templates/billings/invoice_list.html`
- `src/templates/billings/invoice_detail.html`
- `src/templates/logistics/parcel_list.html`
- `src/templates/logistics/parcel_detail.html`
- `src/templates/logistics/parcel_form.html`
- `src/templates/logistics/shipment_list.html`
- `src/templates/logistics/shipment_detail.html`
- `src/templates/logistics/shipment_form.html`
- `src/templates/logistics/shipment_manifest.html`
- `src/templates/logistics/includes/dashboard_snapshot.html`
- `src/templates/logistics/includes/client_parcel_rows.html`
- `src/templates/logistics/includes/form_field.html`

Verification/documentation:

- `src/apps/logistics/test_mobile_ux.py` (new)
- `src/apps/logistics/test_workspace.py`
- `src/apps/logistics/test_local_billing_bypass.py`
- `scripts/logistics_mobile_check.py` (new)
- `docs/MOTIONMATE_LOGISTICS_MOBILE_UX.md` (new)

## Verification

- Full SQLite suite: **1480 tests, OK, 31 skipped** (1449 passed), covering accounts,
  businesses, CRM, billing, Logistics, appointments and PWA. Skipped checks include
  PostgreSQL-only concurrency and shared-cache integration; these are not claimed.
- Six new server tests passed: scoped cards/counts/order, currently permitted
  status controls with replay validation retained, role/CSRF enforcement, expired
  billing-grace read-only restrictions, SERVICE shell isolation, and private cache
  headers/no authenticated Public Tracking navigation.
- Browser acceptance passed: **84 populated screen/viewport checks** with no
  document overflow, no mobile table overflow, no short audited mobile controls, correct
  dashboard hierarchy, reachable sticky form actions and no page errors.
- A 320px touch-browser workflow passed inline Client creation, browser and server
  errors with retained entries, Parcel registration/receipt, ROAD Shipment creation
  with search over 60+ eligible Parcels, Shipment readiness/departure/arrival,
  Parcel readiness/delivery, Shipment completion, dismissed/accepted cancellation,
  released assignments and mobile sidebar highlighting. A 420px reduced-height
  viewport also kept a focused field and submit control reachable.
- Existing PWA browser checks passed all eight SERVICE/LOGISTICS × desktop,
  Pixel 7, iPhone 13 and iPad Mini Chromium profiles. These installed, launched and
  uninstalled a real Chromium standalone app and exercised login/logout, sidebar,
  back navigation, forms/modal, offline fallback, rejected writes and private
  cache safety.
- Ruff, Black, JavaScript syntax checks, Django system checks, migration-drift
  check and `git diff --check` passed. No migrations were generated.
- Production `collectstatic` passed with a temporary static root and DEBUG off;
  the mobile CSS, mobile shell script and workflow script resolved to hashed assets.

Repeat the suites using an isolated database and the installed Chromium binary:

```bash
export DATABASE_URL= DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory:
export DEBUG=True LOGISTICS_LOCAL_BILLING_BYPASS=False PYTHONPATH=src:.
export PWA_CHROMIUM=/path/to/chrome
.venv/bin/python src/manage.py test apps.accounts apps.businesses apps.crm apps.billings apps.logistics apps.appointments taskio.test_pwa --parallel 4 --noinput
.venv/bin/python src/manage.py test scripts.logistics_mobile_check --noinput
.venv/bin/python src/manage.py test scripts.pwa_browser_check --noinput
```

Final logs are `/tmp/logistics-mobile-regression-final.log`,
`/tmp/logistics-mobile-browser-acceptance.log`,
`/tmp/logistics-mobile-write-acceptance.log` and
`/tmp/logistics-mobile-pwa-final.log`. Layout JSON and screenshots live in
`/tmp/logistics-mobile-ux/after/`; standalone evidence lives in
`/tmp/motionmate-pwa-browser/`.

## Remaining verification and next block

Chromium device emulation and reduced viewport height do not validate physical
Zebra devices, glove use, an Android soft keyboard, or Safari/WebKit's installed
iOS behavior. Validate these on real devices, including portrait rotation,
keyboard overlap, VoiceOver/TalkBack, manifest printing and production HTTPS/static
delivery. No hardware integration was attempted.

Recommended next PWA block: a real-device pilot and accessibility acceptance pass,
followed by a separately scoped scanner-input design once that foundation is accepted.
