# Services Invoices v1 validation — Gate A

This phase validates an isolated synthetic design and the unchanged source scope.
It does not run Django, use a database or modify real invoices. Read the
[source audit](audit.md) for the actual routes, roles, model/form/service contracts,
shared consumers, both PDF renderers and current email behavior.

## Actual checks

The installed Chromium 148 executable, Playwright, axe 4.11.1, pypdf and pypdfium2
were used without installation. The existing pinned Tailwind 4.3.5, DaisyUI 5.8.0,
esbuild 0.28.2 and Manrope 5.3.0 build only this task-owned package.

The validator permits only GETs on the loopback read-only static server. All
application/form/route/provider intents are intercepted or blocked. CSP disables
connections and form navigation. Every suite refuses an existing evidence output
folder and verifies that prototype source bytes stay unchanged during capture.

- `matrix-03`: 274 passing rendered cases, including all eight screens at
  1440×900, 768×1024, 390×844 and 320×844 in both themes, plus long/empty/loading/
  error/invalid/read-only/no-access/quota states, all five Services roles,
  draft/issued/paid/cancelled/review/refund/saved-currency variants and customer
  documents with zero tax, zero value, empty notes and many lines.
- `final-delta`: 24 passing edit/detail/document cases after a narrow-screen
  Qty-column adjustment and a consistent no-receipt fixture for editable Drafts.
  It checks reflow, targets, labels, theme, font, axe, clean customer amounts and
  notes, and the return to Draft detail without fictitious receipt history.
- `journeys-04`: eight passing width/theme journeys, 222 assertions. Existing
  filters, receipt-backed Paid, review queue, linked errors/focus, theme draft
  retention, inline client cancel/errors/success, saved service snapshot, add/
  remove line, manual-service category conflict, create/edit round trip, internal
  Draft versus customer copy, explicit issue/cancel/Escape focus, payment page,
  required reference, receipt status, protected cancellation, recorded refund,
  email submission and intercepted handoffs were exercised as simulations.
- `supplement-01`: 20 passing cases. Locked data hidden on all eight screens;
  appointment provenance and fixed client; saved line IDs and `new_` prefixes;
  saved EUR, disabled currency and retry key; legacy review without an invented
  amount; staff/accountant online-method choices; adjustment remaining-receipt
  default; delete cancel/confirm; six associated modal field errors and axe;
  12 RTL list/editor/document captures. English customer documents retain LTR.
- `pdf-05`: 20 passing references. Letter dimensions, no Draft label, Subtotal,
  applicable Tax, one Total Amount, correct Notes/empty Notes, no routine payment
  summaries, meaningful cancelled/review notices, per-page invoice reference and
  page numbering, all 48 multipage items, repeated table headings, correct supplied
  total and identical extracted light/dark document text. Every page is rasterized
  and retained for review. Representative first/last pages were visually inspected.

Completed checks have no page/console errors, blocked application requests, axe
violations, horizontal page overflow, unlabeled controls or measured visible
targets smaller than 44px. Raw axe incompletes are retained; automated axe is not
complete WCAG conformance. The design was visually reviewed at desktop and mobile,
in both themes, including long forms and document pages.

## Retained first attempts and corrections

- `matrix-01` retained six role-adjustment assertion failures caused by supplied
  role fixtures lacking a receipt. Role scenarios now share a meaningful receipt
  fixture; production authorization was not changed. All 270 cases had zero axe
  violations; the six failed semantic assertions were not counted as passes.
- `journeys-01` exposed the prototype's intrinsic `new_service_category_name`
  being confused with the edit form's `new_` prefix. This was fixed in the lab.
  Original results and failure screenshots remain.
- `pdf-01` exposed an overbroad repeated-heading assertion expecting a line-table
  header on a closing Notes-only page. The check now covers actual table pages;
  closing totals/Notes were grouped for professional output. Original PDFs remain.
- The old read-only static listener exited during `matrix-02` / `journeys-03`,
  leaving connection-refused results. Its port was independently found free and
  the same read-only server was restarted at 8766. No other listener or runtime
  was stopped. The complete interrupted suites were rerun successfully; their
  failed raw evidence was not overwritten.
- `journeys-02`, `pdf-02/03/04` and earlier successful partial cases remain as
  historical attempts. The evidence index identifies the final suites; do not
  sum overlapping runs as independent coverage.

## Preservation and limits

The protected intake fingerprint covers 12,679 existing source, documentation,
assets and approved/reference files. Final hashes match, as recorded in preservation-after.json. No
shared registry/token/component, previous lab package, production template/asset,
model, migration, service, form or route is edited. No database connection was
opened. Accepted Clients and Logistics bytes remain unchanged.

The gallery and PDFs are design references. Actual Django rendering, real
POST/CSRF/idempotency enforcement, concurrent financial services, actual
ReportLab/HTML parity, logo uploads, ordinary runtime, providers/email delivery,
Safari/Firefox, assistive technology and native browser zoom were not validated.
The existing emailed-PDF Notes exclusion remains a later explicit integration
scope decision. No live-provider or production-readiness claim follows.

Scoped Ruff, JavaScript syntax, whitespace, deterministic build, gallery links and prior Clients acceptance checks passed; see static-checks.json, gallery-check.json and preservation-after.json.
All source/evidence and the read-only preview remain available for Gate A review.
