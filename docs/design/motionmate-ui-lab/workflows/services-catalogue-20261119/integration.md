# services-catalogue-20261119 — Gate B integration proposal

Design **v1**, SERVICE. Exact proposed scope: **15 files, 3 modifications
and 12 additions**. No production file has been changed.

Approved design SHA-256: `146bd111bff46aadb8f3574772e610bed838ba9f6521ea5c7a5d41421939ba5e`.

## Closed scope and implementation method

Gate A is approved by the user's 20 November 2026 “proceed”, scoped to the named
v1 direction and recorded in approval-log.md. Approved brief/source-audit bytes
remain immutable. **Gate B implementation/resource approval is still pending.**
The exact manifest below is exhaustive: no wildcards, implied follow-on files,
new dependencies, schema sources or framework migration. Additional paths require
a concrete revised scope before edits. No application/source changes occurred in
preparing this proposal.

Keep Phoenix 1.23.0/Bootstrap, existing shell/navigation, theme controls and vendor
order. New CSS is module-scoped, uses approved light/dark semantics and existing
tracked local Manrope/OFL, and uses logical properties for scoped RTL. No global
CSS, user.min.css, collected static output, lab build, shared status component,
Client/Invoice accepted source, Logistics asset or public-site change. No new JS
is needed: use existing forms, native links and approved in-page/native disclosures.

Each module has its own new fixture/preview/check/browser/refusal-test sources.
They reuse existing ui_preview core/identity/network/test boundaries without editing
those helpers or existing adapters. Source/route/phase/ownership mismatch fails
closed before model import or writes. No arbitrary command/label from state runs.

## Concrete application integration

Replace only the three entry templates' parent with the new module base. In each
content block use the resolved current_business.vertical == SERVICE branch to
include the new Services content; retain the complete original non-Services body
in the fallback. The base extends dashboard_parent and adds CSS through page_assets
only for SERVICE. No shared shell, view, form, helper, model, route or vendor change.

The list preserves all service/category records, supplied counts, booking-plan
notice and guarded actions. In-page anchors navigate Services/Categories without
filters or hidden records. Edit forms retain the bound Django fields and complete
error output. Move the actual save/cancel group with its existing targets; do not
add client validation, autosave, search, pagination, bulk/archive dialogs or JS.
Responsive labeled records retain every original information subject and action.

Catalogue owns only list/editor presentation. Import and sample CSV link to the
unchanged named routes, even if Data Import is not approved or implemented.
Existing category-list redirect remains. Preserve create ?category, all field IDs,
CSRF and POST-only soft archive. Existing tax/localization, nullable category
compatibility, inline new category and atomic save behavior stay in Python.

## Consumers and evidence

| Consumer/state | Required preservation and check |
| --- | --- |
| Services owner/admin | Existing read versus write/module/subscription policy, real create/edit/invalid POST/CSRF and archive outcomes, full field payload/draft retention. |
| Other Services roles | Current denial/redirect and no unauthorized fields/actions. |
| Logistics list/editor | Original fallback structure/content/assets and real permitted/denied routes, currency/tax/service/category behavior unchanged. No booking fields introduced. |
| Invoices/appointments/public booking | Existing saved service/category choices, references, prices and tax behavior unchanged; focused source/functional regressions. |
| Existing Clients/Invoices | No changes to their templates/assets/fixtures/evidence or shared shell. |

Planned allowlisted regression sources: apps.crm.test_services_catalogue_ui;
apps.crm.tests.CRMBusinessScopingTests; apps.businesses.test_capabilities;
apps.crm.test_combined_service_import; focused existing invoice service-selection
and public-booking tests. Final runnable case names will be chosen from those
sources in the listed checks adapter, retaining all relevant authorization/data
assertions. No broad management/cleanup suite.

## Module-specific risks and acceptance

Preserving complete Logistics fallback bytes is essential because entry paths are
shared. Keep the original non-Services body structurally unchanged and compare its
rendered output/asset loading. Archived categories linked to an edit form and
legacy nullable references must not disappear through a new selector. Small
viewport records must retain headers/labels/actions, long codes and exact prices.
Measure both themes, keyboard/error focus, 44px targets and contrast after B.
Any booking-help correction requiring policy interpretation remains deferred.

The new browser script checks the real pair and uses a separately guarded test
LiveServer for form/regression writes. Fresh fixtures include OWNER/ADMIN/other
roles, read-only/missing-module, empty/long/archive/category compatibility cases
and a second tenant. Required browser/functional gaps keep Gate C pending.

## Exact file manifest

The JSON manifest contains full before-SHA-256 values, add/modify actions, categories
and both-vertical assessments for each shared entry template. Added paths do not
exist yet; existing paths must match the baseline before execution.

| Action | Exact path | Category | Purpose |
| --- | --- | --- | --- |
| modify | `src/templates/crm/settings/business_service_list.html` | implementation | Select Services catalogue include; retain original non-Services content and form blocks. |
| modify | `src/templates/crm/settings/business_service_form.html` | implementation | Select grouped Services editor; preserve original Logistics editor, all existing fields and draft/error handling. |
| modify | `src/templates/crm/settings/service_category_form.html` | implementation | Select Services category editor; retain original Logistics content and route/form contracts. |
| add | `src/templates/crm/services/catalogue/base.html` | implementation | Module base extends existing Phoenix shell; load assets only for current SERVICE business. |
| add | `src/templates/crm/services/catalogue/assets.html` | implementation | Load this module CSS through the existing page_assets block. |
| add | `src/templates/crm/services/catalogue/list.html` | implementation | Approved two-section service/category list, existing summaries and guarded actions. |
| add | `src/templates/crm/services/catalogue/service_form.html` | implementation | Grouped existing bound service form with complete fields/errors, pricing and booking guidance. |
| add | `src/templates/crm/services/catalogue/category_form.html` | implementation | Existing bound category form with code/status guidance and save/cancel. |
| add | `src/static/assets/css/services-catalogue.css` | required_asset | Module-scoped Manrope/theme/record/form styles; retain Phoenix shell and global tokens. |
| add | `src/apps/crm/test_services_catalogue_ui.py` | tests | Meaningful real Django route/form/CSRF/permission/tenant/data-preservation and Logistics fallback regression checks. |
| add | `scripts/services_catalogue_browser_check.py` | tests | Real guarded pair capture/interaction/accessibility plus isolated LiveServer form checks; no ordinary DB/provider calls. |
| add | `scripts/ui_preview/catalogue_fixtures.py` | implementation | Setup-only module synthetic fixtures and canonical initial parity through existing identity guards. |
| add | `scripts/ui_preview/catalogue_preview.py` | implementation | Fresh module preview entrypoint using existing owned snapshot/session/cluster tools and proposed ports. |
| add | `scripts/ui_preview/catalogue_checks.py` | tests | Allowlisted isolated tests/browser dispatch through unchanged existing source/database/network guards. |
| add | `scripts/ui_preview/test_catalogue.py` | tests | Refusal tests for wrong route/settings/phase/session/source/cluster and provider/network boundary; no database setup in offline tests. |

## Exact resources and authorized actions requested at Gate B

See validation-resources.json for this module's proposed HTTP/PostgreSQL ports,
resource IDs, settings, database naming, owner verification and exclusions.
No resource exists yet; live ownership is **not** verified and is never inferred
from a proposed name or installed tools. The offline check observed PostgreSQL
server tools, Python/Django/Playwright, Chromium cache and local axe/Manrope. No
installer, connection, socket binding, capture, DB process or browser was run.
Recheck all ports and refuse occupied listeners without stopping another process.

B authorization would cover fresh owned temporary source/session directories,
two empty PostgreSQL clusters, existing migrations only there, synthetic fixtures,
loopback Django apps, actual form/browser/axe/regression checks, and runner-owned
test_services_rollout creation/ordinary teardown. Start with recorded canonical
fixture parity and independent cookies; keep immutable BEFORE and refresh AFTER
alone. Never silently reset or reseed review data. No ordinary local/staging/
production/Test Lab DB, .env/secrets/customer copying, live provider/email/workers,
new migration source, cleanup or Git release operation is included.

Ownership checks must verify marker/UID/canonical paths, actual process/listener,
cluster directory/system identifier and live catalog identity before any writes.
Keep raw failures and accessibility incompletes, a compact test report and a few
representative screenshots; disposable logs/builds/DB/browser output stay in owned
external session storage. Existing font/license assets are tracked dependencies,
not disposable generated output. Fixtures/checks remain reproducible source.

## Baselines, independent activation and sequence

implementation-baseline.json captures branch/HEAD, full status, exact target
before hashes, approved design identity, protected-runtime digest and read-only
reference/dependency hashes for review. New targets must remain absent. It is an
integration audit, not the frozen real Django BEFORE or proof of a disposable DB.

The offline helper protects every other workstream's untracked records. Activating
three mutable helper baselines simultaneously would make later sibling checkpoints
look like concurrent edits and can create circular state-hash dependencies.
Therefore execution activation is **serialized in the requested module order**:
Catalogue, Data Import, Subscription/Billing. This is scheduling, not shared consent;
each exact design/manifest/resource scope requires its own B approval and can be
approved independently. A different module can be selected first without changing
its design/manifest; reconcile any already captured baseline explicitly.

The Catalogue helper baseline is activated after all three proposals/checkpoints
are frozen. The other modules keep their exact review/source baselines; invoke
workflow.py baseline on the selected module immediately before recording its B
approval/starting it, once peer planning records are stable. Compare its approved
manifest/target/design/branch against this capture first. Prior authorized module
changes are classified and preserved as unrelated work, never silently included.
Do not overwrite an existing helper baseline or bypass a mismatch. A real target
or scope change needs a concrete revised review, not silent rebaselining.

After explicit B for a selected module:

1. Verify latest user authorization, approved design/manifest, source hashes,
   branch/status and unrelated work; activate its helper baseline if not already
   activated, then record hash-bound B and run check --pre-implementation.
2. Capture actual working-tree runtime bytes with the existing capture tool before
   manifest edits. Add only approved adapter/test sources needed to construct the
   new pair; create fresh clusters/fixtures using the saved source as BEFORE.
3. Prove equivalent initial canonical fixtures and source/environment identities;
   preserve BEFORE. Implement only approved application paths locally, then
   refresh AFTER alone. No historical HEAD substitution or synthetic UI Lab.
4. Run the prospective validation.md cases with the exact guarded adapter; retain
   failures, scoped fixes/reruns and evidence for Services plus unchanged Logistics.
   No unrelated source repair or additional test/dependency installation by implication.
5. Present one real interactive Django BEFORE/AFTER review for this module with
   URLs, source/candidate/fixture/environment hashes, behavior/accessibility results
   and limitations. Stop at C for acceptance. No commits/push/deployment/cleanup.

## Gate B decision

Approve local implementation only for this named v1 design and the exact
implementation-manifest.json identity, together with the actions/resources in
validation-resources.json and constraints above. Approval is not acceptance,
provider readiness, another module's consent, release or cleanup authorization.
The helper-derived manifest/design digests are in gate-b-review.md. All B/C
approval fields and runtime resource authorization records remain empty.

The [workflow skill](../../../../../.agents/skills/motionmate-ui-workflow/SKILL.md)
requires: “stop for explicit authorization of that manifest”. This is the requested
Gate B boundary after completing the concrete proposal, not a new permission gate.
