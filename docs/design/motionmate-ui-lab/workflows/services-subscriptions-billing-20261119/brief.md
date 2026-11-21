# Services Subscriptions & Billing — design direction v1

19 November 2026 · Full Redesign · SERVICE · **Gate A pending**

Primary route: `/businesses/subscription/` (`business_subscription`).
Outcome: clarify current access, available billing action, usage and plan choice
while preserving all subscription and Stripe behavior.

## Authorization and independent ownership

The current user requested three independent workstreams and said:
“Use Workflow v2: audit and design planning first, then one real Django
BEFORE/AFTER review after implementation.” and “Stop at Gate A for
design-direction approval for each module.”

This task owns the proposed Services subscription-page presentation only.
Catalogue/Data Import approvals are independent. Customer invoices/payments,
public pricing/signup, checkout return screens, Business Settings, team management
and all Logistics UI remain outside redesign scope. Billing routes remain real
destinations, not replacement workflows.

Authorized work is offline source audit and saved planning/state. No application
edit, runtime/database setup or access, data/migration change, provider call,
install, staging, commit, push or deployment. Gate A is direction only; exact
integration files and disposable validation scope follow after A.

## Actual Django audit — source evidence

Source: `src/taskio/urls.py:129–146` → `src/apps/businesses/urls.py` →
`business_subscription` (`views.py:664–828`) → current Business/membership,
`BusinessSubscription`, `ClarivoPlan`, `BusinessSubscriptionPlanForm`
(`forms.py:440`), usage/plan services (`utils.py:545–613,1048–1101`), portal
availability (`stripe_portal.py:47–174`) →
`src/templates/businesses/subscription.html` → Phoenix shell.

| Concern | Authoritative current behavior to preserve |
| --- | --- |
| Entry | Outer OWNER/ADMIN decorator; for **Services**, the handler explicitly denies non-OWNER. Logistics has a separate permitted admin GET usage path. No new admin billing permission. |
| Access | Effective access code, end date and checkout resumption come from `subscription.effective_access_state`; stored status and effective access differ. Preserve messages/dates and `billing_return=1` pending-confirmation notice. |
| Catalogue | Active `ClarivoPlan.motionmate_plans()` for SERVICE, business-aware server display pricing. Preserve both USD/EUR monthly/yearly, current/recommended labels, module flags and limits. |
| Local plan selection | Same-page CSRF POST with hidden `plan`; `assign_business_subscription_plan` changes the **local subscription record**, with no new checkout. Preserve trial dates and all current source semantics, including cancellation-flag handling. Never present this as a Stripe upgrade. |
| Confirmation | Server impact decides whether to show usage/module losses; second POST includes `plan` and `confirm_plan_change=1`. Cancel returns to subscription route. Records remain; future activity may be limited. |
| Restrictions | FREE_TEST changes rejected; non-modifiable subscription changes rejected. Keep current-plan response, missing-subscription trial selection, form validation and read-only conditions. No invented entitlement. |
| Usage | Server `current_usage_summary`/`staff_capacity`; active clients, invoices/month, appointments/month, users, full/over/within state, unlimited values, owner seat and pending-invitation semantics. Internal/online appointments share allowance. No browser quota calculation. |
| Manage billing | CSRF POST `/billing/customer-portal/`, `billing_customer_portal`, OWNER only (`views.py:193–220`); exact server eligibility/configuration, no guess from status. |
| Recovery | CSRF POST `/billing/payment-recovery/`, OWNER only (`views.py:223–250`), independent availability, existing priority over normal portal. Access returns after provider confirmation, not browser return. |
| Checkout | CSRF POST `/billing/checkout/resume/`, OWNER only (`views.py:149–190`), existing `can_resume_checkout`, success/cancel/error destinations unchanged. |

`stripe_portal.py` disables portal/recovery for Logistics and validates owner,
tenant, provider, plan, customer/subscription IDs, active business/plan, trusted
return URL and configuration. Preserve checkout, webhook reconciliation and the
existing `not subscription.is_beta_plan` presentation condition.

This page concerns Motionmate platform billing. No customer invoice balances,
receipt entry, settlement calculations, invented payment success, price IDs,
proration, cadence/currency selector or provider-side plan migration is proposed.

## Findings and proposed composition

These are source findings, not browser observations or provider verification.

| Current source pattern | Proposed design | Benefit |
| --- | --- | --- |
| Large gradient workspace card repeats plan/status; pilot explanation precedes billing actions. | One h1 **Subscriptions & Billing**; calm current-plan panel with current access message and existing available billing action beside it. Pilot/local-plan explanation accompanies plan selection. | Owner sees the current task before plan comparison. |
| Important billing predicates are spread through a large template. | One **Motionmate subscription billing** region preserving recovery → portal → resumable-checkout branch order and every nested guard/message. | One truthful next action, no new eligibility logic. |
| Usage/plan panels repeat nested cards and small uppercase text. | Compact labeled usage rows; aligned comparison panels with explicit USD/EUR monthly/yearly, limits/modules, current/recommended labels. | Easier comparison with the same prices/quotas. |
| Downgrade review is a long warning between usage and plans. | **Review plan change** adjacent to comparison, keeping all impact details, quota table and current confirm/cancel POST/link. | Consequences stay with the decision; no new modal. |
| Bound `plan_form` exists but errors are not rendered. | Display its existing field/non-field messages in the plan-choice region, preserving validation/response handling. | Explains invalid server submissions. |

Desktop layout proposal only:

```text
Subscriptions & Billing                        [Business Settings — existing guard]
                                               [Back to dashboard]
Provider-return confirmation / existing messages
Current plan + stored status + effective access | Existing eligible billing action
Usage: label | used / supplied limit | supplied status | staff availability
Plan comparison + “Local plan selection during the pilot” explanation
Available plan panels: prices / limits / modules / existing form or current state
Review plan change when supplied: consequences + quotas + Confirm / Cancel
```

Plan count follows the actual available list; no assumption of three configured
plans. Comparison prices are not asserted renewal charges or receipts. No new
currency/cadence toggle. Unlimited, unknown, missing subscription, unavailable
billing and zero usage remain distinct.

Keep messages for pending checkout; trial active/expired; subscription active/
expired/cancelled; cancel-at-period-end; grace active/expired/missing; stale/
missing provider period; inactive plan/business; fallback unavailability. Keep
actual deadlines. Never equate stored ACTIVE with paid/accessible or portal
return with collection success.

## Motionmate styling and interaction

Use approved [design system](../../../motionmate-design-system/DESIGN.md),
[components](../../../motionmate-design-system/COMPONENTS.md) and
[vertical boundaries](../../../motionmate-design-system/VERTICALS.md): existing
local Manrope/OFL, indigo action, semantic textual states, calm light/navy dark
surfaces, 4px spacing, 12px panels and 8px controls. Remove decorative gradient and
repeated values in Services only, retaining every distinct supplied fact. No
ornamental charts, estimated percentage bars or advertising hero.

Keep Phoenix 1.23.0, Django includes, Bootstrap controls, shell/theme/navigation
and breakpoints. Only module-scoped styling may follow B. No production
Tailwind/DaisyUI, global font/token change or new dependency. The read-only
Phoenix pricing-column example informs alignment, not financial policy.

- Desktop: status/action first, usage next, comparable plan panels below. Tablet:
  stack billing action as necessary, retain comparable fields. Mobile: full-width
  action groups, stacked plan panels, labeled quotas, complete price/state/limit
  labels and wrapping names/dates; 44px targets, no horizontal document overflow.
- One h1, ordered headings, table headers, persistent labels, textual states and
  visible focus. Confirmation follows impact evidence in DOM order, no sticky
  obstruction. Errors remain near their region. Themes preserve review context;
  support reduced motion and scoped RTL.
- Actions retain original POST forms/CSRF/button names and destinations. Plan
  changes retain hidden fields, existing guards and exact confirmation submit.
  No auto-submit, AJAX replacement, automatic retry, new confirmation ceremony
  or changed redirect/provider behavior.

## Shared impact and protected work

`businesses/subscription.html` serves Logistics owners too; Logistics admin usage
renders `businesses/logistics_usage.html`. Integration must explicitly select
Services presentation and preserve Logistics annual messaging, usage includes,
admin usage, disabled portals and asset loading. Shared shell, public pricing,
shared plan-feature include and Stripe sources are excluded. Both verticals need
regression evidence because the entry template is shared.

Initial branch: `experiment/motionmate-ui-redesign`; HEAD
`6d65bc4d5e80f772e1822572f8ee20b4686fd7da`; worktree initially clean. Preserve
Clients/Invoices implementations/workflows/evidence, ignored Phoenix and frozen
references. `source-audit.json` is an audit hash snapshot, not a frozen Django
BEFORE or Gate B baseline.

## Validation limits and deferred decisions

`validation.md` plans owner/non-owner, effective-state, plan-change, quota,
Stripe availability, CSRF, responsive/theme/accessibility and Logistics checks.
**Existing preview guard blocks subscription/plan writes and `/billing/` routes**
(`scripts/ui_preview/guard.py:88–129`). `--route` changes a destination, not that
capability or the dashboard-specific validator.

After A, B must identify verified owned disposable PostgreSQL resources and
appropriate test/fixture coverage for local confirmation and mocked provider
requests while retaining network/financial guards. Separately authorized isolated
Django tests can verify subscription state; blocked interactive actions must be
reported unavailable, never passed. Required real-Django form coverage must be
resolved before validation is complete; mocks alone do not prove browser behavior.
No weakening guards or live Stripe test is implied.

No Django initialization, runtime/database/provider access, fixture, migration,
browser, source capture or data-writing test ran. After B, freeze actual working
tree BEFORE, implement approved files, validate and present one real Django
BEFORE/AFTER review for this module. No standalone prototype is required.

Defer provider plan migration, financial policy, proration, cadence/currency,
price configuration, checkout/webhooks, quota rules, FREE_TEST policy, admin
permissions and all record changes. Existing booking help and unconditional
plan-feature wording may lag module flags. Preserve authoritative values/guards;
do not resolve this through public shared-copy or booking-behavior changes.

## Gate A decision

Approve **Services Subscriptions & Billing v1**: status/available billing action
first, compact authoritative usage, clearer comparison and adjacent existing
impact review, including visible existing server errors. Approval is limited to
this module's presentation, excluding functional/provider decisions. Artifact
hashes/scope-bound identity are in `state.json` and offline check output. Approval
fields remain null. After A prepare exact integration, risks, baseline and
concrete resources; stop at B. A authorizes neither implementation nor Stripe work.
