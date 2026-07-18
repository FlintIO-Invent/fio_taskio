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
