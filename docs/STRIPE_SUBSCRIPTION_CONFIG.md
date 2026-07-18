# Stripe Subscription Configuration

Motionmate includes the official Stripe Python SDK and local configuration checks for future subscription Checkout work. This foundation does not activate Checkout, collect payment methods, redirect to Stripe, create Stripe customers, create Stripe subscriptions, or process webhooks.

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

When disabled, missing Stripe credentials and Price IDs do not block local development, migrations, static collection, or unrelated tests. Future Stripe-specific actions should remain unavailable until `STRIPE_ENABLED=true` and configuration checks pass.

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
