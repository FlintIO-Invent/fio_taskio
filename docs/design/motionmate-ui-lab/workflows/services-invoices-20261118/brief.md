# Services Invoices design brief — v1

The complete Services customer-invoice journey should feel calm and coherent:
find an invoice, prepare its items, review it, issue it under existing safeguards,
record receipts and adjustments, and share a professional customer document.
The source audit and contracts are in [audit.md](audit.md).

## Proposed connected design

- **Directory:** two existing invoice/payment-accounting filters, clear invoice
  identity/client, lifecycle separate from receipt status, original total and
  balance, email-submission metadata and entitled actions. All existing rows
  remain visible; no invented server search, export or pagination.
- **Create/edit:** client panel with inline client creation, repeated saved or
  manual line items and existing save-to-Services/category choices. Notes remain
  editable. A quiet summary sits beside the editor on desktop and follows it on
  mobile. Creation remains a Draft; review/issuance stays on detail.
- **Detail:** internal lifecycle/payment badges, clear invoice information and
  line items, one receipt/accounting section with saved currency, audit history
  and adjustment links. Existing Record customer payment opens its existing full
  page and stays above Download PDF. Issue, email, cancel and delete have distinct
  existing confirmations and independently guarded access.
- **Receipt and adjustment pages:** preserve amounts, required references,
  verification, audit reason, action choices, retry protection and return links.
  Explain clearly that recording does not move money. No new payment gateway.
- **Customer PDF:** clean white Letter paper in either workspace theme. Issuer
  identity, supported business logo/fallback, invoice number and existing date,
  Bill to, full line items, Subtotal, applicable Tax, one emphasized Total Amount,
  Notes and quiet Motionmate attribution. No internal Draft badge or routine
  balance/payment summary. Keep meaningful cancelled/review/refund exception
  notices; long items and notes paginate without losing totals.
- **Customer email:** simple business identity, invoice reference/date, total and
  attachment, without internal Draft or repeated receipt/balance summaries.
  Email metadata remains internal and submission is not delivery or issuance.

## System and accessibility

Use the approved shared Manrope, unchanged Motionmate mark, semantic indigo/navy
colors, restrained surfaces and 44px controls. Tailwind 4/DaisyUI 5 are isolated
prototype tools. Phoenix 1.23.0 remains the production foundation. Do not change
shared navigation, tokens or any previous approved package.

Verify 1440×900, 768×1024, 390×844 and 320×844; existing light/dark modes;
readable long content; empty/loading/error/read-only/no-access/quota states;
owner/admin/staff/accountant/viewer; validation, keyboard and focus, modal return,
reduced motion, RTL and print pagination. White customer documents intentionally
retain a paper palette in both workspace themes.

## Decisions and deferred integration

The design preserves all calculations, stored statuses, tenant/role/module/
subscription/quota checks, saved currency, receipt evidence, refund/credit rules,
issuance locks, protected history, routes, forms, CSRF/retry keys and redirects.
No schema, provider, billing-plan, due-date, reminder or collection feature is
added. Customer invoices and Motionmate platform subscriptions stay distinct.

Downloaded-PDF Notes are already supported. Emailed attachment Notes currently
use an exclusion flag and may include generated appointment provenance if
enabled. Notes inclusion for email is a concrete later presentation decision,
not an automatic side effect of design approval. Actual customer PDFs continue
to use the existing renderer until separate implementation authorization.

All mutations and results in this lab are explicitly simulated, reset on reload
and use only synthetic data. PDF references generated from browser print are
design artifacts, not actual Django/ReportLab output. No application/database
requests, email, provider calls, migrations or release operations are authorized
by this phase. Stop at Gate A for v1 visual/interaction approval.
