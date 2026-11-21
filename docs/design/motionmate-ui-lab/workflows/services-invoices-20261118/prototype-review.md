# Services Invoices v1 — Gate A review

Design ready for approval, 19 November 2026. Intake and fixed synthetic invoice
date: 18 November 2026. No application integration has been performed.

- [Interactive prototype](http://127.0.0.1:8766/services-invoices/dist/)
- [Screen gallery, PDF references and results](http://127.0.0.1:8766/services-invoices/evidence/v1/gallery.html)
- [Customer invoice design PDF](http://127.0.0.1:8766/services-invoices/evidence/pdf-05/invoice-populated-light.pdf)
- [Draft customer-copy design PDF](http://127.0.0.1:8766/services-invoices/evidence/pdf-05/invoice-draft-light.pdf)
- [Multipage design PDF](http://127.0.0.1:8766/services-invoices/evidence/pdf-05/invoice-many-lines-light.pdf)

## Connected review

Review Invoices → Create invoice → inline client creation → saved/manual items
and optional service/category → save Draft → edit → detail → explicit issue →
existing payment page → receipt → adjustment/refund → email confirmation →
customer document. All actions are clearly identified as local simulations.
The separate customer email screen is available through the review controls.

Internal Draft/Issued/Cancelled and receipt/accounting indicators remain distinct.
Customer documents omit Draft labels and routine payment/balance summaries.
Subtotal, applicable Tax, Total Amount and Notes remain, with meaningful cancelled,
review and refund exception notices. Empty Notes and zero Tax have no empty rows.

PDF design references use white Letter paper, local embedded Manrope, repeated
line headings on pages containing line items, a single total block and retained
Notes, invoice reference and page numbers. The 48-item example spans six pages.
These are Chromium design references, not actual Django/ReportLab previews.

## Validation evidence

| Check | Result |
| --- | --- |
| Full screen/state matrix | 274 passed; 1440/768/390/320px, light/dark |
| Final affected-screen refinement | 24 passed: edit, detail, customer document at all four widths/themes |
| Connected journeys | Eight passed, 222 assertions |
| Roles, field contracts, modal errors and RTL | 20 cases passed, including 160 workflow assertions and 12 RTL cases |
| Generated PDF references | 20 passed across ten scenarios, both themes |
| Axe | Zero violations in completed matrix, delta, modal and RTL checks; raw incompletes retained |
| Scope and preservation | All 12,679 protected files unchanged; previous approved packages and registry retained |

Suites overlap and are not a count of unique tests. The final narrow Qty-heading
and consistent empty Draft receipt fixture received targeted edit/detail/document
checks; other full-matrix screens were unchanged. The final PDF set was regenerated
from the final assets. See [validation](validation.md) and
[evidence index](browser-evidence-index.json) for raw results and source identities.

## Approval and outstanding integration decisions

Approve **Services Invoices design v1** for visual layout and simulated
interactions only. The artifact map and aggregate SHA-256 in the workflow check
identify the exact version. Gate A approval does not authorize production changes.

The existing email-PDF `include_notes=False` rule differs from downloaded PDFs,
and stored Notes can contain generated appointment provenance. The design shows
customer-friendly supplied Notes. The later integration proposal must explicitly
scope the email inclusion behavior without deleting or silently exposing stored
content. Existing finance exceptions and internal lifecycle protections remain.

Real current-source Django BEFORE/AFTER, authoritative form/permission/financial
regressions, actual ReportLab/HTML/email parity and Logistics runtime regressions
require the later integration audit and Gate B implementation/resource approval.
No ordinary database, provider, installation, staging, commit, push or deployment
was used. Stop here for Gate A approval.
