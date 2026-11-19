# Services Invoices source audit — 18 November 2026

Scope: Full Redesign, Services customer invoicing only. Actual entry route:
`/billings/`. This phase reads the real Django implementation and produces an
isolated interactive design reference. It changes no production code, database,
provider or Logistics behavior. Motionmate subscription billing is a distinct
platform workflow and is outside this customer-invoice redesign.

## Current source and preservation

Intake branch: `experiment/motionmate-ui-redesign`; HEAD:
`d864d322061dfa03f50076c5381ec26efd0e1ec7`. Intake Git status was clean.
The accepted Clients work is already present and protected. The current source,
rather than historical recollection or a prior runtime copy, is the audit basis.
[Preservation baseline](preservation-before.json) fingerprints 12,679 existing
tracked and reference files. Ordinary `.env` files were not read.

The old Clients design approval hashes the shared preview registry. Therefore
this task leaves `ui-lab/previews.json`, shared components, approved tokens and
all earlier lab packages unchanged. A task-owned builder uses the same installed,
pinned Tailwind/DaisyUI/esbuild/Manrope tools and serves this new package directly.
No installation or framework migration is proposed by this design.

## Actual workflow trace

| Surface | Current source and contract |
| --- | --- |
| Invoice directory | `src/apps/billings/views.py::invoice_list`; `billings/invoice_list.html`. Business-scoped querysets, GET `lifecycle` and `status`, compatibility `status=DRAFT/SENT/CANCELLED`, receipt-backed Paid, separate refund/review filters. Existing all-row directory has no server search or pagination. All five Services roles can read; membership, module and subscription still apply. |
| Create / client / appointment entry | `invoice_create`, `invoice_create_from_client`, `invoice_create_from_appointment`, `_invoice_create_response`. Monthly quota, Business-scoped clients/services/categories, fixed client where supplied, appointment reuse, default notes, number generation, actual redirects and atomic save. No automatic issuance. |
| Create/edit lines | `_build_line_rows_from_post`, `_clean_line_rows`, Invoice/InvoiceLine models and `services.py`. Repeated `service_id`, `description`, `quantity`, `unit_price`, `save_as_service`, category/new-category names; saved `line_id` and `new_` prefixes on editing. Service snapshots and historical basis remain authoritative. Saving a manual line to Services/category is an existing opt-in side effect. |
| Inline client | `/billings/clients/quick-create/`, `invoice_quick_create_client`; `QuickClientForm`. Six required unprefixed fields, separate invoice modal/JSON shape, quota and tenant binding. Existing appointment/request quick-create endpoint is different. Preserve the invoice draft. |
| Edit / delete | Draft-only; payment history and Logistics charge bindings protect the monetary basis. Edit redirects to detail when ineligible. Delete is POST-only, under existing locks and permissions. No record cleanup or merge behavior is added. |
| Detail and lifecycle | Existing tenant resolver, `scope_invoices`, `invoice_ui_permissions`, `payment_context`. Internal stored DRAFT/SENT/PAID/CANCELLED retained. SENT/historical PAID display as Issued; payment labels remain separate. Issue/cancel are existing POSTs with CSRF, lock order and transition validation. Email/download do not issue or settle an invoice. |
| Payments | `payment_views.py`, `payment_forms.py`, `payment_services.py`. Existing `/payments/record/` page and return path. Amount, disabled saved currency, method, required receipt reference, online verification reference and hidden idempotency key retained. Services staff cannot choose externally verified online; accounting roles retain that option. |
| Adjustments | Existing `/payments/<id>/adjust/`; accounting role guard distinct from general Services invoice management. Reversal, completed refund and correction; reason/audit reference, original receipt link and retry key retained. Recording does not collect or send money. Logistics allocation/credit-specific forms are untouched. |
| Accounting presentation | `present_invoice` and `_invoice_settlement`, after authorization. Original total, net receipts, credits, adjusted obligation, balance, refund due and legacy review are distinct. Saved currency is retained. Do not equate Issued/SENT with paid or net refund liability against another debt. |
| Customer document | Download route → `pdf.py::render_invoice_pdf` → ReportLab canvas. `render_invoice_pdf_html` separately renders `billings/invoice_pdf.html`. Both need scoped changes in a later implementation; editing only HTML would not change actual downloads. Filename, Letter format, issuer/client identity, business logo, creation-date semantics and Notes flag are existing contracts. |
| Email | `invoice_email_send` generates the PDF with `include_notes=False`; `notifications/emails.py` and HTML/plain-text templates deliver it. Email metadata records backend submission; delivery is unconfirmed. There is no Services Draft issuance check in the email path; the redesign must not claim or invent one. |

## Findings from current source

1. Services PDFs **already** show Subtotal, applicable Tax and Total Amount and
   omit routine payment-summary rows. This current behavior is preserved. Both
   PDF renderers still print `Invoice status: Draft` for a saved Draft invoice.
2. Customer email HTML and plain text still use the shared internal status and
   amount-row summary, including Draft, net receipts, balance and refund rows.
   They need a Services-specific customer composition in a later proposal.
3. Internal detail repeats financial context across invoice and payment blocks.
   The design gives receipt/adjustment data one clear internal home and keeps
   authoritative figures and warnings available.
4. Create/edit are long inline compositions with saved-service/manual-service
   choices, category side effects and a separate quick-client flow. A calmer
   two-column editor can retain all controls; mobile needs explicit stacking.
5. Downloaded PDFs include Notes, while emailed PDF attachments omit them. Notes
   may contain appointment/request provenance generated by existing code. The
   design shows supplied customer-friendly notes, and the integration proposal
   must explicitly resolve email-note inclusion without deleting, filtering or
   silently exposing stored notes. No send/download behavior changes at Gate A.
6. Normal customer copies can be concise while retaining meaningful exception
   notices for cancellations, accounting review and outstanding refund liability.
   Removing redundant summaries is not authorization to hide financial warnings.

## Shared consumers and Logistics boundary

`presentation.py`, ReportLab/HTML PDFs, invoice views, payment templates, email
templates, shared invoice includes and financial access helpers serve both
verticals. Client cards, dashboards, admin and Logistics operational flows consume
the same financial projection. A global edit to the projection, labels, totals or
PDF rendering would exceed the requested Services scope. Later implementation
must branch on the authoritative Business vertical and retain existing Logistics
output, guards, location scope, receipt allocation and financial clearance.

No actual Django runtime/database/browser write was run for this design audit.
Old Clients review sessions are retained unchanged and are not represented as a
fresh current-source invoice BEFORE. Real working-tree BEFORE/AFTER, isolated
backend checks and actual ReportLab/HTML PDF parity require the later Gate B
implementation/resource authorization. Source findings here are not browser
observations or evidence of live provider behavior.
