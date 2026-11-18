# Services Clients v1 — production integration proposal / Gate B

Gate A approved by the user's message **“approved”**, immediately following the
Clients v1 review. Verified design digest:
`619258b4942682ca18d2d2cd1a93fd6258bbe1d71f9c23a6c0344a280f586043`.
All 733 approved artifacts still match. No production implementation is authorized.
The original integration.md, brief, validation and prototype reports are frozen
Gate A evidence: this separate proposal preserves their approved bytes.

## Concrete scope

Translate v1's Services Clients content into existing Phoenix 1.23.0 and Django.
Retain the actual shared shell/navigation/theme storage and Phoenix breakpoints;
the synthetic lab sidebar/drawer is a design reference, not a replacement shell.
No Tailwind/DaisyUI production imports, new framework, dependency installation,
model, schema, migration source, server policy or financial operation.

Directory/profile/create/edit, CSV upload/preview/result/unavailable, inline client
presentation and archive confirmation are included. Appointments, requests and
invoice creation/details remain existing routes. The legacy `/crm/staff/clients/all/`
view retains its current multi-client behavior; the new profile dispatch requires
SERVICE **and** single_client. Logistics stays on existing branches.

Existing local Manrope and its OFL notice are already under src/static/assets/fonts;
the WOFF2 matches the approved lab bytes. No font/vendor copies or global assets
need changing. The parent exposes page_assets, so it stays untouched. New styles
are scoped to `.mm-services-clients` / the Services inline client modal. Existing
Phoenix controls, Bootstrap modal lifecycle, named forms and billing partials are
reused. No generated bundles or collected static files are in this manifest.

## Closed manifest

**31 exact files: 12 modifications, 19 additions.** Baseline hashes identify the
bytes reviewed before Gate B. An absent addition must still be absent immediately
before implementation. No wildcard or implied follow-on paths are authorized.
Shared flags, consumer impact, regressions, baseline branch/status and resource
scope are also saved in [implementation-manifest.json](implementation-manifest.json).

| Path | Operation | Purpose | Baseline SHA-256 |
| --- | --- | --- | --- |
| `src/templates/crm/main/client_list.html` | modify | Dispatch SERVICE directory to the scoped Phoenix composition; retain existing Logistics branch and list route. | `853eb62e3a03015574237156f20f15a3ccbc4f2af979eaa275b8105343ff8e23` |
| `src/templates/crm/main/client_detail.html` | modify | Dispatch only SERVICE single-client detail; preserve legacy all-clients and Logistics detail branches. | `85292c58667afd06315749205784ab85237279a6ccdd6fc1cc3c8fb3ef41703d` |
| `src/templates/crm/forms/client_create.html` | modify | Dispatch SERVICE creation to the complete 32-field form; retain existing Logistics form and address script. | `228609745d8a907a8aeffebb3089b543eb4274fdbb0f61603afa81d78c665d50` |
| `src/templates/crm/forms/client_update.html` | modify | Dispatch SERVICE editing to the complete form; preserve Logistics editing. | `b49a9a3aec9da20cfb4059b9e04722f15f75acd1e8a1d74233f4de9ae3f18051` |
| `src/templates/crm/importing/client_upload.html` | modify | Dispatch SERVICE CSV upload presentation while retaining existing upload contract and Logistics branch. | `927eb0d4a082bb23388be5ab6364c85b1d3ac8c65bc85694a6fa60ff6fc016f5` |
| `src/templates/crm/importing/client_preview.html` | modify | Dispatch SERVICE stored CSV preview; keep ready/blocked/file/capacity guards and Logistics branch. | `793f895d3a01f7181fb930dea3c4e5ac40d62c6c693469b63c54cb9e714ed53b` |
| `src/templates/crm/importing/client_result.html` | modify | Dispatch SERVICE real import outcomes including retry/expired/capacity errors; retain Logistics branch. | `5d1893dbc7d5d02f788cd5cec670339733055c913857471ad6dc9b421d5b9558` |
| `src/templates/crm/importing/client_preview_unavailable.html` | modify | Dispatch SERVICE expired/unavailable presentation; keep 410 response and existing recovery routes. | `ddc0c01ae36ce89c348e424d228adb03a123edd334e233177db358a98fbbdba4` |
| `src/templates/crm/includes/draft_client_modal.html` | modify | Add a Services-only modal scope/assets and improve labeled client error presentation while retaining the existing six prefixed fields and destination hooks. | `a51639f20188bd1d023edc98df61a0e9fc4609f0894c0951fe4d84f1be541a94` |
| `src/templates/crm/services/clients/base.html` | add | Extend the existing Phoenix dashboard parent; conditionally load Clients assets for SERVICE without changing global shell, navigation or theme handling. | `absent` |
| `src/templates/crm/services/clients/assets.html` | add | Load new scoped CSS and progressive JS; reuse the installed local Manrope font without new dependencies. | `absent` |
| `src/templates/crm/services/clients/list.html` | add | Render approved directory from actual clients queryset; retain GET filters, List.js hooks/10-row pagination, selection and six sort subjects. | `absent` |
| `src/templates/crm/services/clients/detail.html` | add | Render approved profile from single_client, role/module guards and existing context; include authoritative invoice partial unchanged. | `absent` |
| `src/templates/crm/services/clients/form.html` | add | Render one create/edit form with all bound fields, six sections, original field names/IDs, validation summary, hidden fields, CSRF and return routes. | `absent` |
| `src/templates/crm/services/clients/field.html` | add | Reuse existing pure booking_widget helper for accessible bound widgets, labels, help and per-field errors. | `absent` |
| `src/templates/crm/services/clients/appointments.html` | add | Present existing five upcoming/recent appointment query results and existing authorized list/create/detail links, without a new query or status policy. | `absent` |
| `src/templates/crm/services/clients/import_upload.html` | add | Present actual CSV limits, optional-column help, csv_file upload field and existing template download. | `absent` |
| `src/templates/crm/services/clients/import_preview.html` | add | Present server-owned preview rows, statuses, issues and capacity; confirm only under existing ready-job guard. | `absent` |
| `src/templates/crm/services/clients/import_result.html` | add | Present existing execution_result variants, counts, duplicate/retry protections and permitted history/recovery links. | `absent` |
| `src/templates/crm/services/clients/import_unavailable.html` | add | Present the supplied unavailable/expired message and original recovery actions. | `absent` |
| `src/static/assets/css/services-clients.css` | add | Translate approved v1 content into scoped Phoenix/Bootstrap CSS, semantic themes, existing local Manrope, logical spacing/RTL, reflow and motion/focus rules. Scope inline styles to Services modal only. | `absent` |
| `src/static/assets/js/services-clients.js` | add | Progressively enhance existing List.js sort/selection hooks, section/error focus and address behavior, and Bootstrap archive confirmation; use existing forms for all writes. No synthetic records or AJAX replacement of full-page forms. | `absent` |
| `src/static/assets/js/draft-client.js` | modify | Add Services-scoped field ARIA/error associations; preserve endpoint, FormData, JSON handling, prefixes, draft copy/select and Bootstrap lifecycle. | `8bb2edc6d2268933e0cb3bf2c0889ca12da5ceb320b8326a691ebc7d49373b0d` |
| `src/apps/crm/tests.py` | modify | Replace only the obsolete literal inline showTabForElement assertion with a behavior-relevant presentation hook expectation; retain all other tests and fixtures. | `2f87d446cbc25ef9c14f4c21546965abb6753470d2acdfb8752feb0751fd1523` |
| `src/apps/crm/test_services_clients_ui.py` | add | Add disposable-only tests for form inventory/validation/return routes, role/module/quota/tenant behavior and Services-vs-Logistics branch/asset isolation; reuse existing policy services. | `absent` |
| `scripts/services_clients_browser_check.py` | add | Add actual Django Chromium interaction/reflow/theme/axe and draft/import/archive/browser checks; retain raw findings under the owned preview session only. | `absent` |
| `scripts/ui_preview/clients_fixtures.py` | add | Add verified-setup-only synthetic Clients review fixtures and canonical inventory for Services and Logistics regression tenants; refuse unowned settings/session/database before writes. | `absent` |
| `scripts/ui_preview/fixtures.py` | modify | Conditionally invoke Clients fixture adapter only for new owned Clients preview sessions, merge its account/fixture metadata and compare equivalent BEFORE/AFTER inventories. | `82d1f7acf3661cb4f72ae84daee783d087212a8cd13fcc1a243cdc554f25ad00` |
| `scripts/ui_preview/clients_checks.py` | add | Add ownership-verified backend/browser/interactive adapters using existing source/database/network guards and sanitized settings; preserve BEFORE and refresh AFTER alone. | `absent` |
| `scripts/ui_preview/test_clients.py` | add | Cover new adapter/fixture refusal and route/isolation behavior without touching application databases in tooling unit tests. | `absent` |
| `docs/services_clients_workspace.md` | add | Document final Services client presentation, preserved contracts, validation evidence and review limitations without implying release authorization. | `absent` |

## Source contracts and shared-consumer assessment

The actual sources remain authoritative: CRM views.py client create/list/update/
archive/detail and import functions; PrivateClientForm/QuickClientForm; Business
resolver, membership/module/subscription/capacity checks; Client/ImportJob; existing
invoice presentation and Logistics location-aware invoice/parcel scope. No edits
to those implementations are proposed.

| Consumer | Intended effect | Required regression evidence |
| --- | --- | --- |
| Shared CRM list/create/edit/import templates | SERVICE conditional dispatch; keep original non-Services body/scripts intact. | Services owner/admin/staff/accountant/viewer; active/grace/restricted/module-denied; Logistics equivalents, client imports and invalid form posts; no Clients CSS/JS/root on Logistics. |
| Single-client detail / compatibility all-client route | SERVICE single-client profile only; existing multi-client fallback retained. Reuse crm/main/client_invoice.html unchanged inside scoped content. | Tenant 404s, role gates, invoices six per page, financial review/refund labels, disabled modules, appointment history, legacy all-client route with no single-client invoice data; Logistics assigned-site financial filtering. |
| Inline draft modal and draft-client.js | Scoped Services presentation/ARIA only; parent appointment/request forms, compatibility lead mode, JSON payload and lifecycle retained. | Both draft destinations: prefill, invalid fields, 400/403/network/unknown-save error, quota, success, cancel, repeated open, submit lock, selected/copy result, draft and focus return; non-Services behavior preserved. |
| Phoenix shell/vendor/assets/font | Read-only inputs; new page_assets include and local scoped selectors. | Existing Services and Logistics shell, branding, theme/drawer/navigation, assets order and RTL remain intact. No new shell CSS on unrelated pages. |
| Preview fixture orchestration | Add Clients seed only in newly owned sessions whose requested route is Clients. Existing sessions and other-screen fixture paths unchanged. | Refuse wrong settings/phase/session/cluster; default adapter compatibility; source and full fixture identity parity before first browser write. |

### Routes/forms/DOM/financial guarantees

- Preserve client routes, GET `q`, `district`, `is_active`, true/false/1/0 aliases,
  business-derived District/Locality labels/choices and empty filters. List.js still
  paginates ten rows from the server-filtered dataset; retain clientsTable,
  clients-tables-body, valueNames name/email/phone/company/district/active,
  data-list, data-list-info/view/pagination and complete row/selection hooks.
  Keep six sort subjects accessible through the visible toolbar without a second
  List.js initialization or keyboard controls clipped inside a hidden header.
- Source inspection finds the current table's row checkboxes lack the
  data-bulk-select-row hook expected by Phoenix. This is an unverified existing
  interaction risk, not a claimed browser finding. New Services markup must supply
  complete hooks; preserve the Logistics branch and report any BEFORE failure
  rather than patching its process or vendor JavaScript.
- Full-page create/edit submit the existing PrivateClientForm with all 32 fields,
  names, IDs, values, bound errors, hidden fields and CSRF. Keep data-client-form,
  client-form-error-summary, client-create-address-data, address data hooks and
  existing address defaults/compatibility behavior. Sections replace presentation
  tabs; existing form/detail anchor IDs remain meaningful where exposed. Open the
  section containing an error and focus the linked summary/control. No client-side
  validation may weaken Django validation or discard submitted values.
- Company remains required even for Individual in manual/quick creation. CSV
  fields remain optional; supplied values remain checked. Create success returns
  Clients list; edit returns client detail. No is_active field or restore workflow
  is invented. Assignee choices stay active, same-business eligible memberships.
- The one legacy test in crm/tests.py checks a literal inline showTabForElement
  implementation string. Replace that specific assertion with the new error-focus
  hook and test actual behavior in the new suite; do not retain dead JavaScript to
  satisfy a string check. All other tests/fixtures stay intact. This file already
  differs from the historical Step 7 hash; do not rewrite the old preservation
  manifest or reset the file to silence that pre-existing mismatch.
- Archive remains POST+CSRF to the existing endpoint, owner/admin under the existing
  write gate. Bootstrap confirmation is a presentation enhancement; it never
  archives via GET, bypasses server checks or introduces delete/restore. Explain
  existing invoice/appointment retention and ACTIVE-to-INACTIVE classification
  effect; other classifications remain unchanged.
- Profile history uses existing context/querysets, role/module guards and invoice
  presentation, including all five Services roles' permitted billing reads. Keep
  original totals, balance due/review/refund/email-note semantics, six-row
  invoice_page pagination and existing invoice/appointment links. Do not infer
  payment/settlement, recalculate money, add a payment workflow or broaden reads.
- Import keeps csv_file, multipart POST/CSRF, actual limits, existing named template
  download, job ownership, server-stored rows/issues/capacity, ready confirmation
  POST, duplicate/retry behavior, all result codes, history gates and unavailable
  410 behavior. No browser parser or new execution endpoint.
- No production lab scenarios, fixtures, review widgets, design/debug messages or
  synthetic data. Export gains no implementation or endpoint; present the existing
  unavailable action honestly. No merge, activity writer or follow-up policy.

## Disposable validation resources — permission requested at Gate B

No runtime setup has occurred. The following is a proposed authorization scope,
not a claim that clusters already exist or that a test-looking name proves ownership.
Read-only ss preflight reports the proposed ports free; recheck immediately before use.

| Resource | Scope |
| --- | --- |
| BEFORE / AFTER HTTP | New independent loopback Django applications on 8860 / 8861, launcher 8862. |
| PostgreSQL | Two new private clusters on 55610 / 55611 in tool-created /tmp/motionmate-preview-session-*; generated names mm_preview_SESSION_before/after. Never ordinary port 5432. |
| Source snapshots | New tool-owned /tmp/motionmate-preview-snapshot-* and session source directories. Freeze actual working-tree bytes before production edits, including authorized uncommitted sources. No historical commit substitution, .env, secrets, customer uploads or ordinary records. |
| Settings/identity | ui_preview.settings for runtime; taskio.services_test_settings for tests. Verify owner marker, process, canonical pgdata, system_identifier, host/port/database before every first write; fail closed. |
| Migration/setup | Apply only existing checked-in migrations to these empty disposable databases and the runner-owned test database. Create only synthetic fixtures; no migration source/schema changes. |
| Review writes | Login/session/CSRF, client create/edit/archive/quick-create, CSV validate/preview/confirm/retry and draft workflows in these owned environments only. Existing runtime financial/platform writes remain blocked. |
| Regression DB | Create/drop test_services_rollout only on the independently verified AFTER private cluster; no ordinary database. Existing tests may create synthetic users, invoices/payments/credits/import jobs strictly in that isolated test database. |
| Browser/tooling | Existing Chromium executable and axe package; local browser/server traffic only, test live-server port 8768. Evidence/temp files only in this task/owned session directories. No downloads or installs. |
| Integrations | Providers, real email, workers and external networking disabled; preserve existing guards. Invoice detail/create GET navigation may be inspected, but financial POST operations are not enabled for interactive review. |

The existing launcher records/uses PYTHONMALLOC=debug as a review workaround.
Retain that disclosure. A passing debug-allocator review does not establish
ordinary-runtime stability; the historical ordinary-runtime issue remains outside
this scope. Preserve all existing preview processes/data. No automatic cleanup.

### Execution order after B

1. Verify approved design/manifest and pre-implementation branch/status/file hashes.
   Capture the actual working-tree BEFORE before touching production source.
2. Add the approved preview adapters/tooling, then create a **new** owned pair with
   the frozen BEFORE and equivalent synthetic fixtures. Check both sides' settings,
   source/cluster identities, cookies, credentials and canonical fixture inventories.
   Keep old review sessions unchanged. Capture actual BEFORE interactions/findings.
3. Implement only the manifest's scoped source/tests/docs. Do not edit the lab v1
   or approved evidence. Refresh AFTER alone using existing migration-source guards.
4. Run focused backend and real-browser checks; record baseline failures separately,
   fix within scope and repeat only affected checks. Never reset/reseed interactive
   fixtures to manufacture parity; reserve separate validation accounts/test data.
5. Present actual interactive BEFORE/AFTER URLs and source/fixture identities at
   Gate C. Acceptance and release remain separate; no Git release operations.

## Validation plan, risks and preservation

Backend labels (only through the owned test adapter): new Services Clients suite;
CRM CRMBusinessScopingTests, QuickClientTests, ClientInvoiceTests, client import
validation/preview/execution suites, Logistics client capacity and affected
LogisticsFinancialAccessTests (client history); billings presentation; existing
Services booking presentation/draft regression coverage. Tests may verify actual
POST/CSRF/tenant/quota/retry contracts without modifying the underlying policies.
Use targeted labels/methods for unrelated broad suites and retain final logs.

Real browser: actual login and full-page create/edit, invalid bound forms and
all 32 values; six sorts, ten-row pagination/View all, selection and filter aliases;
profile/notes/legacy route; archive confirmation and retained obligations; CSV
upload/ready/blocked/expired/changed/retry paths; appointment and request inline
creation retaining unsaved drafts and focus; module/role/read-only/quota states;
same-business assignment and cross-tenant denial. Verify permitted invoice reads
and existing navigation without enabling interactive financial writes.

Run 1440×900, 768×1024, 390×844 and 320×844 in both themes; long/partial/empty/error/
restricted cases, touch targets, labels, contrast, keyboard/Bootstrap focus/return,
reduced motion and scoped RTL. Preserve table associations and check reflow. Retain
raw axe violations/incompletes, console/request failures and unsupported AT/native
zoom/browser checks. Existing shell warnings may remain; distinguish unchanged
BEFORE findings from new errors, do not claim full-page WCAG or provider readiness.

The 31-file manifest excludes all models/views/forms/URLs/services/migrations,
shared parent/vendor/CSS bundles, public site, Logistics templates/services,
Logistics financial guards, billing presentation/receipt/payment files, collected
static output, approved lab/reference assets and historical preservation manifest.
Shared wrappers/modal/helper require Services and Logistics regressions; no global
CSS/theme/nav changes. Server contracts and data queries stay authoritative.

Main risks: scoped CSS in a Phoenix parent, hidden-section errors, List.js/selection
binding, native form required state after address swaps, date/currency presentation,
Bootstrap focus and real import result variants. Address these with actual BEFORE/
AFTER and targeted tests. Integration must never copy the prototype's hard-coded
records, permission projections, import success, financial labels or simulated writes.

The existing Step 7 manifest mismatch in src/apps/crm/tests.py remains documented;
its intake bytes match HEAD. The planned single assertion change is explicit and
will be distinguished from that historical mismatch. All 733 design artifacts and
unrelated production files remain protected. Existing dirty files are precisely the
Clients lab package and additive ui-lab/previews.json entry from this task; retain
those bytes. No dirty implementation target exists at baseline. Hash drift or an
overlapping edit requires reconciliation, never reset/clean/silent rebaseline.

No source-level rollback command, destructive database operation, worktree creation,
staging, commit, push, merge or deploy is authorized. Any later rollback is a scoped
reviewed patch, never a working-tree reset or database restore by implication.

## Gate B — awaiting implementation and resource authorization

Manifest digest:
`f56c21795f58907ebf784b2afd8c0040534a533f069ec68d59a4531957edc48d`.
Design v1 remains bound to its Gate A digest above. Review [the exact JSON manifest](implementation-manifest.json)
and [read-only preflight](integration-preflight.json).

Requested: implement these 31 files and use only the explicitly described fresh,
owned disposable runtime/test resources to reach Gate C. Implementation approval
is pending. No database, source implementation, installation or release action
follows until that approval arrives. This is the separate gate required by the
invoked motionmate-ui-workflow skill, not a request to reapprove v1's design.
