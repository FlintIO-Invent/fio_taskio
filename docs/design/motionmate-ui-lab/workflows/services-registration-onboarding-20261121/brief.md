# Services Registration & Onboarding — design direction v1

Full Redesign · Motionmate Services · Gate A pending

Primary route: `/accounts/register-business/`. Related surfaces: public Services
pricing, private Services registration, checkout return/recovery, dashboard
welcome and Setup Guide. Modernize the existing journey's presentation without
changing registration, subscription, token, financial or tenant policy.

## Scope, authorization and evidence

The user requested “Automatically complete the audit and design planning” and
“Stop at Gate A for design-direction approval.” This authorizes these saved
planning records. It does not authorize production edits, fixtures, runtime
setup, database access, migrations, providers, dependencies or release actions.

The [Django source audit](audit.md) traces actual routes/forms/services/templates,
branching, consumers and side effects. [Source identities](source-audit.json)
record the clean initial branch/HEAD, tracked-workspace digest and protected
sources/references. This is a source-based design proposal, not a browser audit
or interactive BEFORE. That review remains a post-B prerequisite to edits.

## Design direction and screen composition

Use the existing Motionmate mark, local licensed Manrope, restrained indigo
actions, quiet surfaces, navy dark surfaces and legible labels. Keep the work
visible, avoiding decorative illustrations, gradients and ornamental progress.
Production remains Phoenix 1.23.0/Bootstrap; public pricing stays within Silicon.
Tailwind/DaisyUI do not enter either runtime shell.

### 1. Services pricing and plan selection

Refine the existing `#pricing` section only: concise heading, pricing-region
choice, monthly/yearly control and three equal plan comparisons from active
server rows. Each shows plan name/description, explicit currency and actual
monthly amount or annual total, allowance rows, existing recommended state and
its existing Start trial link. Keep owner-inclusive users, shared appointment
allowance, invoice allowance and unlimited/finite client semantics truthful.

Give common included features one compact area using the existing include.
Use neutral **Yearly billing**, without the hard-coded “2 months free” claim.
No calculated savings, invented “best value,” trial extension or quota edits.
Keep `#pricing`, `pricing-billing-toggle`, `data-bs-toggle="price"`, price/period
hooks and registration URL datasets synchronized. Query `plan`, `interval`,
`currency` and session currency behavior stay unchanged. Currency navigation
still reloads the existing monthly initial state; show the current choice
without promising unimplemented cross-navigation persistence.

Desktop uses three comparisons; tablet wraps at current theme breakpoints;
mobile stacks complete content and full-width links. Express shared identity
through scoped type, spacing and colors. Preserve the public theme, navigation,
hero, footer and other site sections.

### 2. Business registration and account creation

One page, one existing form, one **Create workspace** submit. Use a compact
Motionmate Services header, **Create your Services workspace** h1 and plain
explanation of the owner account. Sign in, staff access and home links keep
current routes. Do not introduce a multi-step wizard or account-type selector.

Desktop composition:

```text
Motionmate Services                                  Existing sign-in link
Create your Services workspace
Existing messages / linked error summary when invalid

Your account and business (wide)       Your plan (narrow; inside same form)
  Owner first / last name               Selected plan · existing recommendation
  Owner login email + visible help      Supplied amount · USD/EUR · month/year
  Business name / business email        Existing trial/access explanation
  Business location + currency help     [Change selection: existing disclosure]
  Password / confirm + visible rules       Plan choices
                                           Monthly / Yearly
                                           International/USD · Europe/EUR
  [Create workspace]                    Location correction / existing errors
  Existing sign-in / staff links
```

Use semantic groups and natural reading/tab order; no duplicate fields or
separate sidebar form. The summary is quiet and distinct from editable inputs.
Changing plan/billing/currency uses the existing local editor, preserving entered
registration details. Keep existing IDs, field names, radio values and
`data-registration-*`, `data-plan-*`, `data-focus-business-location` hooks.
Use server-supplied prices only.

On tablet/mobile place the plan summary/editor in the same reading order before
submission, with all fields/actions reachable at 320px. No sticky overlay hiding
errors, repeated submit or forced account recreation.

### 3. Billing, location and private access

Show **per month** for monthly and **per year / billed yearly** for the supplied
annual total. Display USD/EUR beside the amount. Describe this as the Motionmate
subscription currency; workspace invoice defaults remain in Business Settings.
Keep country free text and server validation; do not auto-switch currency while
typing or introduce a new country classification.

Payment/trial help must reflect the existing server branch: standard signup with
Stripe requires payment setup; local pilot trials go directly to the dashboard;
selected Beta/private free-test access must not imply card collection or paid
renewal. If necessary propose a presentation-only projection of the existing
branch at Gate B. It must not change handoff logic, defaults, trial start,
subscriptions or persistence.

Services free-test shows the fixed server-selected tier and existing no-payment
access explanation, keeping the hidden plan. Beta retains its bound selector,
including current public-plan options/default behavior; do not force Beta or
create a new paid signup process. Token checks, flags, reusable links and
existing private subscriptions remain unchanged. Logistics free-test keeps its
current presentation unchanged.

### 4. Validation and error recovery

Keep server validation authoritative and `novalidate` semantics. Put a concise
linked summary above the form and full existing errors beside each field;
associate help/errors with inputs and focus the summary after invalid submission.
Show owner-vs-business email guidance and password requirements visibly. Do not
replace Django validation with a browser password score or extra rules.

Open the selection disclosure for its errors or the existing country/currency
correction. Missing/invalid selection stays visibly unselected until corrected;
do not conceal rejection with a guessed plan/price. Make native selection usable
before JavaScript enhancement. Preserve payloads and bound values; do not
navigate to pricing to correct a draft. After a server error retain non-secret
values and explain required password re-entry. Selection changes on the current
page must preserve even unsaved password input.

### 5. Checkout entry and return

Registration continues to its existing server-selected destination. Stripe's
hosted interface remains external and unchanged. No extra interstitial, card
form, provider branding claim or simulated hosted payment UI.

Style Services returns as state-first results with saved workspace/plan/interval/
currency context, concise explanation and the existing guarded next action:

| Existing server state | Proposed presentation | Preserved action |
| --- | --- | --- |
| Pending confirmation | **Confirming your subscription**; access not yet confirmed, no payment assertion based on URL. | Resume only when `can_resume_checkout`; other navigation remains guarded. |
| Trialing with access | **Your 14-day trial is active**, according to existing state. | Open dashboard when allowed. |
| Active with access | **Your subscription is active**. | Open dashboard when allowed. |
| Attention/no subscription/no access | **Subscription needs attention** with truthful available context. | Existing guards only; no fabricated billing action. |
| Cancelled/setup failure | **Payment setup paused**; account/workspace saved; continue existing workspace. | Existing CSRF-protected Resume payment setup POST when allowed. |

Keep `can_resume_checkout` precedence over dashboard entry, all messages and
sign-out. No polling, automatic retry, client-side activation, status mutation
or trust in return parameters. Do not invent a price from a stored interval or
treat a checkout return as customer-invoice settlement.

### 6. First-time welcome and Setup Guide

Refine the existing Services modal/offcanvas in the existing dashboard. Preserve
already redesigned dashboard content/navigation and other screens. Welcome
uses **Welcome to Motionmate Services**, the three existing journey choices,
short purpose, current task list, factual completed count and existing Start/
Continue/Review controls. Keep every choice; no automatically saved default.

The guide places selected journey and **Step n of m** first, actual completion
as separately labeled information, then one current task and its effective CTA.
Follow with current journey task states and other journeys. Keep Back, Next,
Skip for now, Finish, Continue later and explicit close POST semantics,
missing-target guidance, prerequisites, locks and completed states. Do not label
step position as completion or treat Skip/Finish as work done.

Keep modal/guide/title IDs, hidden action/step keys, auto-show/reopen rules,
Bootstrap lifecycle, static guide backdrop, disabled Escape dismissal and
desktop spotlight hooks. Mobile stacks welcome choices and uses existing guide
behavior; no new spotlight/tour engine. Setup actions open existing Settings,
Services, Availability, Clients, Appointments and Invoices screens; their forms
are not copied into onboarding. Preserve existing users' state without reset.

`/businesses/setup/` without a Business remains the membership-required fallback.
It cannot be reliably classified as Services there; preserve its shared notice
and redirects. No invented self-service workspace attachment.

## Responsive, themes and accessibility

Follow the [design system](../../../motionmate-design-system/DESIGN.md),
[components](../../../motionmate-design-system/COMPONENTS.md) and
[vertical boundaries](../../../motionmate-design-system/VERTICALS.md). Reuse
local Manrope WOFF2/OFL and the unchanged logo. The present read-only Phoenix
split-auth/pricing references supply native grid/form patterns; do not import
their social login, terms fields, sample prices or wizard process.

Use 4px spacing increments, 20–24px sections, 12px panels/8px controls, 32px
desktop/28px mobile page title, 20px section headings, 14px labels/help, 16px
inputs/mobile body and at least 44px action targets. Use scoped semantic tokens,
without global Phoenix breakpoint/token changes. Public pricing uses existing
Silicon theme hooks; authenticated surfaces keep Phoenix preferences and asset
order. Never mix their theme CSS.

Both themes retain identical information/controls. Verify 390/768/1440px, 320px
reflow, zoom, RTL, long names/emails/prices/errors, keyboard/error navigation,
contrast, reduced motion and overlay scroll/close. Use native fieldsets/radios,
persistent labels, one page h1, named dialogs/landmarks and textual states. No
design claim here establishes rendered accessibility conformance.

## Preservation, deferred decisions and next gate

Protect Logistics signup/enrollment, free-test, checkout, onboarding and all
role/module/subscription/location rules and records. Scope Services compositions
from existing context; shared consumers need both verticals' regressions. Keep
completed Services redesigns and current Team/Settings candidates/evidence.
Do not alter shared parents/theme bundles or allowance sources as a shortcut.

New plans/prices/currencies/taxes, private-access defaults/expiry, trials,
activation/webhook/checkout policy, signup retry architecture, task definitions/
completion, new setup fields/routes, email verification, invitations, provider
configuration, yearly persistence across public region navigation, invoice
defaults, data/schema and release actions remain separate work.

After A prepare the exact Gate B manifest, impact assessment, current working-
tree/file baselines and disposable PostgreSQL/test/browser scope. Current preview
guards block registration subscription writes and checkout routes; resolve a
concrete isolated validation approach without weakening shared financial/network
guards or contacting providers. See [validation.md](validation.md).

After B freeze the actual working tree BEFORE before edits; implement approved
files; validate; refresh AFTER alone; present one real Django BEFORE/AFTER pair
and stop at Gate C. No standalone prototype is needed.

Approve **Services Registration & Onboarding v1**: grouped single-page signup,
editable plan summary, truthful billing/currency/private access, state-first
checkout recovery and focused existing welcome/guide. Approval authorizes
preparing Gate B only. Exact artifact hashes and scope-bound design identity
are in `state.json` and [gate-a-review.md](gate-a-review.md).
