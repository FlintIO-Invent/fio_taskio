# Stripe Test-Mode QA Script

Use this script only with Stripe test-mode credentials and test Price IDs. Do not create live subscriptions, send real customer email, or store real credentials in this repository.

Where possible, run the Stripe CLI against a staging or local HTTPS tunnel so signed webhooks exercise the real `billing/webhooks/stripe/` endpoint.

## Setup

1. Configure fake or test-mode environment values for `STRIPE_ENABLED`, Stripe keys, webhook secret, Customer Portal configuration, and every `STRIPE_PRICE_*` variable.
2. Run `uv run --no-sync python src/manage.py check`.
3. Run migrations in the test environment.
4. Use the Django test email backend or a sandbox transactional provider.
5. Confirm `.env.example` contains placeholders only and real values are stored in deployment secrets.

## Public Signup And Checkout

1. Open public pricing with no currency parameter and confirm International/USD is selected, only USD card prices are active, and signup links include `currency=usd`.
2. Register Starter monthly from the International/USD pricing card with a non-Europe country.
3. Confirm Checkout uses the matching USD test Price ID and requires payment details.
4. Complete Checkout with a Stripe test payment method.
5. Confirm local state remains `pending_checkout` until the signed webhook is received.
6. Confirm webhook changes the local subscription to `trialing` and preserves `BusinessSubscription.billing_currency=usd`.
7. Select Europe/EUR on public pricing and confirm only EUR card prices are active and signup links include `currency=eur`.
8. Register Pro monthly with a Europe country such as `Germany`.
9. Confirm Checkout uses `STRIPE_PRICE_PRO_MONTHLY_EUR`.
10. Complete Checkout and confirm the signed webhook preserves `BusinessSubscription.billing_currency=eur`.
11. Register Business yearly from International/USD with a non-Europe country and confirm Checkout uses `STRIPE_PRICE_BUSINESS_YEARLY_USD`.
12. Confirm Starter, Pro, and Business features and limits match the selected plan after webhook activation.
13. Attempt a Europe country such as `Germany` with International/USD and confirm registration rejects it before creating an account, business, subscription, or Stripe Checkout Session.
14. Attempt a non-Europe country with Europe/EUR and confirm registration rejects it before creating an account, business, subscription, or Stripe Checkout Session.
15. Attempt an invalid `currency` link value and confirm it does not select an unsupported currency.
16. Confirm pricing is not changed by IP address, VPN location, browser locale, timezone, or language headers.
17. Cancel Checkout before completion and confirm local state remains `pending_checkout`.
18. Resume Checkout and confirm the stored open Session is reused when still usable.
19. Expire or abandon Checkout and confirm a replacement Session can be created without granting access.

## Webhook Reliability

1. Replay the successful Checkout webhook and confirm duplicate delivery does not create duplicate notifications.
2. Replay a stale older subscription update after a newer active or cancelled state and confirm no downgrade.
3. Send a webhook with a wrong signing secret and confirm no local state changes.
4. Send malformed JSON and confirm no local state changes.
5. Confirm unknown Price IDs fail closed and do not grant access.

## Trial And Active Periods

1. Use fixed test timestamps to confirm `now < trial_end` gives full access.
2. Confirm `now == trial_end` gives no trial access without newer provider state.
3. Confirm `now > trial_end` gives no trial access without newer provider state.
4. Send the first successful charge or active subscription event and confirm local status becomes `active`.
5. Confirm active access requires `now < current_period_end` for Stripe-backed public subscriptions.

## Failed Payment And Recovery

1. Trigger or simulate `invoice.payment_failed`.
2. Confirm `past_due_since` and `grace_period_ends_at` are set from the provider event time.
3. Confirm repeated failed-payment events do not extend grace.
4. Confirm owners see payment warning and recovery action during grace.
5. Confirm non-owners see neutral billing-attention wording.
6. Confirm `evaluation_time < grace_period_ends_at` gives full access.
7. Confirm `evaluation_time >= grace_period_ends_at` gives restricted read-only access.
8. Confirm restricted users can view existing records and detail pages.
9. Confirm restricted users cannot create, edit, delete, send, import, upload, invite, change status, or mutate via direct URLs.
10. Confirm public booking and public request creation are blocked neutrally.
11. Open payment recovery Portal as owner.
12. Return from Portal and confirm state does not change.
13. Send verified `invoice.paid` or valid active subscription webhook.
14. Confirm status becomes `active`, grace fields clear, full access returns, and payment-recovered notification is queued.

## Cancellation

1. Schedule cancellation at period end in the Stripe test dashboard or through a test event.
2. Confirm local `cancel_at_period_end=True` while status remains `trialing` or `active`.
3. Confirm access stays full until the effective end.
4. Confirm cancellation-scheduled notification is queued once.
5. Send effective cancellation webhook.
6. Confirm local status becomes `cancelled`, access becomes none, and cancellation notification is queued once.

## Notifications And Reminders

1. Run `enqueue_subscription_reminders --dry-run --at <aware ISO datetime>`.
2. Run `enqueue_subscription_reminders --at <same aware ISO datetime>`.
3. Confirm trial three-day window is `24 hours < remaining <= 72 hours`.
4. Confirm trial one-day window is `0 < remaining <= 24 hours`.
5. Confirm grace one-day window is `0 < remaining <= 24 hours`.
6. Confirm restricted-mode reminder can catch up after the grace boundary.
7. Run `send_subscription_notifications --dry-run`.
8. Run `send_subscription_notifications`.
9. Confirm delivery marks rows sent and retry failed works without duplicate sends.
10. Confirm obsolete reminders are cancelled before delivery after recovery or cancellation.

## Beta Regression

1. Register through the private beta route using the configured beta token.
2. Confirm beta is active immediately and non-trialing.
3. Confirm no Stripe Checkout, payment method, Price ID, customer ID, subscription ID, grace period, Portal, recovery action, trial reminder, or billing notification is created.
4. Confirm beta is not visible on public pricing and cannot be selected by tampered public signup.

## Notes On Hard-To-Simulate Conditions

- Use Stripe CLI replay for duplicate and delayed webhooks.
- Use signed local fixture payloads for exact stale ordering and boundary timestamps.
- Use Stripe test clocks where available for subscription lifecycle timing.
- Do not create production subscriptions for QA.
