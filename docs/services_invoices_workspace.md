# Services invoices workspace

The approved Services invoice design is implemented with Phoenix 1.23.0, existing
Django views/forms/routes, and Services-only includes/assets. Tailwind and DaisyUI
remain isolated design references. Shared billing templates dispatch on the resolved
Services Business; their original non-Services bodies remain unchanged.

The directory preserves lifecycle and payment/accounting filters, review-only
records, all existing records and guarded actions. Details keep internal lifecycle,
recorded payments, receipt adjustments, refund/review explanations, saved currency,
email submission metadata and source/client navigation. Record customer payment
remains the existing full-width page link above Download PDF.

Create/edit retain repeated line field names, saved line IDs, `new_` prefixes,
source appointment/client context, whole-unit validation, service snapshots,
category fields, CSRF and server validation. Inline quick-client creation uses the
existing endpoint and six required fields without discarding the invoice draft.
Payment pages render the actual form, including dynamic allocation fields and
hidden idempotency keys; they do not calculate settlement or collect money.

Services customer PDF, HTML and email summaries display saved Subtotal, applicable
Tax and Total Amount. They omit internal Draft/lifecycle labels and routine
payment/balance summaries. Required cancellation, unverified-history, currency and
refund explanations remain authoritative. Downloaded Notes follow `include_notes`;
notification code is unchanged and emailed attachments still exclude Notes.
Issuance, cancellation, deletion, payment/refund and subscription/role safeguards
remain in the unchanged server services and views.

ReportLab customer PDFs use Letter pages, embedded Manrope regular/bold, wrapping,
repeated line headings, invoice identity/page numbering and a single amount closing.
Existing tenant checks, Logistics access checks and supported normalized invoice
logo loader remain in the shared entrypoint. The existing Logistics renderer is
unchanged. Font files and OFL license were pinned to googlefonts/manrope commit
`6f81ebecdf65e4463b798cc07b16a4f8d5216917`; recorded hashes/provenance are in the
workflow's `font-sources.json` and `font-download-verification.json`.

Validation evidence and review resource identities are recorded in
[the workflow](design/motionmate-ui-lab/workflows/services-invoices-20261118/implementation-report.md).
Tests write only to an independently verified disposable PostgreSQL test database.
Human Django preview financial POSTs remain blocked by the unchanged review guard.
Ordinary local, Test Lab, staging and production databases/providers are outside
this review. No migration source, dependency, shared shell, Logistics source,
commit, push or deployment is included. Gate C acceptance is separate from release.
