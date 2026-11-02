# Customer invoice and payment vocabulary

Implemented locally on 2 November 2026 for Services and Logistics. This concerns
customer invoices, not Motionmate subscription billing or Stripe configuration.
There are no new migrations, due dates, automatic collections, or financial writes
performed by the presentation layer.

## Shared presentation

`apps.billings.presentation.present_invoice` wraps the existing authoritative
`_invoice_settlement` projection. `Invoice.presentation` exposes it to scoped
HTML callers. Do not call it before applying the existing tenant and financial
read policy. All monetary calculations, cancellation allocation validation,
receipt history, credit approvals and movement decisions remain in their existing
services.

- Lifecycle: **Draft, Issued, Cancelled**. Stored `SENT` and historical `PAID` both
  present as Issued. Their stored values are retained.
- Payment: **Unpaid, Partially paid, Paid**, based on valid recorded payments and
  adjusted obligations. Paid requires positive net receipts and no remaining debt.
  An outstanding refund is a separate indicator and does not turn a satisfied
  retained obligation into a partial payment.
- **No payment required** identifies zero-value or fully credited obligations;
  these do not satisfy the receipt-backed Paid filter.
- Cancellation credits, adjusted amount, refund due, credit approval and review
  information remain separate. In a shared invoice, payments owed back on one
  allocation never offset debt on another.
- Historical manually-paid records without receipts show **Manually marked paid
  — unverified**. They are excluded from collectible totals and follow-up, shown
  in an explicit review section, and never receive invented receipts. An explicit
  authorized reconciliation form remains available without a prefilled amount.
- Email information says **Sent by email**, with submission time and recipient.
  Backend submission is recorded; delivery/open/bounce evidence is unavailable.
  Send/resend does not change lifecycle, receipts or balances.

The same projection serves invoice lists/details, client invoice cards, Logistics
workflow/registration/charge displays, admin, invoice emails, the HTML PDF template
and the ReportLab PDF renderer. Documents distinguish original total, cancellation
credits, adjusted amount, net payments received, balance due and refund due.
First-receipt currency is retained even after Services currency defaults change.
Logistics workflow summaries receive a bounded native-value dictionary, without
embedding Business models or private receipt details.

## Consumers and actions

Services and Logistics dashboard totals use `invoice_finance_totals` and separate
currencies and unverified balances. Drafts, cancellations and review cases are not
collectible. Monthly issued value uses creation dates because historical issue
timestamps do not exist; credits are reflected. It is not a cash-revenue metric.

Lifecycle and payment/accounting filters are separate. Existing lifecycle links
remain accepted, with `status=SENT` representing Issued. The Paid filter requires
payment evidence. Outstanding includes valid positive balances even when the same
invoice also has refund liability. Review cases appear explicitly and have their
own filter. Refund recorded means at least one completed refund entry, including
partial refunds.

Normal Mark as Paid UI is replaced by receipt recording. Old authorized POSTs
requesting `PAID` redirect to the existing receipt form without changing status.
The internal transition service is retained for historical compatibility. Admin
shows the derived vocabulary and does not expose direct lifecycle editing.

Logistics registration offers **Record payment received** and **Continue without
recording a payment**. Its saved navigation action is not a financial claim. Old
open forms using paid/unpaid remain accepted and normalize to the new actions.
Credit clearance cannot substitute for a receipt entry.

Invoice deletion endpoints and admin enforce Draft-only deletion. Existing
payment-history and Logistics-charge protections remain. Admin deletion rechecks
under the Business/Invoice lock order; bulk invoice deletion is unavailable.
Controlled business-data operations are not changed.

## Local validation results

All runs below used disposable PostgreSQL 14 on loopback, with no skipped tests.
Suites overlap and must not be summed as unique tests.

| Check | Result |
| --- | --- |
| Invoice/payment, dashboard, role/location, client and vertical regressions | 240 passed |
| Final presentation/workflow/client rerun after display refinements | 51 passed |
| Receipt, registration, credit/movement, financial access and coverage races | 26 passed |
| Cancellation confirmation/refund races, run separately | 3 passed |
| Historical payment migration preservation, run separately | 1 passed |
| Payment and registration Chromium checks at 390/1440 pixels | 4 passed |
| Final Services/Logistics screen and PDF refresh | 2 passed |

Django system checks, migration drift (`makemigrations --check --dry-run`),
changed-file Ruff, Black for changed files except pre-existing formatting in the
CRM test module, and `git diff --check` passed. Representative mobile/desktop,
admin, HTML PDF and rendered ReportLab PDF screenshots were visually inspected.

Logs are under `/tmp/invoice-terminology-implementation-04Qr45/`:
`regressions-verified.log`, `final-surface-regressions.log`,
`receipt-movement-races-final.log`, `cancellation-races-final.log`,
`history-test.log`, `browser-final.log`, and `surfaces-final.log`.
Untouched baseline revision `5c29b3a` reproduced the unrelated CRM import and
Logistics demo-port failures in `baseline-import-test.log` and
`baseline-demo-test.log`. Demo-seed failure paths are excluded from the focused
passing suite; their wider-run failures remain in `regressions-final.log`.

## Verification boundaries

Tests use disposable loopback PostgreSQL databases and the existing test settings
with test-only local billing authorization, in-memory email and cache, and MD5
password hashing. They do not migrate or mutate the ordinary application database.
The historical payment migration test runs separately from row-lock race suites;
rewinding its schema after other transaction tests have flushed seeded plans can
trip the existing Services allowance migration guard.

Browser checks in `scripts/invoice_terminology_browser_check.py` cover Services and
Logistics at 390 and 1440 pixels, including receipt entry, email submission,
review, currency separation, admin/client/dashboard screens, simultaneous debt and
refund liability, PDF downloads and HTML PDF rendering. Screenshots and PDFs are
written under `/tmp/invoice-terminology-browser/`.

The wider investigation also reproduced two unrelated failures in an untouched
HEAD checkout: the CRM service-import example test expects obsolete text, and
Logistics demo seeding rejects its loading/discharge port references. Those paths
are unchanged. An older optional settings/defaults browser smoke also times out
while locating a settings field; it is outside this change's payment browser suite.

Actual payment custody, external online verification, refunds and email delivery
remain operational concerns. Legacy Services invoices without receipts have no
saved payment currency to reconstruct; their existing workspace-default behavior
is retained. No due-date, overdue, provider or historical reconciliation rollout
is included.
