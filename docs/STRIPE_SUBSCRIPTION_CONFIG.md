# Stripe Subscription Configuration

Motionmate includes the official Stripe Python SDK, local configuration checks, and Stripe-hosted Checkout setup for paid-plan registration. Checkout creates a local pending subscription and redirects the owner to Stripe when enabled. Return URLs are informational only; webhooks are still required before a workspace becomes trialing or active.

## Install Dependencies

Use the normal project dependency workflow:

```bash
uv sync --extra dev
```

The official `stripe` Python package is installed from `pyproject.toml` and locked in `uv.lock`.

## Enablement

Stripe subscription billing is disabled by default:

```env
STRIPE_ENABLED=false
```

When disabled, missing Stripe credentials and Price IDs do not block local development, migrations, static collection, or unrelated tests. Paid-plan registration keeps the local pilot flow: a local 14-day trial is created, the owner is logged in, and no Stripe API call is made.

## Credentials

Use Stripe test credentials in development and staging:

```env
STRIPE_ENABLED=true
STRIPE_PUBLISHABLE_KEY=pk_test_replace_me
STRIPE_SECRET_KEY=sk_test_replace_me
STRIPE_WEBHOOK_SECRET=whsec_replace_me
STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID=bpc_replace_me
SUBSCRIPTION_PAYMENT_GRACE_DAYS=7
```

Production must use live keys:

```env
STRIPE_PUBLISHABLE_KEY=pk_live_replace_me
STRIPE_SECRET_KEY=sk_live_replace_me
```

Do not mix test and live keys. Do not commit real Stripe secrets. Store real values only in the deployment environment.

## Customer Portal

Motionmate uses Stripe's hosted Customer Portal for owner-only subscription billing management. The portal is available only for valid Stripe-backed Motionmate subscriptions with local `trialing` or `active` access.

Create a dedicated Stripe Customer Portal configuration in the Stripe Dashboard for each Stripe mode you use. Test mode and live mode have separate `bpc_...` configuration IDs. Configure the Motionmate environment with the matching ID:

```env
STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID=bpc_replace_me
```

Initial portal configuration:

- Payment-method updates: enabled
- Invoice history: enabled
- Subscription cancellation: enabled only if commercially approved
- Subscription plan updates: disabled
- Quantity changes: disabled
- Promotion codes: disabled

Do not enable switching between Starter, Pro, Business, monthly, yearly, EUR, or USD in this portal configuration. Future plan-change behavior must be implemented deliberately through Motionmate's local Price mapping and webhook architecture.

The portal route is owner-only and creates a new Stripe Portal Session on POST. Motionmate uses the local subscription's stored Stripe customer ID and a server-generated return URL; it never accepts customer IDs, configuration IDs, or return URLs from browser input.

## Payment Failure Grace

Motionmate uses a provider-neutral access grace period when Stripe confirms a subscription is `past_due`:

```env
SUBSCRIPTION_PAYMENT_GRACE_DAYS=7
```

The value defaults to 7 days and must be a whole number from 0 to 30. `0` means no grace access. Starter, Pro, and Business use the same policy.

The first verified `invoice.payment_failed` webhook, or a verified `customer.subscription.updated` webhook that reports `past_due`, starts the current delinquency episode from the Stripe event timestamp. Motionmate stores `past_due_since` and `grace_period_ends_at` on the subscription. Additional failed-payment webhooks update only the latest operational failure timestamp; they do not extend grace.

During grace, the selected plan continues to control access and limits. After `evaluation_time >= grace_period_ends_at`, a valid Stripe-backed public paid subscription enters restricted read-only access until a verified Stripe recovery webhook arrives.

Owners can use the hosted Stripe Customer Portal recovery action to update payment information during or after grace expiry. Returning from the Portal is informational only and does not recover access. Motionmate clears the current delinquency only after `invoice.paid` or a newer valid subscription webhook confirms `active` or `trialing` state. Cancellation and terminal provider states clear the current grace fields and follow the existing no-access rules.

Stripe retry timing is configured separately in the Stripe Dashboard. Motionmate's grace period does not guarantee Stripe will retry payment on a specific date, is not a new free trial, and does not send dunning emails in this block.

## Workspace Access Modes

Subscription access is derived locally and has three explicit modes:

- `full`: the workspace can be viewed and modified according to the selected plan, role permissions, and module gates.
- `restricted`: the workspace can be viewed, but operational writes are blocked.
- `none`: the workspace is unavailable except for owner subscription recovery routes.

Restricted mode is available only for provider-backed Stripe subscriptions on public paid plans with valid local Stripe identity fields and valid past-due grace timestamps. Beta subscriptions, manual/internal subscriptions, missing grace state, malformed grace state, cancelled subscriptions, unpaid public subscriptions without Stripe identity, and plan/provider mismatches fail closed to `none` or follow their pre-existing access behavior.

Access evaluation must not call Stripe, update database rows, send notifications, create sessions, or mutate local state. Browser return URLs from Checkout or the Customer Portal remain informational; only signed Stripe webhooks can restore full access after payment recovery.

Use the central guards for new business routes:

```python
@business_module_required("client_management", access="read")
@business_module_required("client_management")
@business_workspace_access_required(access="read")
@business_workspace_access_required()
```

`read` allows restricted workspaces to view plan-included data. `write` is the default and requires full access. Every new route that reads or mutates business data should declare the intended access level explicitly, then continue to enforce role permissions and object ownership as usual.

Restricted access behavior:

| Area | Restricted mode |
| --- | --- |
| Dashboard and existing CRM data | View allowed |
| Existing clients, service requests, appointments, invoices, invoice PDFs, services, and team list | View allowed when plan and role allow |
| Create, edit, archive, delete, convert, import, upload, email/send, status changes, onboarding writes, invitation acceptance, team mutations, settings mutations, and plan changes | Blocked |
| Public request and public booking forms | Neutral unavailable page; no records are created |
| Owner subscription and payment recovery | Allowed |
| Non-owner recovery messaging | Neutral read-only messaging without payment controls |

## Subscription Notification Outbox

Motionmate stores owner-facing SaaS billing email intent in `SubscriptionNotification` rows. Stripe webhook processing only synchronizes local subscription state and creates deduplicated outbox records; it does not send email. SMTP or email-backend failure cannot roll back Stripe webhook state, extend grace, clear grace, restore access, or make the webhook fail solely because delivery failed.

The outbox fields include the local business, local subscription, recipient owner email/user, notification type, unique deterministic deduplication key, status, availability time, attempt counters, delivery timestamps, safe last-error summary, source provider event ID, and a minimal safe `context_summary`. It does not store raw webhook payloads, card details, bank details, Stripe payment-method objects, transient Portal URLs, or provider customer/subscription/price IDs in renderable context.

Supported notification types:

- `trial_started`
- `subscription_activated`
- `payment_grace_started`
- `payment_recovered`
- `cancellation_scheduled`
- `subscription_cancelled`
- `trial_ending_3_days`
- `trial_ending_1_day`
- `payment_grace_ending_1_day`
- `restricted_mode_started`

Supported statuses:

- `pending`
- `processing`
- `sent`
- `failed`
- `cancelled`

Deduplication keys are server-generated from the local subscription, notification type, relevant billing episode or provider transition date, and a deterministic recipient key. Duplicate Stripe event delivery and repeated provider updates for the same transition reuse the existing row instead of resetting delivery history.

Recipient selection uses active local `BusinessUser` owner memberships only. Staff, admins, accountants, viewers, inactive users, inactive memberships, other workspaces, Stripe customer email, browser input, and customer invoice recipients are not used as fallbacks. If no active owner recipient exists, Motionmate creates a failed operationally visible outbox row with a safe error summary and still lets webhook processing succeed.

Webhook transitions that enqueue notification intent:

| Local transition | Notification |
| --- | --- |
| `pending_checkout` to `trialing` | `trial_started` |
| `pending_checkout` or `trialing` to `active` | `subscription_activated` |
| first current-episode transition into `past_due` with newly initialized `past_due_since` | `payment_grace_started` |
| `past_due` to `active` or `trialing` | `payment_recovered` |
| `cancel_at_period_end` changes from false to true on an active/trialing subscription | `cancellation_scheduled` |
| `trialing`, `active`, or `past_due` to `cancelled` | `subscription_cancelled` |

Time-based reminder discovery is separate from delivery and uses only local, timezone-aware subscription data. It makes no Stripe API calls, sends no email, and does not mutate subscription status, trial dates, grace dates, or access mode.

Reminder windows:

| Local state | Reminder | Due window |
| --- | --- | --- |
| Stripe-backed public paid `trialing` subscription | `trial_ending_3_days` | `24 hours < trial_end - evaluation_time <= 72 hours` |
| Stripe-backed public paid `trialing` subscription | `trial_ending_1_day` | `0 < trial_end - evaluation_time <= 24 hours` |
| Stripe-backed public paid `past_due` subscription with full grace access | `payment_grace_ending_1_day` | `0 < grace_period_ends_at - evaluation_time <= 24 hours` |
| Stripe-backed public paid `past_due` subscription with central access mode `restricted` | `restricted_mode_started` | `evaluation_time >= grace_period_ends_at` |

Boundary and catch-up policy:

- At exactly `evaluation_time == trial_end`, trial-ending reminders are stale and are not enqueued.
- At exactly `evaluation_time == grace_period_ends_at`, the grace-ending reminder is stale; restricted-mode entry is evaluated instead.
- Missed three-day trial reminders are not backfilled during the one-day window.
- Missed trial reminders are not enqueued after the trial ends.
- Missed grace-ending reminders are not enqueued after grace ends.
- Restricted-mode notifications may be caught up later while the subscription remains `past_due` and the central derived access mode remains `restricted`.
- Trial reminders are skipped when local Stripe-synchronised state says cancellation at period end prevents the first paid renewal; Motionmate does not send automatic-renewal wording in that state.

Reminder deduplication uses the existing outbox key architecture. The relevant deterministic contexts are:

- `trial_ending_3_days:{trial_end}`
- `trial_ending_1_day:{trial_end}`
- `payment_grace_ending_1_day:{past_due_since}:{grace_period_ends_at}`
- `restricted_mode_started:{past_due_since}:{grace_period_ends_at}`

The recipient identity remains part of the final deduplication key, so different owner recipients can receive separate rows while repeated command runs, execution-time changes, sent rows, and failed rows do not create duplicates for the same milestone.

Discover due reminders manually:

```bash
uv run --no-sync python src/manage.py enqueue_subscription_reminders
```

Useful options:

```bash
uv run --no-sync python src/manage.py enqueue_subscription_reminders --dry-run
uv run --no-sync python src/manage.py enqueue_subscription_reminders --limit 100
uv run --no-sync python src/manage.py enqueue_subscription_reminders --at 2026-08-01T12:00:00+00:00
uv run --no-sync python src/manage.py enqueue_subscription_reminders --type trial_ending_1_day
```

`--at` must be an aware ISO-8601 datetime. `--limit` bounds candidate subscriptions evaluated in deterministic primary-key order. `--dry-run` evaluates candidates and reports what would be created without creating rows, changing status, incrementing counters, sending email, or calling Stripe.

Deliver pending notifications manually:

```bash
uv run --no-sync python src/manage.py send_subscription_notifications
```

Useful options:

```bash
uv run --no-sync python src/manage.py send_subscription_notifications --limit 25
uv run --no-sync python src/manage.py send_subscription_notifications --dry-run
uv run --no-sync python src/manage.py send_subscription_notifications --retry-failed
```

The command processes eligible `pending` rows with `available_at <= now` in deterministic order. `--retry-failed` explicitly includes failed rows. `--dry-run` reports work without sending email or changing rows. Reminder delivery performs a relevance check before sending: obsolete trial, grace-ending, and restricted-mode reminder rows are marked `cancelled` with a safe reason instead of being delivered after activation, recovery, effective cancellation, changed milestones, invalid provider identity, or changed access mode.

Intended future operational sequence:

```text
1. Run enqueue_subscription_reminders
2. Run send_subscription_notifications
```

Production scheduling is not configured in this block. There is no Celery worker, Celery Beat schedule, cron entry, Heroku Scheduler configuration, platform scheduler, Stripe polling, customer invoice reminder, appointment reminder, SMS, push notification, or marketing campaign.

Recipient-facing dates are displayed in the business timezone when `Business.timezone` is valid. If it is not valid, Motionmate falls back to the project `TIME_ZONE`, then UTC. Email dates include both time and a timezone label. The timezone is never inferred from Stripe metadata, email domains, IP addresses, browser state, or webhook headers.

Beta remains excluded from reminder candidate queries and creates no reminder outbox rows. Customer invoice emails and appointment emails remain separate flows and are not affected by subscription reminder discovery.

## Price IDs

Motionmate plan names, displayed prices, regional pricing, features, and limits remain database-backed. Stripe Price IDs are deployment configuration that connect each public Motionmate plan and billing option to a separately created Stripe Price.

Each plan, billing interval, and currency needs its own Stripe Price ID. Do not reuse one Stripe Price ID for different amounts, currencies, plans, or billing intervals.

Supported public combinations:

```env
STRIPE_PRICE_STARTER_MONTHLY_USD=price_replace_starter_monthly_usd
STRIPE_PRICE_STARTER_YEARLY_USD=price_replace_starter_yearly_usd
STRIPE_PRICE_STARTER_MONTHLY_EUR=price_replace_starter_monthly_eur
STRIPE_PRICE_STARTER_YEARLY_EUR=price_replace_starter_yearly_eur
STRIPE_PRICE_PRO_MONTHLY_USD=price_replace_pro_monthly_usd
STRIPE_PRICE_PRO_YEARLY_USD=price_replace_pro_yearly_usd
STRIPE_PRICE_PRO_MONTHLY_EUR=price_replace_pro_monthly_eur
STRIPE_PRICE_PRO_YEARLY_EUR=price_replace_pro_yearly_eur
STRIPE_PRICE_BUSINESS_MONTHLY_USD=price_replace_business_monthly_usd
STRIPE_PRICE_BUSINESS_YEARLY_USD=price_replace_business_yearly_usd
STRIPE_PRICE_BUSINESS_MONTHLY_EUR=price_replace_business_monthly_eur
STRIPE_PRICE_BUSINESS_YEARLY_EUR=price_replace_business_yearly_eur
```

## Public Pricing Regions

Public pricing has two explicit regions:

- International/USD for businesses outside Europe.
- Europe/EUR for businesses registered in Europe, including country names such as `Netherlands`, `Germany`, and `France`, plus common country codes such as `NL`, `DE`, and `FR`.

The pricing page selector stores only the safe session value `motionmate_pricing_currency`, with allowed values `usd` and `eur`. Pricing links carry the same value as `currency=usd` or `currency=eur` into registration, and valid links override an older session value. Invalid currency values are ignored on GET and rejected on POST.

Motionmate does not infer public pricing from IP address, VPN location, browser locale, timezone, language, Accept-Language headers, email domain, Stripe metadata, or webhook headers.

Registration remains server-authoritative. A Europe business must submit Europe/EUR pricing, and a non-Europe business must submit International/USD pricing before any user, business, or subscription is created. After signup, `BusinessSubscription.billing_currency` is authoritative for Checkout, webhook processing, and billing state; the pre-signup session key must not be used to change an existing subscription.

Beta is an internal non-trial plan and is not part of the public Stripe Price mapping.

## Validation

Run system checks with Stripe disabled:

```bash
uv run --no-sync python src/manage.py check
```

Run checks with fake-but-shaped test values when validating configuration wiring:

```bash
STRIPE_ENABLED=true \
STRIPE_PUBLISHABLE_KEY=pk_test_replace_me \
STRIPE_SECRET_KEY=sk_test_replace_me \
STRIPE_WEBHOOK_SECRET=whsec_replace_me \
STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID=bpc_replace_me \
SUBSCRIPTION_PAYMENT_GRACE_DAYS=7 \
STRIPE_PRICE_STARTER_MONTHLY_USD=price_starter_monthly_usd \
STRIPE_PRICE_STARTER_YEARLY_USD=price_starter_yearly_usd \
STRIPE_PRICE_STARTER_MONTHLY_EUR=price_starter_monthly_eur \
STRIPE_PRICE_STARTER_YEARLY_EUR=price_starter_yearly_eur \
STRIPE_PRICE_PRO_MONTHLY_USD=price_pro_monthly_usd \
STRIPE_PRICE_PRO_YEARLY_USD=price_pro_yearly_usd \
STRIPE_PRICE_PRO_MONTHLY_EUR=price_pro_monthly_eur \
STRIPE_PRICE_PRO_YEARLY_EUR=price_pro_yearly_eur \
STRIPE_PRICE_BUSINESS_MONTHLY_USD=price_business_monthly_usd \
STRIPE_PRICE_BUSINESS_YEARLY_USD=price_business_yearly_usd \
STRIPE_PRICE_BUSINESS_MONTHLY_EUR=price_business_monthly_eur \
STRIPE_PRICE_BUSINESS_YEARLY_EUR=price_business_yearly_eur \
uv run --no-sync python src/manage.py check
```

Checks are local only. They do not contact Stripe or verify that a Price exists remotely.

## Checkout Boundaries

With `STRIPE_ENABLED=true`, normal paid-plan registration records a `pending_checkout` subscription and creates a Stripe Checkout Session outside the registration transaction. The Checkout Session uses subscription mode, a 14-day trial, the configured Price ID for the selected plan, interval, and regional currency, and metadata linking the Stripe session to the local business, subscription, and owner.

Checkout never trusts browser-submitted Price IDs, amounts, trial settings, customer IDs, subscription IDs, tax settings, coupons, or provider metadata. The Price ID is resolved from the local `BusinessSubscription` plan, interval, and `billing_currency` against the configured `STRIPE_PRICE_*` matrix.

The Checkout success and cancelled return pages do not activate access. Customer Portal returns also do not update local state. Activation, trial dates, Stripe customer IDs, cancellation, and remote subscription state belong to signed Stripe webhook processing. Beta registration remains internal and does not create a Stripe Checkout Session or Customer Portal Session.

## Local Access Reconciliation

Motionmate access checks are local and time-aware. They do not call Stripe. A Stripe-backed active subscription must have a current local provider period that has not ended, and a trialing subscription must have a future `trial_end`.

The local reconciliation command can be run manually or scheduled later:

```bash
uv run --no-sync python src/manage.py reconcile_subscription_access
```

Preview changes without writing:

```bash
uv run --no-sync python src/manage.py reconcile_subscription_access --dry-run
```

The command is idempotent and does not call Stripe, send email, delete records, or create new trials. It can safely mark expired local trials as `expired` and completed scheduled cancellations as `cancelled`. Stripe-backed expired trials and stale provider periods are reported for reconciliation instead of inventing a provider status locally.
