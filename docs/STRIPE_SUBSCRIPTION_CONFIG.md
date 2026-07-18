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
```

Production must use live keys:

```env
STRIPE_PUBLISHABLE_KEY=pk_live_replace_me
STRIPE_SECRET_KEY=sk_live_replace_me
```

Do not mix test and live keys. Do not commit real Stripe secrets. Store real values only in the deployment environment.

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

The success and cancelled return pages do not activate access. Activation, trial dates, Stripe customer IDs, and remote subscription state belong to webhook processing in the next block. Beta registration remains internal and does not create a Stripe Checkout Session.
