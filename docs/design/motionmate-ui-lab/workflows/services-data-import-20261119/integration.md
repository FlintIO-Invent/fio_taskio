# services-data-import-20261119 — Gate B integration proposal

Design **v1**, SERVICE. Exact proposed scope: **31 files, 11 modifications
and 20 additions**. No production file has been changed.

Approved design SHA-256: `5030d8f2b0a120c98d66e5a7630e52f844b9b3e614f3511f0a3cf3ca451adf5e`.

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

Dispatch only the eleven listed shared entry templates to Services includes via
current_business.vertical == SERVICE; retain their complete non-Services bodies.
The new module base extends the existing Phoenix shell and loads this CSS only
for SERVICE. Existing shared status_badge/status_key/issue includes stay unchanged.
No Client Import wrapper/include/base/CSS/JS, view, parser, schema, preview store,
execution service, route, model, permission helper or retry mechanism is modified.

The hub presents the three existing capability-guarded import choices and their
download links; history moves to a header link under its existing guard. Labels
show Upload → Validate → Preview → Confirm → Result; validation remains upload
POST and confirmation remains the preview section, without new routes or JS.
Lead/service uploads keep csv_file, multipart encoding, CSRF, field/help IDs and
all optional-field/default/limit guidance. Service sample headers/rows/copyable CSV
use native disclosures; sample-csv-text remains. Clarify domain-record timing in
these new Services includes only: metadata/preview may be stored before confirm,
but clients/leads/services are not committed until the existing execute action.

Read-only previews retain all server issues, summaries and type-specific keys,
status meanings, before/after changes and category notes. Confirmation follows
rows and is shown under the same job/status/payload readiness conjunction. Keep
exact execute URL and no browser-supplied row payload. Results retain every code,
message/count, guarded next link and recovery. History remains metadata-only,
50 jobs/page, terminal-only details, no uploaded records or preview/digest exposure.

## Consumers and evidence

| Consumer/state | Required preservation and check |
| --- | --- |
| Existing Services Client Import | Keep accepted source/assets and actual upload/preview/confirm/result/unavailable behavior/appearance unchanged; direct regression. |
| Services Lead import | Preserve private historical Lead/REQUEST semantics, role/module gates, defaults, duplicates/category rechecks and no booking/invoice/client/outreach side effects. |
| Services Service/Category import | Preserve external-code update/create matching, optional/blank values, localized tax/price, target drift, capacity failure, atomic category+service writes and completed retry. |
| History | OWNER/ADMIN CRM-read policy, tenant isolation, metadata-only projection, terminal details and page query. |
| Logistics | Original hub/import/history fallback and capability/role/subscription behavior, client/service capacity checks and location/downstream scope unchanged. |
| Catalogue/billing | Existing entry/return links retained; no source edits or borrowed approval. |

Planned existing regression sources: apps.crm.test_importing;
test_client_importing/test_client_preview/test_client_execution;
test_lead_importing/test_lead_execution;
test_service_importing/test_service_execution; test_combined_service_import;
test_import_history; test_import_ux; relevant apps.businesses.test_logistics_usage_limits.
The new apps.crm.test_services_data_import_ui and browser script verify actual
rendered forms/payloads, empty/invalid/expired/stale/ready/completed states, quota
and duplicate rechecks, atomic rollback/retry, tenant/actor isolation and native
POST/CSRF. No duplication of the implementation in trivial markup-only tests.

## Module-specific risks and acceptance

Do not normalize different import permissions or hub/direct-route availability.
No new capability, import type, editable preview, mapping UI, schema/default,
retention policy, auto-confirm, restart or ignore-error behavior. Long rows/notes/
filenames and wide sample CSV must remain readable without document overflow.
Preserve one dataset/table relationships and all issues in mobile labeled records.
Default/review/error/duplicate/update explanations remain distinct and truthful.

The new synthetic fixture adapter makes current ready/blocked/expired/result and
metadata states via existing import services in setup phase only. Actual upload,
confirmation, stale-state and duplicate-POST scenarios run through real Django in
owned synthetic review/test data, with canonical initial facts equal on both sides.
Do not silently reset review records after browser writes. Existing Client Import
is regression-covered, not reopened or migrated. Missing required browser/form/
Logistics evidence keeps Gate C pending.

## Exact file manifest

The JSON manifest contains full before-SHA-256 values, add/modify actions, categories
and both-vertical assessments for each shared entry template. Added paths do not
exist yet; existing paths must match the baseline before execution.

| Action | Exact path | Category | Purpose |
| --- | --- | --- | --- |
| modify | `src/templates/crm/importing/data_import.html` | implementation | Select Services task-choice hub with unchanged per-type/history guards. |
| modify | `src/templates/crm/importing/lead_upload.html` | implementation | Select Services lead upload composition; preserve Logistics markup and multipart form contract. |
| modify | `src/templates/crm/importing/lead_preview.html` | implementation | Select Services read-only preview; preserve ready/blocked state, row data, issues and confirm POST. |
| modify | `src/templates/crm/importing/lead_result.html` | implementation | Select Services result composition with original codes/counts/next actions. |
| modify | `src/templates/crm/importing/lead_preview_unavailable.html` | implementation | Select Services unavailable state; retain status, message and recovery links. |
| modify | `src/templates/crm/settings/business_service_import.html` | implementation | Select Services combined CSV upload/examples; retain Logistics fallback and exact fields/hooks. |
| modify | `src/templates/crm/importing/service_preview.html` | implementation | Select Services create/update/category preview with complete changes, notes and confirm contract. |
| modify | `src/templates/crm/importing/service_result.html` | implementation | Select Services result with exact execution messages/counts/recovery. |
| modify | `src/templates/crm/importing/service_preview_unavailable.html` | implementation | Select Services unavailable state; retain original status/message/recovery. |
| modify | `src/templates/crm/importing/history.html` | implementation | Select Services metadata-only history with existing page size/links/guards. |
| modify | `src/templates/crm/importing/history_detail.html` | implementation | Select Services terminal-job metadata detail without exposing preview/customer rows. |
| add | `src/templates/crm/services/data_import/base.html` | implementation | Services-only assets on existing Phoenix shell. |
| add | `src/templates/crm/services/data_import/assets.html` | implementation | Load only this module CSS; no existing Clients assets are changed. |
| add | `src/templates/crm/services/data_import/hub.html` | implementation | Guarded three-type task rows, existing history link and five-stage process. |
| add | `src/templates/crm/services/data_import/lead_upload.html` | implementation | Existing CSV multipart form and optional-field guidance. |
| add | `src/templates/crm/services/data_import/lead_preview.html` | implementation | Read-only row results, exact summary/issues/statuses and existing confirmation. |
| add | `src/templates/crm/services/data_import/lead_result.html` | implementation | Existing outcome codes/counts and permitted next actions. |
| add | `src/templates/crm/services/data_import/lead_unavailable.html` | implementation | Existing expired/unusable message and lead upload recovery. |
| add | `src/templates/crm/services/data_import/service_upload.html` | implementation | Existing bound CSV form, header/example disclosures and copyable sample text. |
| add | `src/templates/crm/services/data_import/service_preview.html` | implementation | Complete server create/update/category changes/notes and existing confirm form. |
| add | `src/templates/crm/services/data_import/service_result.html` | implementation | Exact service execution outcomes/counts/next links. |
| add | `src/templates/crm/services/data_import/service_unavailable.html` | implementation | Existing unusable message and service upload recovery. |
| add | `src/templates/crm/services/data_import/history.html` | implementation | Current metadata list and 50-job pagination with responsive labels. |
| add | `src/templates/crm/services/data_import/history_detail.html` | implementation | Sanitized terminal-job metadata/counts; no uploaded rows or payloads. |
| add | `src/static/assets/css/services-data-import.css` | required_asset | Module-scoped Manrope/theme/record/form styles; retain Phoenix shell and global tokens. |
| add | `src/apps/crm/test_services_data_import_ui.py` | tests | Meaningful real Django route/form/CSRF/permission/tenant/data-preservation and Logistics fallback regression checks. |
| add | `scripts/services_data_import_browser_check.py` | tests | Real guarded pair capture/interaction/accessibility plus isolated LiveServer form checks; no ordinary DB/provider calls. |
| add | `scripts/ui_preview/data_import_fixtures.py` | implementation | Setup-only module synthetic fixtures and canonical initial parity through existing identity guards. |
| add | `scripts/ui_preview/data_import_preview.py` | implementation | Fresh module preview entrypoint using existing owned snapshot/session/cluster tools and proposed ports. |
| add | `scripts/ui_preview/data_import_checks.py` | tests | Allowlisted isolated tests/browser dispatch through unchanged existing source/database/network guards. |
| add | `scripts/ui_preview/test_data_import.py` | tests | Refusal tests for wrong route/settings/phase/session/source/cluster and provider/network boundary; no database setup in offline tests. |

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
