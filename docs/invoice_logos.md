# Company logos on invoice PDFs

Owners and admins with workspace modification access can upload, replace or remove
the company logo under **Business Settings → Invoice defaults**. The saved preview
appears after saving the business settings. Other settings saves retain the logo.

The current logo is embedded in newly generated invoice downloads, emailed PDF
attachments and the HTML invoice representation for both Services and Logistics.
Regenerating an older invoice uses the current logo. Previously downloaded or sent
files are unchanged. Removing the logo restores the text-only header.

## Storage and validation

`businesses.BusinessInvoiceLogo` stores one PNG image per Business in the database,
separately from the Business row. No public media URL, local persistent filesystem,
external image request or cloud storage account is used. The logo is included in
the existing tenant inventory and controlled permanent-purge deletion order;
all existing purge gates remain in force.

Uploads must decode as a still PNG or JPEG and be at most 2 MiB, 4096 pixels per
side and 16 megapixels. Pillow applies orientation, preserves transparency and
proportions, strips metadata, and resizes to at most 1000 × 500 pixels. Normalized
PNG data must fit within 512 KiB. Invalid uploads or unrelated form errors preserve
the previous logo and business settings. Replacement and removal cannot be selected
together. Business settings and logo changes commit atomically.

The PDF logo fits within 144 × 54 points above the company details on the first
page. Header text wraps within separate company and invoice-information columns.
A missing or unreadable image falls back to the company text header; image decoding
errors log only the Business ID.

## Dependencies and rollout

Django handles invoices, settings and multipart uploads. ReportLab generates PDF
bytes; the HTML template is a separate representation. Pillow is now a direct
runtime dependency (`>=12.2,<13`); the existing ReportLab version is unchanged.
`pypdf` and `pypdfium2` remain development-only PDF inspection/rendering tools.

Apply `businesses.0038_business_invoice_logo` before running this code against an
application database. It creates an empty logo table and does not backfill or alter
existing businesses, clients or invoices. Database backups include the stored logos.

## Verification

- Unit/integration checks: `apps.businesses.test_invoice_logos` and
  `apps.billings.test_invoice_logos`.
- Browser check: `scripts.invoice_logo_browser_check`, using disposable PostgreSQL,
  covers upload, preview, invalid images, replacement, removal, keyboard focus and
  390/1440 pixel light/dark settings layouts in both products. PDF, multipage PDF
  and HTML evidence is written under `/tmp/invoice-logo-browser/`.
- Existing settings, billing, invoice-presentation and tenant-data checks retain
  their behavior. Thirteen older inventory/purge test cases fail while preparing
  unsubscribed capacity-limited fixtures; the same failures were reproduced on an
  untouched HEAD checkout. New logo inventory/purge and financial-confirmation-gate
  checks use valid fixtures and run against disposable databases only.

No application database migration, provider call or deployment is performed by
these checks.
