# Stripe Launch Checklist

This checklist is for Motionmate SaaS subscription billing only. It does not cover customer invoice payments, appointment payments, Stripe Connect, Stripe Tax, coupons, plan switching, seat billing, or usage billing.

Do not enable live Stripe billing until code checks, test-mode QA, external Stripe setup, email delivery, migrations, and support ownership have all been verified.

## Status Legend

- PASS: verified in the target environment.
- FAIL: verified and not working.
- NOT TESTED: not yet verified.
- EXTERNAL ACTION REQUIRED: must be completed outside this repository.

## Production Environment Variables

| Variable | Status | Notes |
| --- | --- | --- |
| `STRIPE_ENABLED` | Required in production | Set to `true` only after webhook and Price setup is complete. |
| `STRIPE_PUBLISHABLE_KEY` | Required when Stripe is enabled | Must match the Stripe mode used by the secret key. |
| `STRIPE_SECRET_KEY` | Required when Stripe is enabled | Store only in deployment secrets. |
| `STRIPE_WEBHOOK_SECRET` | Required when Stripe is enabled | Must be the signing secret for the deployed webhook endpoint. |
| `STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID` | Required when Stripe is enabled | Must be the matching `bpc_...` ID for test or live mode. |
| `SUBSCRIPTION_PAYMENT_GRACE_DAYS` | Optional | Defaults to 7. Must be a whole number from 0 to 30. |
| `MOTIONMATE_PUBLIC_BASE_URL` | Required in production | Used for email links. Use the canonical HTTPS app URL with no trailing slash. |
| `SECRET_KEY` | Required in production | Required whenever `DEBUG=False`. |
| `DEBUG` | Required in production | Must be `False`. |
| `ALLOWED_HOSTS` | Required in production | Include the exact deployed hostname(s). |
| `CSRF_TRUSTED_ORIGINS` | Required in production | Include exact HTTPS origins. |
| `DATABASE_URL` | Required in hosted production | Prefer platform-managed PostgreSQL. |
| `EMAIL_BACKEND` | Required in production | Use SMTP or an approved transactional provider backend. |
| `EMAIL_HOST` | Required for SMTP | Provider-specific. |
| `EMAIL_PORT` | Required for SMTP | Usually 587 with TLS. |
| `EMAIL_USE_TLS` | Required for SMTP | Provider-specific. |
| `EMAIL_USE_SSL` | Optional | Do not enable with TLS unless provider requires it. |
| `EMAIL_HOST_USER` | Required for SMTP | Provider-specific. |
| `EMAIL_HOST_PASSWORD` | Required for SMTP | Store only in deployment secrets. |
| `DEFAULT_FROM_EMAIL` | Required in production | Authenticated sender identity. |
| `SERVER_EMAIL` | Optional | Defaults to `DEFAULT_FROM_EMAIL`. |
| `MOTIONMATE_SUPPORT_EMAIL` | Optional | Shown in subscription emails when configured. |
| `SECURE_SSL_REDIRECT` | Optional | Defaults secure when `DEBUG=False`. |
| `SESSION_COOKIE_SECURE` | Optional | Defaults secure when `DEBUG=False`. |
| `CSRF_COOKIE_SECURE` | Optional | Defaults secure when `DEBUG=False`. |
| `SECURE_HSTS_SECONDS` | Optional | Defaults to 3600 when `DEBUG=False`. |
| `USE_X_FORWARDED_PROTO` | Optional | Enable when behind a trusted HTTPS proxy such as Heroku. |

## Stripe Price Variables

Every public plan, interval, and currency combination needs a configured Stripe Price ID before `STRIPE_ENABLED=true` can pass system checks.

| Variable | Status |
| --- | --- |
| `STRIPE_PRICE_STARTER_MONTHLY_USD` | Required when Stripe is enabled |
| `STRIPE_PRICE_STARTER_YEARLY_USD` | Required when Stripe is enabled |
| `STRIPE_PRICE_STARTER_MONTHLY_EUR` | Required when Stripe is enabled |
| `STRIPE_PRICE_STARTER_YEARLY_EUR` | Required when Stripe is enabled |
| `STRIPE_PRICE_PRO_MONTHLY_USD` | Required when Stripe is enabled |
| `STRIPE_PRICE_PRO_YEARLY_USD` | Required when Stripe is enabled |
| `STRIPE_PRICE_PRO_MONTHLY_EUR` | Required when Stripe is enabled |
| `STRIPE_PRICE_PRO_YEARLY_EUR` | Required when Stripe is enabled |
| `STRIPE_PRICE_BUSINESS_MONTHLY_USD` | Required when Stripe is enabled |
| `STRIPE_PRICE_BUSINESS_YEARLY_USD` | Required when Stripe is enabled |
| `STRIPE_PRICE_BUSINESS_MONTHLY_EUR` | Required when Stripe is enabled |
| `STRIPE_PRICE_BUSINESS_YEARLY_EUR` | Required when Stripe is enabled |

## Stripe Account Setup

- [ ] EXTERNAL ACTION REQUIRED - Test account configured.
- [ ] EXTERNAL ACTION REQUIRED - Live account activated.
- [ ] EXTERNAL ACTION REQUIRED - Business verification complete.
- [ ] EXTERNAL ACTION REQUIRED - Bank payout information complete.
- [ ] EXTERNAL ACTION REQUIRED - Statement descriptor reviewed.
- [ ] EXTERNAL ACTION REQUIRED - Support contact configured.

## Products And Prices

- [ ] EXTERNAL ACTION REQUIRED - Starter monthly Price created.
- [ ] EXTERNAL ACTION REQUIRED - Starter yearly Price created where supported.
- [ ] EXTERNAL ACTION REQUIRED - Pro monthly Price created.
- [ ] EXTERNAL ACTION REQUIRED - Pro yearly Price created where supported.
- [ ] EXTERNAL ACTION REQUIRED - Business monthly Price created.
- [ ] EXTERNAL ACTION REQUIRED - Business yearly Price created where supported.
- [ ] EXTERNAL ACTION REQUIRED - EUR and USD combinations confirmed.
- [ ] EXTERNAL ACTION REQUIRED - Price IDs entered into production environment.
- [ ] EXTERNAL ACTION REQUIRED - Test and live Price IDs not mixed.

## Checkout

- [ ] NOT TESTED - Payment-method collection required.
- [ ] NOT TESTED - Subscription mode confirmed.
- [ ] NOT TESTED - 14-day trial confirmed.
- [ ] NOT TESTED - Success URL confirmed.
- [ ] NOT TESTED - Cancellation URL confirmed.
- [ ] NOT TESTED - Test cards exercised.
- [ ] NOT TESTED - Abandoned Checkout exercised.

## Customer Portal

- [ ] EXTERNAL ACTION REQUIRED - Dedicated Portal configuration created.
- [ ] EXTERNAL ACTION REQUIRED - Payment-method update enabled.
- [ ] EXTERNAL ACTION REQUIRED - Invoice history enabled.
- [ ] EXTERNAL ACTION REQUIRED - Cancellation decision confirmed.
- [ ] EXTERNAL ACTION REQUIRED - Plan updates disabled.
- [ ] EXTERNAL ACTION REQUIRED - Quantity updates disabled.
- [ ] EXTERNAL ACTION REQUIRED - Promotion codes disabled.
- [ ] EXTERNAL ACTION REQUIRED - Live `bpc_...` ID configured.

## Webhooks

- [ ] EXTERNAL ACTION REQUIRED - Production webhook endpoint configured.
- [ ] EXTERNAL ACTION REQUIRED - Correct events selected.
- [ ] EXTERNAL ACTION REQUIRED - Webhook signing secret configured.
- [ ] NOT TESTED - Signature test passed in deployed environment.
- [ ] NOT TESTED - Duplicate-delivery test passed in deployed environment.
- [ ] NOT TESTED - Delayed-event test passed in deployed environment.
- [ ] EXTERNAL ACTION REQUIRED - Endpoint reachable over HTTPS.
- [ ] NOT TESTED - No authentication or CSRF interference.

## Application

- [ ] NOT TESTED - Migrations applied in target environment.
- [ ] NOT TESTED - System checks pass in target environment.
- [ ] NOT TESTED - Static assets collected in target environment.
- [ ] EXTERNAL ACTION REQUIRED - Production base URL configured.
- [ ] EXTERNAL ACTION REQUIRED - Email backend configured.
- [ ] EXTERNAL ACTION REQUIRED - Sender domain authenticated where applicable.
- [ ] EXTERNAL ACTION REQUIRED - Allowed hosts configured.
- [ ] EXTERNAL ACTION REQUIRED - Secure cookies and HTTPS settings reviewed.
- [ ] EXTERNAL ACTION REQUIRED - Stripe enabled only after webhook deployment.

## Lifecycle Tests

- [ ] NOT TESTED - Starter signup.
- [ ] NOT TESTED - Pro signup.
- [ ] NOT TESTED - Business signup.
- [ ] NOT TESTED - Monthly path.
- [ ] NOT TESTED - Yearly path.
- [ ] NOT TESTED - Trial activation.
- [ ] NOT TESTED - First payment.
- [ ] NOT TESTED - Payment failure.
- [ ] NOT TESTED - Grace.
- [ ] NOT TESTED - Restricted mode.
- [ ] NOT TESTED - Payment recovery.
- [ ] NOT TESTED - Scheduled cancellation.
- [ ] NOT TESTED - Effective cancellation.
- [ ] NOT TESTED - Notification delivery.
- [ ] NOT TESTED - Reminder discovery.
- [ ] NOT TESTED - Beta regression.

## Operations

- [ ] NOT TESTED - Notification enqueue command documented.
- [ ] NOT TESTED - Notification send command documented.
- [ ] NOT TESTED - Reconciliation command documented.
- [ ] NOT TESTED - Command dry runs completed.
- [ ] EXTERNAL ACTION REQUIRED - Operational owner identified.
- [ ] EXTERNAL ACTION REQUIRED - Failed notification inspection documented.
- [ ] EXTERNAL ACTION REQUIRED - Failed webhook inspection documented.
- [ ] EXTERNAL ACTION REQUIRED - Support escalation path documented.
