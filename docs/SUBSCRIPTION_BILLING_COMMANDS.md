# Subscription Billing Command Reference

All commands below are repository-local and should be run from the project root. Use test credentials, fake placeholders, or local SQLite overrides unless you are intentionally validating a secured deployment environment.

## Check Configuration

```bash
uv lock --check
uv run --no-sync python src/manage.py check
uv run --no-sync python src/manage.py makemigrations --check --dry-run
```

Validate Stripe-enabled wiring with fake shaped values:

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

## Fresh Local Migration Check

```bash
DATABASE_URL= DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/fio_taskio_fresh.sqlite3 \
uv run --no-sync python src/manage.py migrate --noinput
```

## Reconcile Local Access

Preview only:

```bash
uv run --no-sync python src/manage.py reconcile_subscription_access --dry-run
```

Apply local reconciliation:

```bash
uv run --no-sync python src/manage.py reconcile_subscription_access
```

## Preview Reminders

```bash
uv run --no-sync python src/manage.py enqueue_subscription_reminders --dry-run
uv run --no-sync python src/manage.py enqueue_subscription_reminders --dry-run --limit 100
uv run --no-sync python src/manage.py enqueue_subscription_reminders --dry-run --at 2026-08-01T12:00:00+00:00
uv run --no-sync python src/manage.py enqueue_subscription_reminders --dry-run --type trial_ending_1_day
```

## Enqueue Reminders

```bash
uv run --no-sync python src/manage.py enqueue_subscription_reminders
uv run --no-sync python src/manage.py enqueue_subscription_reminders --limit 100
uv run --no-sync python src/manage.py enqueue_subscription_reminders --at 2026-08-01T12:00:00+00:00
```

## Preview Email Delivery

```bash
uv run --no-sync python src/manage.py send_subscription_notifications --dry-run
uv run --no-sync python src/manage.py send_subscription_notifications --dry-run --limit 25
uv run --no-sync python src/manage.py send_subscription_notifications --dry-run --retry-failed
```

## Send Pending Notifications

```bash
uv run --no-sync python src/manage.py send_subscription_notifications
uv run --no-sync python src/manage.py send_subscription_notifications --limit 25
```

## Retry Failed Subscription Notifications

```bash
uv run --no-sync python src/manage.py send_subscription_notifications --retry-failed
```

## Focused Billing Tests

```bash
DATABASE_URL= DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/fio_taskio_tests.sqlite3 \
uv run --no-sync python src/manage.py test apps.businesses.tests.SubscriptionBillingLifecycleEndToEndTests

DATABASE_URL= DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/fio_taskio_tests.sqlite3 \
uv run --no-sync python src/manage.py test \
  apps.businesses.tests.StripeConfigurationTests \
  apps.businesses.tests.StripeCheckoutServiceTests \
  apps.businesses.tests.StripeWebhookProcessingTests \
  apps.businesses.tests.SubscriptionEffectiveAccessPolicyTests \
  apps.businesses.tests.StripeCustomerPortalServiceTests \
  apps.businesses.tests.SubscriptionNotificationOutboxTests \
  apps.businesses.tests.SubscriptionNotificationDeliveryTests \
  apps.businesses.tests.SendSubscriptionNotificationsCommandTests \
  apps.businesses.tests.SubscriptionReminderDiscoveryTests \
  apps.businesses.tests.SubscriptionReminderDeliveryRelevanceTests \
  apps.accounts.tests.BusinessRegistrationViewTests \
  apps.billings.tests.BillingBusinessScopingTests
```

## Broader Relevant Suite

```bash
DATABASE_URL= DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/fio_taskio_tests.sqlite3 \
uv run --no-sync python src/manage.py test \
  apps.accounts.tests \
  apps.businesses.tests \
  apps.crm.tests \
  apps.billings.tests \
  apps.appointments.tests
```

## Full Configured Django Test Suite

```bash
DATABASE_URL= DB_ENGINE=django.db.backends.sqlite3 DB_NAME=/tmp/fio_taskio_tests.sqlite3 \
uv run --no-sync python src/manage.py test
```

Automated tests must mock Stripe SDK calls, use the Django test email backend, and avoid real Stripe or email-provider network calls.
