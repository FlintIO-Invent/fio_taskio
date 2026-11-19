# Accepted Services Invoices commit scope

One local commit is authorized by the user after Gate C acceptance. This later
authorization permits the selected files below to be staged and committed; the
earlier no-commit statements in the acceptance/finalization records remain the
history of those stages. No push, merge, deployment, database action, implementation
change or deletion is authorized by this packaging step.

Accepted candidate: `936f7fa66278a40e5d90122d365b6d097d245e7c1822c55b54993b1a51a91abc`.
Branch: `experiment/motionmate-ui-redesign`. Parent before packaging: `d864d322061dfa03f50076c5381ec26efd0e1ec7`.
Commit message: `feat(services): modernize invoices and billing interfaces`.

The selection contains 82 files: the exact 40 accepted files,
11 frozen UI Lab source/build/validation files, 30 final
approval/design/integration/validation records, and this packaging scope document.
All accepted candidate hashes and task-owned source hashes were verified. Existing
modified files also match the approved pre-change HEAD baselines.

## Runtime and reproducibility dependencies

- Both Manrope PDF TTFs and their exact OFL license are included. The existing
  tracked Manrope WOFF2 and its license already belong to the parent commit.
- Guarded fixture-generation Python code and the synthetic lab scenario module are
  reproducible source dependencies, not disposable database contents. They remain
  included because the approved preview/test and design sources import them.
- Existing tracked shared UI Lab components and pinned toolchain manifests are
  reused. Generated dist/, browser captures/PDFs, fixture data, logs and caches are
  not required application runtime assets.

## Evidence packaging

Final JSON approval, file-hash and validation summaries are retained as documentation.
Raw logs, generated output, large working-tree snapshots and machine-specific runtime
state are excluded. Historical reports/state retain their original local evidence
paths and frozen hashes. Those references are not new runtime dependencies; a fresh
checkout can rebuild the lab from source, but checking every original frozen evidence
hash requires the preserved local evidence/archive. No accepted state or design hash
was rewritten to hide excluded artifacts. Existing validation limitations remain.

## Explicit selected paths

- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/audit.md`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/brief.md`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/browser-evidence-index.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/commit-scope.md`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/comparison.md`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/design-identity.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/django-browser-summary.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/django-journey-summary.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/django-print-summary.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/django-test-summary.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/django-validation.md`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/final-print-source-delta.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/final-source-manifest.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/finalization-check.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/finalization.md`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/font-download-verification.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/font-sources.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/gate-a-approval.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/gate-b-approval.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/gate-c-acceptance.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/implementation-manifest.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/implementation-preservation.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/implementation-report.md`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/integration-proposal.md`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/logistics-test-parity.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/preservation-after.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/print-pdf-verification.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/prototype-review.md`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/state.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/static-checks.json`
- `docs/design/motionmate-ui-lab/workflows/services-invoices-20261118/validation.md`
- `docs/services_invoices_workspace.md`
- `scripts/services_invoices_browser_check.py`
- `scripts/ui_preview/invoices_checks.py`
- `scripts/ui_preview/invoices_fixtures.py`
- `scripts/ui_preview/invoices_preview.py`
- `scripts/ui_preview/test_invoices.py`
- `src/apps/billings/pdf.py`
- `src/apps/billings/services_invoice_pdf.py`
- `src/apps/billings/test_pdf_layout.py`
- `src/apps/billings/test_presentation.py`
- `src/apps/billings/test_services_invoice_documents.py`
- `src/apps/billings/test_services_invoices_ui.py`
- `src/apps/billings/tests.py`
- `src/static/assets/css/services-invoices.css`
- `src/static/assets/fonts/manrope/Manrope-PDF-OFL.txt`
- `src/static/assets/fonts/manrope/manrope-bold.ttf`
- `src/static/assets/fonts/manrope/manrope-regular.ttf`
- `src/static/assets/js/services-invoices.js`
- `src/templates/billings/invoice_create.html`
- `src/templates/billings/invoice_detail.html`
- `src/templates/billings/invoice_edit.html`
- `src/templates/billings/invoice_list.html`
- `src/templates/billings/invoice_pdf.html`
- `src/templates/billings/payment_form.html`
- `src/templates/billings/services/invoices/assets.html`
- `src/templates/billings/services/invoices/base.html`
- `src/templates/billings/services/invoices/detail.html`
- `src/templates/billings/services/invoices/document.html`
- `src/templates/billings/services/invoices/editor.html`
- `src/templates/billings/services/invoices/field.html`
- `src/templates/billings/services/invoices/line.html`
- `src/templates/billings/services/invoices/list.html`
- `src/templates/billings/services/invoices/manual_service_fields.html`
- `src/templates/billings/services/invoices/payment_form.html`
- `src/templates/billings/services/invoices/payments.html`
- `src/templates/billings/services/invoices/quick_client_modal.html`
- `src/templates/emails/invoice_body.html`
- `src/templates/emails/invoice_body.txt`
- `src/templates/emails/services/invoice_body.html`
- `src/templates/emails/services/invoice_body.txt`
- `ui-lab/services-invoices/.gitignore`
- `ui-lab/services-invoices/README.md`
- `ui-lab/services-invoices/build.mjs`
- `ui-lab/services-invoices/build_review.py`
- `ui-lab/services-invoices/src/app.js`
- `ui-lab/services-invoices/src/fixtures.js`
- `ui-lab/services-invoices/src/index.html`
- `ui-lab/services-invoices/src/input.css`
- `ui-lab/services-invoices/src/render.js`
- `ui-lab/services-invoices/supplement.py`
- `ui-lab/services-invoices/validate.py`

## Excluded and preserved locally

- Raw execution logs: 59 files, left unchanged and unstaged.
- Local runtime, baseline, duplicate or intermediate workflow artifacts: 20 files, left unchanged and unstaged.
- Generated build metadata: 1 files, left unchanged and unstaged.
- UI Lab generated dist/: 11 files, left unchanged and unstaged.
- UI Lab generated evidence/: 1219 files, left unchanged and unstaged.

All other application/workflow paths remain outside this commit.
Motionmate Logistics and the Dashboard, Appointments and Clients sources are preserved. No
new test or design-review cycle was performed for this source-preserving packaging.
Staged content, accepted hashes, file count, whitespace and accidental-secret checks
are the commit verification; no runtime or database command is part of this step.

## Accepted whitespace notices

Staged diff inspection reports two existing notices in accepted candidate
`936f7fa66278`: a trailing space on line 21 of the exact upstream
`Manrope-PDF-OFL.txt`, and a blank line at EOF in `quick_client_modal.html`.
Both are preserved byte-for-byte; this packaging step does not reformat the
accepted implementation or alter the upstream license. No other whitespace
findings were reported.
