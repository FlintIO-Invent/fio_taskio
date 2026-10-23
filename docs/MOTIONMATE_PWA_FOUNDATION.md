# Motionmate PWA foundation

## Frontend audit

Motionmate renders its authenticated UI through `inheritance/dashboard_parent.html`
and the legacy `account_parent.html`. Login and other authentication flows use
`authentication_parent.html`, `split_forms_parent.html`, and `success_fail_parent.html`.
The Phoenix theme supplies Bootstrap navigation, sidebar collapse, forms and modals.
The marketing/public shell uses `public_site/base.html`; public tracking renders a
separate template without workspace context processors.

Static sources are under `src/static`. `build.sh` runs Django `collectstatic`;
production uses WhiteNoise `CompressedManifestStaticFilesStorage`. There is no
application npm build to introduce or replace. Existing Motionmate PNG icons are
192 and 512 pixels; the Apple touch icon is 180 pixels. The previous favicon
manifest had standalone display but lacked an explicit start URL, scope and stable
identity. There was no service worker or shared connectivity indicator.

Authentication remains Django cookie/session authentication with the existing
active-business selection. CSRF middleware and form tokens remain active. Existing
workspace, role, vertical and subscription gates continue to run for every network
request. Public tracking already uses `never_cache`, limited public output and its
own fail-closed lookup throttling. Private response headers were inconsistent;
the new middleware adds `private, no-store, no-cache, must-revalidate` to private
responses, authentication paths, permission redirects, JSON and error responses.

Browser QA exposed two existing shared-script initialization errors: password
wrappers without toggle controls and SERVICE pages without a demo chart container.
Both now return early when their target elements are absent. Product layouts and
domain behavior are unchanged.

## Manifest and installation

`/site.webmanifest` and the legacy `/manifest.json` route return the same
`application/manifest+json` document. Name and short name are **Motionmate**;
identity/start URL are the existing dashboard, scope is the project root, display
is `standalone`, theme is white, and background is `#f5f7fa`. Django URL reversal
and static storage supply URLs, including production fingerprints. There are no
environment hostnames, tenant identifiers or tokens in these resources.

All five application shells share the manifest, Apple standalone/title/status-bar
metadata, connectivity CSS and worker registration. Existing Apple touch-icon
links remain. The public base links to the canonical manifest but does not
register a worker. Installation uses the browser's existing install controls;
there is no new banner or button. Installed launch requests the dashboard and
uses normal login when the Django session is absent or expired.

## Files changed

| Files | Change |
| --- | --- |
| `src/taskio/pwa.py` | Manifest/offline/worker views, explicit asset list and private-response middleware |
| `src/taskio/settings.py`, `src/taskio/urls.py` | Middleware and resource routes |
| `src/templates/includes/pwa_head.html` | Shared registration, manifest and Apple metadata |
| `src/templates/inheritance/dashboard_parent.html`, `src/templates/inheritance/account_parent.html` | Authenticated shell integration |
| `src/templates/inheritance/authentication_parent.html`, `src/templates/inheritance/split_forms_parent.html`, `src/templates/inheritance/success_fail_parent.html` | Authentication/form shell integration |
| `src/templates/public_site/base.html` | Canonical manifest link |
| `src/templates/pwa/service-worker.js`, `src/templates/pwa/offline.html` | Worker policy and anonymous offline document |
| `src/static/assets/css/pwa.css`, `src/static/assets/js/pwa.js` | Connectivity, offline styling, registration and history safety |
| `src/static/assets/js/phoenix.js`, `src/static/assets/js/dashboards/crm-dashboard.js` | Missing-element guards |
| `src/taskio/test_pwa.py`, `scripts/pwa_worker_test.cjs`, `scripts/pwa_browser_check.py` | Route/security, executable worker policy and browser checks |
| `docs/MOTIONMATE_PWA_FOUNDATION.md` | Audit, policy, verification and follow-up |

## Worker and cache policy

`/service-worker.js` is served by Django with a JavaScript MIME type, `no-store`
headers and `Service-Worker-Allowed: /`. Root scope is necessary because the
existing authentication, workspace, CRM, appointment, billing and Logistics routes
occupy separate root paths. Scope also follows Django's URL prefix if configured.

Cache Storage holds exactly seven public resources: the anonymous offline page,
PWA CSS/JS, Motionmate SVG mark, 192/512 PNG icons and Apple touch icon. Installation
fetches them without credentials and rejects errors, redirects and opaque
responses. Cache versions depend on worker source, offline HTML and asset content;
activation removes older **Motionmate PWA** caches and preserves other caches.
Only exact allowlisted GET URLs are read from this cache. Other static resources
retain the existing browser/WhiteNoise cache policy and never enter this worker's
cache.

All other same-origin requests use `fetch` with `cache: no-store`. Operational HTML,
Clients, Parcels, Shipments, invoices, settings, accounts, JSON/API responses,
exports, server errors and redirects never enter Cache Storage. Cross-origin
requests are untouched. HTTP error statuses remain unchanged. POST/PUT/PATCH/DELETE
failures and JSON/AJAX failures reject normally, with no queue, replay or synthetic
success response.

## Offline and history behavior

A failed GET navigation within the application routes returns a data-free offline
document with HTTP 503 and `no-store`. It offers Retry and Dashboard links. It
contains no user/workspace details, operational forms, CSRF tokens or authenticated
context. Public tracking, booking, marketing and admin navigations do not receive
this application fallback.

Already-open application pages show an accessible connectivity indicator on the
browser's offline event, marking live data as potentially outdated. Native and
AJAX form submit events are blocked while `navigator.onLine` is false. This signal
is a browser connectivity hint; server/API failures still follow the existing
error handling when a device reports online. A returning connection does not
replay or auto-submit anything.

Private pages hide on `pagehide`. A persisted browser history snapshot reloads
before showing its body, allowing Django to recheck the session and permissions.
After logout, online back navigation reaches login; offline back navigation can
only show the generic offline page. The worker never has private HTML to restore.
Existing logout route semantics, session cookies and authentication are unchanged.

## Environment and verification

Local, Development and Production run the same implementation. Worker registration
requires a secure browser context: localhost works for local QA; hosted environments
use HTTPS and the existing secure-cookie/proxy settings. Deployment must continue
to route the manifest, worker and offline URLs to Django and run `collectstatic`.
No second deployment, migration, model, billing rule or domain service is introduced.

Chromium checks use an isolated SQLite test database and disposable persistent
browser profiles. They inspect manifest/installability errors, actually install
the PWA, select standalone display, launch its app window, and uninstall it at the
end. Desktop, Pixel 7, iPhone 13 and iPad Mini viewport profiles each exercise both
SERVICE and LOGISTICS: dashboard/header layout, sidebar navigation, back navigation,
forms, Logistics Add Client modal, offline write rejection, fallback, reconnect,
login inside the installed window, logout and online/offline history safety.
Apple/Android profiles run **Chromium**, not Safari or physical Android Chrome.
Physical-device install prompts, iOS/iPadOS Add to Home Screen, OS relaunch and
production HTTPS/proxy behavior require device/deployment acceptance testing.

Run focused route/security/worker tests (Node executes the rendered worker):

```bash
LOGISTICS_LOCAL_BILLING_BYPASS=False DATABASE_URL= \
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
.venv/bin/python src/manage.py test taskio.test_pwa --noinput
```

Run optional browser checks with Playwright and an installed Chromium binary:

```bash
PWA_CHROMIUM=/path/to/chromium LOGISTICS_LOCAL_BILLING_BYPASS=False \
DEBUG=True DATABASE_URL= DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
PYTHONPATH=src:. .venv/bin/python src/manage.py test scripts.pwa_browser_check --noinput
```

Screenshots and JSON evidence default to `/tmp/motionmate-pwa-browser`; override
with `PWA_QA_OUTPUT`. `PWA_TEST_PROFILE` and `PWA_TEST_VERTICAL` can select a case.
Full regression coverage uses the existing six application suites plus
`taskio.test_pwa`. SQLite results do not establish PostgreSQL concurrency coverage
or live Stripe readiness.

Final validation on 2026-10-08: the full SQLite run completed **1,474 tests**, with
**1,443 passing and 31 skipped**. The ten PWA route/security tests include the Node
worker-policy harness. The browser runner exercises eight profile/vertical cases.
Production `collectstatic`, fingerprinted WhiteNoise resource responses, manifest,
worker and offline responses passed. Django checks, Ruff, Black, `git diff --check`
and migration drift checks passed; no migration was generated.
A final 43-test PWA/public-tracking run also passed after avoiding lazy user/session
resolution for public tracking cache headers. Authenticated tracking GETs retain
zero database queries and no workspace data.

## Recommended next block

Complete physical Android Chrome, iPhone/iPad Add to Home Screen and deployed HTTPS
acceptance. Exercise install, OS relaunch, expired sessions, dropped connections,
logout/back history and static updates. Then define a small update/install-help
experience based on those results.

References: [Service workers](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API/Using_Service_Workers),
[installation and Apple behavior](https://web.dev/learn/pwa/installation),
[Chromium PWA automation](https://chromedevtools.github.io/devtools-protocol/tot/PWA/).
