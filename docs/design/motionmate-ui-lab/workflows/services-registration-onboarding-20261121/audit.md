# Services Registration & Onboarding — Django source audit

Full Redesign · SERVICE · design v1 · Gate A preparation

The request authorizes saved audit, design and workflow records and requires a
Gate A stop. This audit follows the actual Django source; no Django process,
browser, settings environment, database or provider was accessed. Rendered
findings, accessibility measurements and interactive BEFORE remain pending.
Repository-relative references below identify the audited sources; exact bytes,
Git identity and protected trees are in [source-audit.json](source-audit.json).

## Existing journey and routes

| Entry / method | Current behavior and authority | Source |
| --- | --- | --- |
| `/home/#pricing`, `/site-preview/#pricing`, GET | Same `motionmate_pricing_context`; active SERVICE Starter/Pro/Business rows; USD/EUR query selection stored in session. Silicon public theme. Monthly/yearly display and signup links synchronize in JavaScript. | `src/taskio/urls.py:45`, `src/templates/public_site/home.html:2463` |
| `/accounts/register-business/`, GET/POST | `register_business → _register_business → BusinessRegistrationForm`. Query `plan`, `interval`, `currency`; POST `plan`, `billing_interval`, `pricing_currency`. Defaults Pro/monthly/USD subject to session and active-plan fallback. Same-route form POST with CSRF. | `src/apps/accounts/urls.py:96`, `src/apps/accounts/views.py:231`, `src/apps/accounts/forms.py:163` |
| `/accounts/register-business/beta/<token>/`, GET/POST | Flag, constant-time configured-token check and active beta row admit the private route. Existing selector includes active public plans plus Beta; merely arriving here does not force Beta selection. Invalid/disabled access redirects to standard registration. | `src/apps/accounts/views.py:239`, `src/apps/accounts/beta_registration.py`, `src/apps/accounts/forms.py:296` |
| `/accounts/free-test/<tier>/<token>/`, GET/POST | Flag, tier-specific token and eligible plan queryset admit the route. Selected tier is server-fixed; tampering rejected. Services and Logistics use this shared form/template. | `src/apps/accounts/views.py:254`, `src/apps/accounts/free_test_registration.py`, `src/apps/accounts/forms.py:375` |
| `/billing/checkout/success/`, `/billing/checkout/cancelled/`, GET | Current active Business, owner role and local effective subscription access determine presentation. Success URL and `session_id` do not activate access or prove payment. Shared with Logistics. | `src/apps/businesses/views.py:93`, `src/apps/businesses/utils.py:125`, `src/templates/businesses/checkout_status.html` |
| `/billing/checkout/resume/`, POST only | Owner/current Business guard. Services requires pending checkout and public plan; existing session validation/reuse/replacement and error handling. Logistics delegates to its approved enrollment flow. | `src/apps/businesses/views.py:151`, `src/apps/businesses/stripe_checkout.py:163` |
| `/crm/agent/dashboard/`, GET/POST | Business membership, subscription access and vertical branch precede the dashboard. Pending Services owners return to payment setup. Owner/admin onboarding uses persisted user/Business state and existing task projections. | `src/apps/crm/urls.py`, `src/apps/crm/views.py:587`, `src/apps/businesses/onboarding.py:629` |
| `/businesses/setup/`, GET | Existing Business redirects to Business Settings. Without a Business, displays a membership/setup-required notice; it is not a business-creation wizard. | `src/apps/businesses/views.py:347`, `src/templates/businesses/setup_required.html` |

Business login, staff login, password recovery, employee invitation acceptance,
legacy customer-registration redirect and the already redesigned Settings,
Catalogue, Appointments, Clients, Invoices, Imports, Team and Subscription pages
are downstream consumers/boundaries. Their own screens and behavior stay intact.
Invitation acceptance can expire an invitation on GET
(`src/apps/accounts/views.py:556`); it is not a safe ordinary-database audit URL.

## Registration and creation contracts

The eleven fields are `first_name`, `last_name`, `email`, `business_name`,
`business_email`, `country`, `plan`, `billing_interval`, `pricing_currency`,
`password1`, `password2`. Preserve Django labels, generated IDs/names, bound
non-secret values, field and non-field errors, password validators, CSRF and
server validation. Owner login email and business contact/billing email are
distinct. Emails normalize to lowercase; owner email must not already exist.
There is no new email verification, social login, terms checkbox, country
autocomplete or resume-draft endpoint.

`BusinessRegistrationForm.save` is atomic: existing custom user creation,
unique-slug Business, OWNER membership, existing subscription path and legacy
`SaaSUserProfile` compatibility updates. Standard and Services private signup
create SERVICE; Logistics free-test tiers explicitly create LOGISTICS plus its
profile. Do not reinterpret profile defaults or add tenant creation elsewhere.
Passwords are intentionally not re-rendered after server validation; selection
editing on the current page should not discard any entered input.

Public GET selection fallback differs from invalid POST: unknown/inactive GET
plans may default; missing/unknown/inactive submitted plans are rejected. Billing
accepts monthly/yearly; invalid submitted choices remain server errors. Public
plans exclude Beta/internal/Logistics offerings. No new retry key or signup
idempotency mechanism exists in this form; retain existing validation and
checkout service idempotency rather than inventing either.

### Pricing, currency and allowances

`ClarivoPlan.motionmate_plans`, `attach_display_pricing`, `get_pricing_data` and
`get_display_pricing` supply values (`models.py:543–674`). Use current active
rows, descriptions, recommendation and allowance helpers. No amounts or limits
were read from an ordinary database and no production Price IDs were verified.
Migration `0035_services_allowances.py` is historical rollout source, not proof
of the ordinary runtime's current allowances and not permission to run it.

The registration form uses existing country normalization through
`pricing_region_for_business`/`uses_europe_pricing_region` to reject country and
pricing-currency mismatch. USD means International; EUR means Europe, with the
existing pricing fallback behavior. Do not infer currency by IP, browser locale
or a new country map. Do not invent conversion, taxes, savings or monthly
equivalents. Yearly displays the supplied annual total, not twelve installments.
The public page currently claims “2 months free” without deriving that claim from
each current plan; v1 should use neutral “Yearly billing” without changing prices.
Render any supplied tax note faithfully; absence is not a tax-inclusive promise.

Subscription currency is distinct from `Business.currency`, which defaults to
USD on creation. EUR signup does not set workspace invoice currency, timezone or
locale. The existing Settings screen remains the authority for those defaults.
Public currency navigation currently reloads monthly presentation; carrying the
yearly choice through that navigation would be a separate behavior change.

### Subscription / checkout branches

| Branch | Existing result to preserve |
| --- | --- |
| Standard, Stripe disabled | Existing local 14-day trial helper, login, active Business in session, dashboard. Local trial creation does not persist selected interval/currency as a Stripe contract. |
| Standard, Stripe enabled | Save account/workspace first; login and resolve Business; ensure pending subscription; create Stripe-hosted subscription session outside the registration transaction. Card collection is required by existing payload; trial length comes from offering policy. |
| Checkout unavailable/fails | Keep created workspace; safe message; cancelled/setup page; existing owner POST resumes this Business rather than registering another. |
| Valid Beta route with Beta selected | Active BETA provisioning, no trial deadline/Stripe handoff. The private route also permits public plan selection; retain existing behavior without a new default or checkout policy. |
| Valid Services free-test | Fixed eligible tier, active LOCAL/FREE_TEST subscription, no card/Stripe call and no access deadline. |
| Logistics free-test | Existing tier eligibility, vertical/profile, annual compatibility marker and all Logistics behavior remain outside the redesign. |

`stripe_checkout.py:139–434` retains server-selected Price IDs, metadata,
client reference, trial policy, session ownership/expiry/reuse and idempotency.
`stripe_webhooks.py:223` dispatches reconciliation; return pages do not perform
it. Preserve pending, trialing, active, attention and no-subscription states,
`can_resume_checkout` precedence, `can_enter_dashboard`, POST-only resume and
sign-out. Do not add polling, automatic retries, a “mark paid” action or a fake
hosted Checkout screen. Pending return copy currently says payment method was
received although a direct GET proves no such event; v1 should state only that
confirmation is pending. Existing cancellation copy is route-based; any wider
payment-state policy remains separate.

## Existing welcome and setup guide

`onboarding.py:23–224` defines separate Services/Logistics tasks and journeys.
Services offers **Set Up My Business**, **Start Managing Clients**, **Get Booked
& Paid**. Task URLs lead to existing screens, not inline replacement forms.
Role visibility is active owner/admin membership; task locks follow existing
module checks. Server prerequisites provide an effective fallback CTA/target.
Task completion checks current tenant records; user state stores selected journey,
welcome completion/dismissal, skipped steps and last step, unique per user/Business.

`agent_dashboard` POST first requires workspace write access and recognizes:
`select_journey`, `dismiss_welcome`, `guide_step`, `skip_step`, `continue_later`,
`start_task`. Preserve `selected_journey`, `open_guide_after_select=1`,
`target_step_key`, `current_step_key` and `?setup_guide=1`. Skip is not completion;
Finish/Continue later do not create records or mark operational work done.

The modal and offcanvas are shared includes in
`src/templates/crm/agent_dashboard/agent_dashboard.html:62`. IDs:
`onboardingWelcomeModal`, `onboardingWelcomeModalLabel`, `onboardingGuidePanel`,
`onboardingGuidePanelLabel`; retain Bootstrap launch/auto-show and close POSTs.
The guide deliberately uses static backdrop/disabled Escape dismissal. Preserve
that exception and its explicit save/close actions. Desktop spotlight uses
`data-current-target-selector`, `data-onboarding-target`,
`data-onboarding-spotlight-missing` and `onboardingSpotlightFrame`; mobile has no
spotlight. Preserve shared JS and existing missing-target fallback.

There are two progress measures: actual completed-task percentage and current
step position (`_selected_journey_step_context`). Do not label navigation position
as completed work or count skipped tasks as completed. Current completion wording
for invoice send/download is based on existing checks/status evidence, not new
download telemetry or payment settlement.

## Presentation findings and shared impact

| Source finding, not a browser measurement | Proposed response |
| --- | --- |
| Narrow card interleaves owner/business/password/plan sections; h3 page title; dense small text. | Group account, business and password fields; one h1; separate but same-form plan summary. |
| Registration CSS uses gradients, hard-coded white surfaces, decorative shadows and sub-14px text. | Services-scoped Motionmate surfaces/type/themes; retain Phoenix foundation. |
| Plan editor closes by default; a country mismatch alone does not open it. | Make currency/location correction obvious; open relevant disclosure on errors. |
| Without JS a selected-plan editor stays hidden; a bad submitted plan lacks summary update targets. | Progressive enhancement with usable native fields/disclosure and honest missing selection; preserve hooks/payloads. |
| Email/password help is mostly tooltip based; errors lack a linked summary. | Visible help, linked error summary, associated errors and meaningful focus. |
| Public pricing has oversized emphasis, tiny metadata and a fixed savings claim. | Scoped, quieter comparison with explicit annual totals and dynamic allowances; preserve Silicon elsewhere. |
| Checkout combines confirmation/attention/cancel states inside a generic card. | State-first heading, saved-workspace context and existing guarded recovery action. |
| Welcome/guide repeat dense card content and small uppercase metadata. | Compact journey choice; focused current task; factual completion vs step position. |

Do not restyle `authentication_parent.html` globally: registration, checkout,
Logistics enrollment/free-test, invitation/login/password/setup screens consume
it. A Services-only child composition/scoped asset is the direction for Gate B.
The shared signup has no ordinary tenant on GET; use existing `free_test_plan`
and tier context to exclude Logistics, not a guessed active workspace.

Checkout already supplies `is_logistics`; onboarding/dashboard supplies current
Business and Services context. Shared entry files require unchanged Logistics
branches and tests in both verticals. Shared `user*.css`, `dashboard_parent`,
logo, existing dashboard/Subscriptions CSS and included-features copy should stay
unchanged. Keep completed Services designs and Team/Settings candidates intact;
current saved Team/Settings states await Gate C and are not accepted here.

## Existing coverage and runtime limitations

Inspected test sources, not executed: `accounts.tests.BusinessRegistrationViewTests`,
`PaidPlanRegistrationHandoffTests`; `businesses.tests.StripeCheckoutServiceTests`,
`CheckoutReturnViewTests`, onboarding status/visibility/state tests and public
pricing/lifecycle tests; `crm.tests.DashboardOnboardingViewTests`; Logistics
free-test tests. They cover many selection/token/currency/trial/return contracts.
Target them under later explicit disposable authorization; do not run tests
against unspecified settings. Existing copy assertions may require approved
updates, while behavioral assertions stay intact.

Current preview settings disable Stripe/free-test; middleware blocks every
`/billing/` URL, financial/subscription writes and external redirects. Default
dashboard validation does not cover this journey. A new, explicitly scoped
validation adapter is likely required at Gate B. Do not weaken shared guards to
make checkout appear functional. Real registration/local/private writes must
occur only under independently verified disposable ownership. Checkout provider
calls must be replaced only in isolated tests with clearly labeled doubles;
live Stripe, actual webhooks/email delivery and provider checkout remain unverified.

No source evidence substitutes for the one real interactive Django BEFORE/AFTER
pair required after B. [validation.md](validation.md) specifies coverage to
propose; [brief.md](brief.md) defines the v1 direction for Gate A.
