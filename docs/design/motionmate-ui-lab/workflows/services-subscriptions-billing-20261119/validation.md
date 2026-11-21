# Subscription/Billing validation plan — pending Gate B

Planning only. No runtime, database, provider, browser, fixture, migration or
financial test was executed. No ordinary application/provider health is claimed.

## Offline Gate A checks

Verify source references/hashes, documentation links, schema-2 workflow state,
Gate A stop and documentation-only ownership. No Django initialization is needed.

## Resource and preview constraint to resolve at B

The existing guard in scripts/ui_preview/guard.py rejects subscription/plan table
writes, blocks /billing/ routes and external redirects/network. Changing --route
does not enable plan changes or make the dashboard validator cover this module.
Retain these guards. B must concretely identify how the final test/fixture adapter
covers real Django forms and plan-review states, which interactive operations are
unavailable and how isolated backend tests cover domain/provider contracts.
Mocks are not browser evidence. Required form coverage cannot be silently waived.

Name and verify owned disposable PostgreSQL BEFORE/AFTER resources and a separate
test environment as required: settings, sanitized DB/owner, directory/system ID,
ports/processes and independent ownership proof. Existing migrations only on empty
owned databases under explicit runtime approval; no schema-source changes.
No ordinary local/staging/production/Test Lab database, .env/secrets/customer copies,
live Stripe, external services, workers or real email. Isolated tests may use
synthetic provider responses under explicit B test scope with networking blocked.
Do not activate Stripe, invent provider IDs for ordinary records or weaken guards.

Freeze actual working-tree BEFORE immediately before application edits; retain it
and refresh AFTER alone. One real Django BEFORE/AFTER review for this workstream,
equal initial synthetic records, distinct cookies/databases and recorded identities.
No standalone prototype. Keep unavailable provider actions clearly disclosed.

## Proposed behavior and authorization matrix

| Case | Required evidence after implementation |
| --- | --- |
| Roles/tenants | Services OWNER allowed; ADMIN/STAFF/ACCOUNTANT/VIEWER denied, direct POST included; no foreign-tenant subscription/plan/portal data. Preserve Business resolver and owner-only billing endpoints. |
| Effective state | Missing subscription; pending checkout; trial active/expired/missing end; active; expired; cancel-at-period-end; cancelled; grace active/expired/missing; stale/missing provider period; inactive plan/business. Preserve stored status versus effective access. |
| Provider return | billing_return=1 retains pending notice; no local payment/access restoration merely on return; actual webhook reconciliation unchanged. |
| Local plan selection | Same-page plan field/CSRF; current-plan no-op, invalid plan errors, no-subscription trial, valid switch, preserved trial dates/current semantics; no provider upgrade/checkout initiated. |
| Confirmation | Server-required module loss/quota review; exact plan and confirm_plan_change=1, cancel navigation, second POST; existing records retained, limits applied by current server policy. |
| Restrictions | FREE_TEST rejection, read-only/no-modify rejection and current conditional controls. No new permission or unconditional plan-change action. |
| Usage/prices | Actual server usage, unlimited/zero/at/over values, owner/staff/pending seats, shared appointment allowance; USD/EUR monthly/yearly server display, all flags/limits, arbitrary plan count and no configured plans. No financial arithmetic in UI. |
| Portal/recovery | Existing eligibility and precedence, owner/tenant/provider/plan/status/ID/configuration checks, trusted return URLs, POST/CSRF and current errors/redirects. Verify with isolated synthetic provider responses; interactive preview remains guarded. |
| Checkout/webhooks | Existing resume conditions, success/cancel/error routing and webhook/access state unaffected. No live call or claimed provider readiness. |

Relevant existing tests to inspect/select at B include apps.businesses.tests
BusinessSubscriptionViewTests, StripeCustomerPortalServiceTests,
StripeCheckoutServiceTests, CheckoutReturnViewTests,
SubscriptionEffectiveAccessPolicyTests and relevant lifecycle coverage, plus
apps.businesses.test_service_allowances and test_capabilities. Do not run broad
management/destructive suites. Existing tests are located, not currently passed.
Any necessary UI/adaptor test additions must be in the exact B manifest and
verify contracts rather than mirror markup.

## Browser/accessibility and Logistics preservation

Test populated/empty/long/error/read-only/attention/pending-confirmation states
at 1440/768/390px, light/dark, plus 320px reflow/relevant RTL/zoom. Check real login,
DOM forms/CSRF/field values, plan review focus/reading order, existing confirm/cancel
navigation where safe, labels/headings, visible keyboard focus, 44px targets,
contrast, table/mobile field relationships, no clipped state/price/date content,
no hidden consequences, reduced motion and theme-context retention. Retain axe
failures/incompletes. Explicitly record every guard-blocked interaction.

Shared subscription entry requires unchanged Logistics owner annual plan/usage
presentation, admin GET usage, disallowed mutations/other-role access, no Services
plan catalogue and disabled portals/recovery. Confirm original Logistics assets,
module/subscription/location policies and downstream data unaffected. Public
pricing, Customer Invoices and Business Settings are excluded consumers; regression
samples remain unchanged without editing them or their accepted records.

Keep logs/browser output/databases external to Git in verified owned resources;
save representative captures, fixture/check source and compact validation results.
Separate source inspection, isolated backend, actual Django/browser, manual review
and real provider/runtime verification. Workarounds or mocked providers do not
establish ordinary-runtime/provider readiness.

## Gate C prerequisites

Actual URLs, source/candidate/fixture/environment identities, equivalent initial
synthetic records, test evidence and honest unavailable-provider/form limitations.
Resolve required real-Django coverage before declaring Full Redesign validated.
Human acceptance and any later commit/release authority are separate; no cleanup.

## Gate B preparation — 20 November 2026

Gate A is now approved; runtime implementation and resource consent remain pending.
The existing coverage plan above is retained. integration.md now specifies exact
source/adapter boundaries and validation-resources.json specifies the new owned
resources/actions proposed for B. No runtime check or fixture has run.

All three modules use separate source/fixture/session identities; test runs are
serialized through the existing guarded test boundary on 127.0.0.1:8768 and only
the selected module AFTER cluster's runner-owned test_services_rollout database.
Keep read-only review financial blocks intact. Real write/form checks happen in
the separate synthetic test DB/LiveServer; provider SDK responses are synthetic,
external browser transport is blocked and provider-hosted screens remain unverified.
No fake UI substitutes for actual forms, routes, login, CSRF or permissions.

Do not run the existing dashboard validator as proof of module coverage: the
new listed screen adapter owns its cases. Reuse existing ownership, source, live
DB-identity and network guards unchanged. Evidence must distinguish inspected
source, isolated backend tests, real browser behavior and live provider/runtime
checks. Missing required evidence keeps validation/Gate C pending.
