# Services Invoices v1 — Gate B implementation proposal

Gate A approval is recorded for design
`08215da40bb17baeaa63d5a3482f02a45daf83e26ffecca0f6a78ec13ab77f80`.
This proposal translates that design into the existing Phoenix/Django application.
It contains **40 exact files: 12 modifications and 28 additions**. Implementation,
font-asset downloads and disposable Django/database setup are pending Gate B.

The original [audit](audit.md), [brief](brief.md), [prototype review](prototype-review.md),
validation and all 1,257 approved design artifacts remain frozen. The approval is
recorded separately in [gate-a-approval.json](gate-a-approval.json). The exact
manifest, baseline hashes and shared assessments are in
[implementation-manifest.json](implementation-manifest.json).

## Resulting behavior

Services gets the approved responsive directory, create/edit editor, detail,
payment history, existing receipt/adjustment pages and clean customer documents.
Phoenix 1.23.0, Bootstrap, existing Choices client search and local Manrope remain
the application foundation. Tailwind/DaisyUI stay in the isolated lab.

Internal Draft/Issued/Cancelled labels, stored enum values and independent
receipt/accounting indicators remain. Customer-facing Services PDF/HTML/email
output omits internal Draft/status labels and ordinary settlement summaries.
PDFs show saved Subtotal, applicable Tax, one saved Total Amount and Notes when
the existing inclusion flag permits. Mandatory cancelled/review/refund notices
remain; uncertain balances are never relabeled as verified or paid.

The email Notes decision is concrete: **retain `include_notes=False` for emailed
PDF attachments, and keep invoice Notes out of email bodies**. Downloaded PDFs
continue to include saved Notes when present. Existing Notes may contain generated
appointment/request provenance; this proposal does not widen their disclosure,
filter saved text or introduce a replacement field. A different email-sharing
rule would require explicit additional scope.

No models, migrations, calculation/payment/refund services, accounting projection,
tenant/role/module/subscription/quota/location policy, views, URLs or send logic
will change. No due dates, reminders, auto-issuance, collection, exports, server
search, new pagination or platform subscription-billing features are added.

## Integration findings and compatibility

| Area | Implementation constraint |
| --- | --- |
| Shared workspace templates | Dispatch Services content/assets using the current resolved Business; retain the original non-Services content and scripts. Do not edit the shared dashboard parent, theme, vendor bundles or collected assets. |
| Client/appointment/request entry | Keep existing named routes, locked client, source appointment and duplicate-invoice behavior. CRM request invoicing currently redirects to the existing client-based creation path; do not restore an older direct Lead-to-Invoice architecture. |
| Client search and quick creation | Preserve current Choices search and native fallback. Invoice quick-create is its own endpoint with six unprefixed fields and a nested `client` JSON response. Keep its draft, modal ID, CSRF, errors and submit lock; do not reuse the other prefixed quick-client endpoint. |
| Line items and categories | Preserve saved `line_id`, repeated field names, `new_` prefixes, template disable/enable state, service metadata, snapshot selection, whole-unit attributes and existing live estimate behavior. Preserve the opt-in service/category creation side effects; all saved calculation/validation remains server-authoritative. |
| Financial history and actions | Retain all independent server-provided permissions. Services staff can manage generic invoices and record ordinary receipts but cannot perform accounting adjustments or choose externally verified online. Do not infer those permissions from one broad UI role flag. |
| Payment forms | Render the complete actual server form, including hidden retry key, disabled currency, field/non-field errors and any dynamic allocation/credit fields. Preserve reference, verification and audit requirements, retry behavior and return links. |
| Status and issuance | Retain locked transition services, persisted status and saved financial basis. Download/email does not issue or settle an invoice. Current Services email/download paths do not have a Draft issuance restriction; presentation work must not invent one. |
| Internal accounting display | Reuse `present_invoice`, `amount_rows`, receipt entries and existing authoritative financial summary. Preserve review, credits, adjusted obligations, saved currency, refund liability and audit references. Do not calculate settlement in JavaScript. |
| Actual PDFs | Downloads/emails use ReportLab, independently of the HTML PDF template. Add a Services-only drawing implementation reached through the unchanged authorized entrypoint/context. Keep the original Logistics drawing helpers and access/monitoring checks. |
| Saved amounts and dates | Render the saved invoice/line values and existing tax/currency/date properties. Do not recompute a stored total from displayed subtotal/tax, rename creation time to a new issuance date, convert currency or reinterpret legacy paid records. |
| Customer email | Services-specific body fragments inside the existing email base. Preserve subject, attachment naming/content type, recipients, reply-to, submission metadata and unconfirmed-delivery semantics. Logistics retains its original body. |
| Logos and PDF typography | Reuse existing BusinessInvoiceLogo loading, aspect fitting, transparency and text fallback. Embed scoped Manrope faces in Services PDFs; no font family override on Logistics or global theme change. |

## Shared consumers and preservation

| Shared file/group | Services effect | Other-consumer check |
| --- | --- | --- |
| Invoice list/detail/create/edit/payment wrappers | Approved scoped compositions/assets | Original Logistics branches, role/module/subscription/location states, valid/invalid GET/POST, protected charge/receipt history and absence of new assets |
| ReportLab entrypoint and HTML PDF wrapper | Services-specific professional document | Deterministic Logistics BEFORE/AFTER PDF byte equality, HTML/text/layout comparison, logos, review/credit/refund information and direct access denials |
| HTML/plain-text invoice email wrappers | Clean Services customer body | Original Logistics body/attachment and location authorization, failure behavior and delivery metadata |
| Existing three billing test modules | Narrow Services customer-label/typeface and external-Choices-marker assertions | Retain every financial/tenant/role/state assertion and all Logistics expectations; add real search/browser and document facts tests |
| New invoice preview entrypoint | Fresh invoice-specific setup using existing core guards | No changes to existing fixtures, runtime, settings, network/financial guard or Clients/Appointments adapters |

The authoritative financial projection also serves client cards, dashboards,
admin and Logistics workflows. Those sources remain unchanged and receive
regressions. The accepted Clients work, its source files, fixture adapters,
registry, assets and evidence remain untouched. The new invoice entrypoint
composes default fresh setup with its own verified fixture adapter; it does not
extend `scripts/ui_preview/fixtures.py` or change prior session behavior.

Original non-Services template bodies will be compared after removing only the
dispatch wrapper. Financial/policy/model/migration sources outside the manifest
must remain byte-identical. No existing data is copied, reset or reseeded.

## Font assets and external reads

The local approved Manrope WOFF2 is suitable for the workspace/HTML, while the
current ReportLab renderer uses Helvetica. The audited upstream has static
[regular and bold TTF assets at a fixed commit](https://github.com/googlefonts/manrope/tree/6f81ebecdf65e4463b798cc07b16a4f8d5216917/fonts/ttf).
After approval, download only those two fonts and their exact upstream OFL,
verify recorded Git blob hashes and byte sizes, and add the three listed assets.
The existing WOFF2 and its license remain unchanged. No converter, package
installation or production dependency/lockfile change is needed.

The proposed immutable asset sources and sizes are in
[font-sources.json](font-sources.json). This audit read public source metadata;
no font binaries were downloaded or added to application assets yet.

## Proposed disposable resources

Use a **new** owned `/tmp/motionmate-preview-session-*` and source snapshot,
independent from the retained Clients review and ordinary application. Proposed
ports are currently free; preflight must recheck them and refuse occupied ports.

| Resource | Target |
| --- | --- |
| Real BEFORE Django | `127.0.0.1:8870` |
| Real AFTER Django | `127.0.0.1:8871` |
| Local account/review launcher | `127.0.0.1:8872` |
| BEFORE private PostgreSQL | `127.0.0.1:55620` |
| AFTER private PostgreSQL | `127.0.0.1:55621` |
| Isolated browser-test LiveServer | `127.0.0.1:8768` |
| Runtime settings | `ui_preview.settings` |
| Regression settings / database | `taskio.services_test_settings` / runner-owned `test_services_rollout` on the new AFTER cluster |

Authorization would cover creating those empty owned clusters, applying only
existing migrations, synthetic fixture setup and whitelisted test writes. Verify
ownership/markers, PID/process, canonical data directory, system identifier and
live database identity before first writes and each later operation. Keep network,
provider, email and financial guards; do not load ordinary `.env`, copy customer
records, or connect to ordinary/staging/production/Test Lab databases.

**The human BEFORE/AFTER pair keeps existing financial-write blocks.** Reads,
native navigation, editor interaction, validation presentation and PDF downloads
are real Django behavior. Invoice/payment/email POSTs there remain explicitly
unavailable. Complete real create/edit/issue/receipt/refund/email POST validation
runs only against the separately guarded test LiveServer and disposable test DB.
Its email backend is in-memory; no money movement or external email occurs.

Setup may create synthetic active Logistics plan/membership/site fixtures solely
in the empty owned review/test databases, to exercise actual allowed/denied
Logistics cases. This does not activate provider products or any ordinary plan.
Both sides must start with equivalent canonical financial facts and records.
Generated retry UUIDs/setup timestamps are identified where normalization is
needed; supplied values and ledger facts are not normalized away.

Serialize test database runs and runtime identity preflights: the existing guard
refuses an unexpected test database in a live preview cluster. Drop only the
runner-owned test DB at ordinary test teardown. If a completed runner strands it,
recovery requires exact cluster/catalog proof and zero active sessions; never
terminate connections, remove review records, reset or clean existing sessions.

The existing launcher uses a debug-allocator workaround, and the prior Clients
review recorded a Python GC teardown crash. Keep those facts visible if they
recur; a passing isolated run does not establish ordinary-runtime stability.

## Sequence after explicit Gate B approval

1. Recheck design/manifest/branch/HEAD and baseline target hashes. Preserve all
   unrelated work. Create the new isolated adapter files and capture actual
   working-tree runtime bytes before changing application templates/assets.
2. Create independent fresh BEFORE/AFTER sources/clusters. Run setup-only
   synthetic fixtures with authoritative services, prove initial canonical
   parity and start the read-only real review pair. Preserve source identities
   and immutable BEFORE evidence, including existing defects.
3. Implement only the exact manifest, download/verify the three pinned font
   assets, retain Phoenix and all non-Services paths, then refresh AFTER alone.
4. Run new and existing focused backend/POST/browser/PDF checks in the guarded
   test environment; capture read-only real BEFORE/AFTER separately. Save raw
   first failures and scoped reruns. Never silently resynchronize records.
5. Compare source, original fixture records, financial facts, both verticals and
   actual document output. Produce implementation/validation/comparison reports
   and stop at Gate C for acceptance of the exact resulting candidate.

## Validation required

- Actual forms: searchable client selector/native fallback, unprefixed inline
  client 400/201/capacity/network outcomes, retained draft, fixed client and
  appointment/request entry, service snapshots, category conflict, saved IDs,
  `new_` fields, whole units, Notes, native POST and return destinations.
- Finance: existing rounding/calculation, saved currency, receipt-backed Paid,
  zero/fully credited/review/legacy states, refunds separate from debt, ledger
  append-only history, correction/reversal/refund, CSRF/retry/reference/tenant
  rejection, quota, persisted role/subscription changes and issuance protection.
- Actual documents: ReportLab plus HTML/plain-text/HTML email, PDF downloads and
  locally captured email attachment, no Draft customer labels, stored amount
  facts, tax omission, Notes flag, exception messages, fonts/logos, long/unbroken
  content, many pages, per-page references/headings, clipping and final totals.
- Both verticals: owner/admin/staff/accountant/viewer, active/grace/restricted/
  missing-module states, Logistics site grants/denials, original document/output
  and asset isolation, related client/dashboard/admin accounting presentation.
- Browser: 1440/768/390/320, light/dark, keyboard/focus/error links/dialog return,
  long/empty/restricted/error states, RTL/reflow/44px targets, raw full-page and
  scoped axe results. Preserve inherited shell findings and unsupported checks.
- Scope: 40-file diff only, protected source/design hashes, unchanged migrations,
  authoritative services and records; actual AFTER source equals candidate.

Whitelisted regressions include billing scoping/create/edit/quick-client tests,
presentation/payment/filter/PDF/logo suites, payment concurrency, Logistics
financial access/coverage/cancellation cases and accepted Clients/Bookings UI
regressions. Existing unrelated failures, if reproduced against BEFORE, stay
disclosed and are not fixed by widening this scope.

## Gate B boundary

Approve the exact manifest and the described fresh disposable resources, including
the three pinned font-asset reads, to authorize local implementation and tests.
Approval does not authorize ordinary data/schema changes, new financial policy,
Notes-sharing expansion, live providers, installations, cleanup, staging, commits,
pushes, merges or deployment. No application edit or runtime setup was performed
while preparing this proposal.

## Exact file list

| File | Action | Purpose |
| --- | --- | --- |
| `src/templates/billings/invoice_list.html` | modify | Render approved Services directory with existing lifecycle/payment filters and all current records/actions; no new server search or pagination. |
| `src/templates/billings/invoice_detail.html` | modify | Render approved Services detail/actions and one authoritative internal receipt section; preserve issue/cancel/delete/email/payment guards, appointment/client links and financial exceptions. |
| `src/templates/billings/invoice_create.html` | modify | Render approved Services create/client/appointment editor and separate invoice quick-client flow; preserve all field names, Choices search, line metadata, CSRF and source/return context. |
| `src/templates/billings/invoice_edit.html` | modify | Render approved Services draft editor; preserve saved line IDs, new_ prefixes, snapshots, whole-unit inputs, existing validation and protected-history behavior. |
| `src/templates/billings/payment_form.html` | modify | Render approved Services receipt/adjustment presentation around the actual server-supplied form, including dynamic fields and hidden retry keys; retain existing pages and redirects. |
| `src/templates/billings/invoice_pdf.html` | modify | Dispatch Services customer HTML document to the approved clean layout while preserving Notes flag, saved amounts/currency, logos, identity/date and mandatory exceptions; leave Logistics document unchanged. |
| `src/templates/emails/invoice_body.html` | modify | Dispatch only Services customer invoice email body to a clean fragment without internal Draft or routine settlement summaries. Retain original Logistics body, subject/recipient/reply-to/attachment contract and exception notices. |
| `src/templates/emails/invoice_body.txt` | modify | Dispatch only Services customer invoice email body to a clean fragment without internal Draft or routine settlement summaries. Retain original Logistics body, subject/recipient/reply-to/attachment contract and exception notices. |
| `src/apps/billings/pdf.py` | modify | Add a Services-only ReportLab drawing dispatch using the unchanged authorized invoice context. Retain original Logistics drawing helpers, access checks, filenames, metadata, saved values and include_notes behavior. |
| `src/apps/billings/tests.py` | modify | Update only Services presentation assertions affected by clean customer email labels and moving Choices initialization into a scoped asset. Retain all tenant/role/workflow/calculation/attachment/Notes assertions and verify searchable client behavior in the browser. |
| `src/apps/billings/test_presentation.py` | modify | Split internal accounting assertions from clean Services customer document/email assertions. Preserve authoritative status, receipt evidence, saved currency, filters, refunds, dashboard/admin and all Logistics checks. |
| `src/apps/billings/test_pdf_layout.py` | modify | Update Services layout/typeface/customer-status expectations and extend document preservation checks; retain original totals, saved-currency, tax, Notes flag, logo/identity, review and Logistics access/output assertions. |
| `src/templates/billings/services/invoices/base.html` | add | Inherit existing Phoenix dashboard parent and include scoped Services assets only; shared shell remains unchanged. |
| `src/templates/billings/services/invoices/assets.html` | add | Load existing local Manrope WOFF2 and new scoped invoice CSS/JS without Tailwind/DaisyUI/vendor/global theme changes. |
| `src/templates/billings/services/invoices/list.html` | add | Compose directory/filter/empty/read-only/error feedback around existing invoice querysets and permissions. |
| `src/templates/billings/services/invoices/detail.html` | add | Compose invoice information, internal lifecycle, actions and existing authoritative accounting data with preserved guards and navigation. |
| `src/templates/billings/services/invoices/editor.html` | add | Compose shared create/edit structure, fixed or searchable client, repeated lines, notes and summary while preserving current POST payloads and source context. |
| `src/templates/billings/services/invoices/line.html` | add | Render saved/new line controls with preserved names/prefixes/IDs/hooks, source selection, snapshot metadata and whole-unit attributes. |
| `src/templates/billings/services/invoices/manual_service_fields.html` | add | Render the existing opt-in save-as-service, category/new-category controls and hidden value; preserve existing side effects and compatibility. |
| `src/templates/billings/services/invoices/quick_client_modal.html` | add | Render separate invoice quick-client modal with six unprefixed fields, original endpoint/JSON hooks, draft preservation, validation and focus. |
| `src/templates/billings/services/invoices/payment_form.html` | add | Render the actual receipt/adjustment form, all dynamic and hidden fields, labels/errors, disabled currency, references and existing return navigation. |
| `src/templates/billings/services/invoices/field.html` | add | Provide semantic labels and linked server error/help presentation without changing server fields, validation, choices or prefixes. |
| `src/templates/billings/services/invoices/payments.html` | add | Give existing authoritative amount_rows/payment entries/audit links one internal home; no browser settlement arithmetic or role inference. |
| `src/templates/billings/services/invoices/document.html` | add | Render complete Services-only customer HTML document with issuer/logo fallback, identity/date, line items, Subtotal, applicable Tax, Total Amount, conditional Notes and required exceptions. No internal Draft/ordinary balance summary. |
| `src/templates/emails/services/invoice_body.html` | add | Provide clean Services invoice email body fragment using existing saved-currency presentation, total, identity/date, attachment and business contact. No internal Draft/routine payment summary; mandatory financial exceptions retained; no invoice Notes disclosure. |
| `src/templates/emails/services/invoice_body.txt` | add | Provide clean Services invoice email body fragment using existing saved-currency presentation, total, identity/date, attachment and business contact. No internal Draft/routine payment summary; mandatory financial exceptions retained; no invoice Notes disclosure. |
| `src/static/assets/css/services-invoices.css` | add | Translate approved v1 into Services-scoped Phoenix styles, Manrope, light/dark tokens, reflow, RTL, focus, errors, print and 44px targets. No shared token or stylesheet replacement. |
| `src/static/assets/js/services-invoices.js` | add | Scope progressive invoice editor/Choices/quick-client/form-error/dialog behavior to Services. Preserve current decimal-estimate display, repeated payloads, service/category transitions, whole-unit rules and native form writes; server remains authoritative. |
| `src/apps/billings/services_invoice_pdf.py` | add | Draw Services-only Letter PDFs with embedded Manrope, width-aware wrapping, existing supported logo fallback, repeated line headings/reference/page numbers, a single closing amount block and conditional Notes. Read only existing authorized values/flags; no finance calculation or state mutation. |
| `src/static/assets/fonts/manrope/manrope-regular.ttf` | add | Embed the upstream static Manrope regular face for Services PDFs. Fixed source commit and Git blob/size verification are recorded in font-sources.json. No package installation. |
| `src/static/assets/fonts/manrope/manrope-bold.ttf` | add | Embed the upstream static Manrope bold face for Services PDF hierarchy and Total Amount. Fixed source commit and Git blob/size verification are recorded in font-sources.json. No package installation. |
| `src/static/assets/fonts/manrope/Manrope-PDF-OFL.txt` | add | Retain the exact upstream copyright and OFL accompanying the new PDF TTF assets without replacing the existing WOFF2 license. Fixed source commit and Git blob/size verification are recorded in font-sources.json. No package installation. |
| `src/apps/billings/test_services_invoices_ui.py` | add | Add meaningful real Django tests for Services form inventory, prefixes, guards, search/quick-client contracts, draft/return behavior and absence of invoice assets on other verticals; existing backend services remain unchanged. |
| `src/apps/billings/test_services_invoice_documents.py` | add | Verify real Services ReportLab/HTML/email facts and no Draft customer label, conditional Notes, tax/saved currency, exceptions, fonts/long content; compare unchanged Logistics documents against frozen BEFORE and assert no invoice/ledger mutation. |
| `scripts/ui_preview/invoices_preview.py` | add | Create/start a fresh invoice-specific BEFORE/AFTER pair through existing source/cluster guards. Run the new setup-only fixture adapter before initial canonical parity and launch. Delegate lifecycle operations to existing tools; do not edit shared preview code or existing sessions. |
| `scripts/ui_preview/invoices_fixtures.py` | add | Seed only verified fresh setup-phase invoice review fixtures and canonical metadata for Services/Logistics roles and financial states. Refuse ordinary settings, unowned listeners, non-invoice routes or reseeding; use authoritative services for synthetic financial fixtures. |
| `scripts/ui_preview/invoices_checks.py` | add | Add owned-source/database-verified adapters for read-only runtime captures, exact whitelisted backend/browser tests and document/legacy comparisons. Retain financial-write/network guards and serial test database ownership checks; no ordinary resources. |
| `scripts/ui_preview/test_invoices.py` | add | Add offline refusal/route/identity/metadata tests for the new adapter without opening application databases or changing prior preview tooling. |
| `scripts/services_invoices_browser_check.py` | add | Exercise actual read-only Django BEFORE/AFTER and isolated write-enabled test LiveServer forms/receipt/refund/email flows, role/location/access states, four widths/themes, axe/focus/drafts and actual downloaded/emailed PDFs. Save new evidence only in the owned session. |
| `docs/services_invoices_workspace.md` | add | Document final Services presentation, preserved financial/routes/forms/Notes contracts, embedded font provenance, actual checks and limitations. No release authorization implied. |
