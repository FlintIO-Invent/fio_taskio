# services-subscriptions-billing-20261119 — Gate B integration proposal

Design **v1**, SERVICE. Exact proposed scope: **16 files, 1 modifications
and 15 additions**. No production file has been changed.

Approved design SHA-256: `66c935e2d8b4c16b87049779a2783b251c98ce1295f15d3d3c15c8e027ad81f1`.

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

Only businesses/subscription.html is modified. Extend the new module base and
select the new page include for resolved SERVICE; retain the complete original
non-Services content and Logistics usage includes. The base extends Phoenix and
loads this module CSS through page_assets only for SERVICE. No shared shell,
context/permission resolver, view/form/model, public plan-feature include, pricing,
Stripe service/configuration/checkout/webhook or migration source change.

New includes compose current plan/effective state first, available billing action,
server usage, plan comparison and adjacent existing impact review. Keep every
nested beta/availability/access/workspace guard and the recovery → portal →
resumable-checkout branch priority. All buttons remain original POST forms with
CSRF and original route/field names. Plan selection stays same-page plan POST;
confirmation stays plan + confirm_plan_change=1. Display the existing bound form
errors without changing validation. Existing local plan selection and provider
billing remain separate; the pilot explanation sits next to plan comparison.

Keep all actual status/period/deadline/unavailable messages, billing_return pending
notice, supplied USD/EUR monthly/yearly prices, flags/limits, arbitrary available
plan count, zero/unlimited/unknown values, owner/pending-seat semantics and shared
appointment allowance. Do not compute pricing, settlement or quota percentages.
No new cadence/currency toggle, proration, provider plan change, invoice history,
admin billing access or subscription financial operation.

## Consumers and evidence

| Consumer/state | Required preservation and check |
| --- | --- |
| Services owner | Missing/pending/trial/active/cancellation/grace/restricted/stale/inactive/fallback states, server form errors, plan impact and exact confirmation behavior. |
| Services non-owner | Current handler denial remains for ADMIN/STAFF/ACCOUNTANT/VIEWER, including direct POST. |
| Stripe destinations | Same owner/tenant/configuration/provider/ID checks, CSRF methods, error/redirect behavior and trusted returns; no SDK/webhook implementation edits. |
| Logistics owner/admin | Owner annual page/usage and original includes/assets remain; admin GET usage page and denied writes unchanged; no Services plan list or newly enabled portal/recovery. |
| Public pricing/Customer Invoices | No include/asset/projection/receipt changes; existing accepted work stays intact. |

Allowlisted existing backend sources: apps.businesses.tests.BusinessSubscriptionViewTests,
StripeCustomerPortalServiceTests, StripeCheckoutServiceTests,
CheckoutReturnViewTests, SubscriptionEffectiveAccessPolicyTests and relevant
SubscriptionBillingLifecycleEndToEndTests; apps.businesses.test_service_allowances,
test_capabilities and focused Logistics subscription-access cases. The new
apps.businesses.test_services_subscriptions_ui supplies meaningful template/data/
permissions regression tests. No broad destructive-management suite.

## Concrete financial/form validation boundary

The human real-Django pair retains ui_preview.guard unchanged: subscription/plan
SQL writes, /billing/ provider paths, external redirects/network remain blocked.
Do not claim that a visible button was successfully exercised there. Synthetic
setup can prepare distinct subscription/access/impact states before serve, while
both sides have equivalent initial canonical records and truthful projections.

The new services_subscriptions_browser_check.py includes real native form tests
on a separate StaticLiveServerTestCase at 127.0.0.1:8768 and runner-owned
test_services_rollout, invoked only through subscriptions_checks.py and the existing
dashboard_checks.execute guarded test boundary. That boundary verifies the owned
AFTER cluster before Django setup, restricts DB connections to its own postgres/
test_services_rollout with live directory/system-ID proof and allows loopback only.
It is an explicitly authorized test context, not a relaxation of review guards.

In that test DB, exercise same-page local plan POST, invalid plan/errors,
server-required confirmation/cancel, FREE_TEST/read-only rejection, owner-only
portal/recovery/resume POST/CSRF and native 302 outcomes. Mock only provider SDK
responses at the existing Stripe seam using synthetic fixture IDs; keep handlers,
forms, permissions and local services real. Abort every non-loopback browser
request before transport and record the attempted redirect URL; provider-hosted
screens and real payment/webhook delivery remain unverified. Never substitute a
fake browser UI or modify production endpoints to simulate success.

Serialize test DB creation/teardown and review identity checks because the guard
rejects an unexpected test database while present. On test teardown failure stop
and report exact owned resource identity; no connection termination, forced drop,
reset/reseed or cleanup. Tests must close threaded DB connections. Missing real
form/CSRF/permission evidence keeps Gate C pending; a static or mocked-only pass
cannot replace it. Local debug-allocator success does not prove ordinary runtime.

## Module-specific risks and acceptance

Current plan selection directly updates local subscription fields; preserve all
existing semantics, trial dates and cancellation handling. Never market this as a
provider upgrade or change it during UI work. Browser return cannot restore access.
Unknown/incompatible/provider-identity states retain current fallback behavior.
Retain supplied feature text/flags and defer booking-policy/copy discrepancies
rather than editing shared public copy. Long prices/dates, all consequences,
keyboard focus, read-only controls, both themes and mobile comparisons need real
browser checks. Existing records and financial logic remain unchanged outside
authorized synthetic test operations.

## Exact file manifest

The JSON manifest contains full before-SHA-256 values, add/modify actions, categories
and both-vertical assessments for each shared entry template. Added paths do not
exist yet; existing paths must match the baseline before execution.

| Action | Exact path | Category | Purpose |
| --- | --- | --- | --- |
| modify | `src/templates/businesses/subscription.html` | implementation | Select Services-only subscription composition; preserve original Logistics owner page, includes and asset loading. |
| add | `src/templates/businesses/services/subscriptions/base.html` | implementation | Services-only asset loading on existing Phoenix shell. |
| add | `src/templates/businesses/services/subscriptions/assets.html` | implementation | Load this module CSS only. |
| add | `src/templates/businesses/services/subscriptions/page.html` | implementation | Compose approved status-first page and existing messages/navigation. |
| add | `src/templates/businesses/services/subscriptions/current_plan.html` | implementation | Stored plan/status plus authoritative effective-access message/date. |
| add | `src/templates/businesses/services/subscriptions/billing_actions.html` | implementation | Preserve beta guard and exact recovery/portal/resume branch order, POST/CSRF and unavailable messages. |
| add | `src/templates/businesses/services/subscriptions/usage.html` | implementation | Render authoritative usage/staff capacity without new arithmetic. |
| add | `src/templates/businesses/services/subscriptions/plans.html` | implementation | Existing server plans/USD/EUR prices/limits/modules/current and read-only forms; render bound plan_form errors. |
| add | `src/templates/businesses/services/subscriptions/plan_change_review.html` | implementation | Complete server module-loss/quota evidence and exact second-submit plan/confirm_plan_change form. |
| add | `src/static/assets/css/services-subscriptions.css` | required_asset | Module-scoped Manrope/theme/record/form styles; retain Phoenix shell and global tokens. |
| add | `src/apps/businesses/test_services_subscriptions_ui.py` | tests | Meaningful real Django route/form/CSRF/permission/tenant/data-preservation and Logistics fallback regression checks. |
| add | `scripts/services_subscriptions_browser_check.py` | tests | Real guarded pair capture/interaction/accessibility plus isolated LiveServer form checks; no ordinary DB/provider calls. |
| add | `scripts/ui_preview/subscriptions_fixtures.py` | implementation | Setup-only module synthetic fixtures and canonical initial parity through existing identity guards. |
| add | `scripts/ui_preview/subscriptions_preview.py` | implementation | Fresh module preview entrypoint using existing owned snapshot/session/cluster tools and proposed ports. |
| add | `scripts/ui_preview/subscriptions_checks.py` | tests | Allowlisted isolated tests/browser dispatch through unchanged existing source/database/network guards. |
| add | `scripts/ui_preview/test_subscriptions.py` | tests | Refusal tests for wrong route/settings/phase/session/source/cluster and provider/network boundary; no database setup in offline tests. |

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
