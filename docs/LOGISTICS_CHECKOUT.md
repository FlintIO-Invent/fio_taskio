# Logistics annual checkout (Block 5)

## Local operational testing without checkout

For Client → Parcel → Shipment testing, use the existing local effective-access
bypass. In repository-root `.env`, set `ENV=local`, `DEBUG=True`,
`LOGISTICS_AUTO_APPROVE_ALL=True`, `LOGISTICS_LOCAL_BILLING_BYPASS=True` and
`STRIPE_ENABLED=False`, with a local `SECRET_KEY`. Keep the database configuration
pointing at the existing local database. `src/config.py` already loads this file
using an absolute path; no shell sourcing or additional dotenv loader is needed.
Exported variables override `.env`. For example, an inherited `DEBUG=release`
resolves to False, so use `DEBUG=True python3 src/manage.py runserver` locally.

Sign in at `/accounts/login/` with the existing Logistics owner, then open
`/crm/agent/dashboard/`. New applicants can use `/logistics/apply/` with a new
account password. The real operational dashboard displays a local billing bypass
banner and the existing KPIs, actions, events, shipments and attention sections.
Clients, Parcels and Shipments retain their normal tenant, role and entitlement guards.

The compatible yearly, no-trial Stripe subscription remains `pending_checkout`;
the staged Logistics plan may remain inactive and unpriced. This grants effective
local access without changing billing records or calling Stripe. Disabling the
flag immediately restores payment gates. Development/Staging and Production must
set `LOGISTICS_LOCAL_BILLING_BYPASS=False` and configure TEST/LIVE billing below.
Startup checks and the runtime policy reject the bypass outside `ENV=local` with
`DEBUG=True`. This configuration tests operations; it does not verify payments.

An authenticated converted applicant continues from `/logistics/enroll/complete/`
using a CSRF-protected POST to `/logistics/enroll/<application-id>/checkout/`.
The existing billing resume action delegates Logistics enrollments to that entry.
There is no public plan/Price checkout link. The application UUID is a selector,
not authorization: only its enrolled, active OWNER may proceed. No enrollment token
is needed to resume, so expiration of the consumed enrollment grant is harmless.

`apps.logistics.billing.checkout_for_application` is the reusable entry service.
It locks the application and existing subscription, rechecks APPROVED status,
current approved/evaluated/converted revision, durable conversion, active ownership,
LOGISTICS Business/plan, pending checkout, Stripe provider, yearly interval, no trial,
and approved currency. Material changes after conversion require review and cannot
charge against the previous conversion, including after reapproval. This block
provides no amendment or reprovisioning path.

The service calls the shared `resume_trial_checkout_session` pipeline. Its legacy
name is retained for SERVICE compatibility; the offering registry gives Logistics
zero trial days. The shared create/resume functions also enforce Logistics admission,
preventing callers from bypassing the enrollment check. All metadata keys, client
reference, success/cancel URLs and Stripe idempotency conventions are preserved.
Repeated starts serialize through row locks. If Stripe succeeds but the local write
fails, retry uses the same shared provider idempotency key.

## Commercial configuration and activation

The seeded Logistics plan stays inactive/unpriced. No production prices or Price
IDs are introduced. Configure actual commercial annual display amounts using the
existing `ClarivoPlan.regional_prices` pattern, explicitly setting the currency:

- `usd`: currency `USD`, yearly agreed USD amount.
- `eur`: currency `EUR`, yearly agreed EUR amount.

Configure only the annual currencies actually supported:

```
STRIPE_PRICE_LOGISTICS_YEARLY_USD=price_...
STRIPE_PRICE_LOGISTICS_YEARLY_EUR=price_...
```

A one-currency offering does not require the other currency or monthly mappings.
All existing SERVICE Price configuration requirements remain unchanged. An enrolled
currency without its annual mapping fails closed; it never falls back to another
currency, monthly Price or zero database placeholder.

Django Admin activation validates at least one annual mapping and its positive,
matching display price, then verifies each configured annual Stripe Price before
allowing `is_active`. Stripe must be enabled and its existing configuration valid.
Automated future activation should call `validate_offering_activation` before saving;
raw database/QuerySet updates bypass Admin validation, but checkout still performs
all commercial checks. Runtime configuration failures do not automatically deactivate
already-paid tenants or rewrite their subscription lifecycle.

Checkout independently retrieves the configured Stripe Price and requires active,
recurring, licensed, per-unit pricing, interval year/count 1, correct USD/EUR currency,
and the exact positive configured annual amount in cents. Ambiguous Price mappings,
including SERVICE/LOGISTICS aliases, reject selection. Missing, zero, mismatched or
unverifiable prices raise explicit configuration errors and create no Checkout Session.

The browser accepts no plan, Price, interval or currency inputs. Unexpected POST/query
parameters reject. Approved application currency and the existing subscription determine
all choices. Before reusing a stored session, the pipeline revalidates admission and
commercial configuration, verifies its existing metadata/reference, and retrieves its
expanded line item to verify one unit of the selected annual Price.

## Provider lifecycle and recovery

Success/cancel pages only read local subscription/access state. Client session IDs or
payment claims cannot activate access. Logistics copy describes annual confirmation,
without SERVICE trial promises. A completed provider session awaits webhook confirmation;
it never creates another session or activates access from the return page.

The existing signed Stripe webhook, event ledger, provider ordering and transactional
synchronization remain unchanged. Valid events update the existing BusinessSubscription,
customer/subscription identities, paid state and notification outbox. They do not create
Users, Businesses or subscriptions. Logistics trials and mismatched family/Price events
remain rejected. Duplicate events remain idempotent. Payment confirmation remains provider
authoritative if an application is changed after an already-authorized checkout; subsequent
checkout/resume is blocked by current approval checks.

Open usable sessions are reused. Expired sessions use the existing replacement/idempotency
conventions. Abandoned checkout retains enrollment and subscription. Network failures and
local transaction rollback do not reprovision. Paid/past-due/grace/read-only/recovered states
use normal subscription access rules and existing notification/reminder infrastructure.
Logistics activation messaging confirms annual payment; recovery messages direct applicants
to support. Logistics Customer Portal remains disabled to preserve family/interval controls.

## Validation and remaining deployment decisions

Focused tests use mocked provider APIs and genuinely signed webhook requests to cover
admission, prices/configuration, tampering, no trial, return pages, webhook idempotency,
provider state, notifications, resumption and rollback. Existing SERVICE checkout/trial and
billing regressions run with the full suite. SQLite does not verify PostgreSQL row-lock
concurrency. A real Stripe test-mode end-to-end payment is a deployment validation step;
these tests do not claim to perform one.

Before commercial rollout, supply agreed annual prices, matching Stripe IDs and activate
the plan through its validated Admin form. Keep Portal disabled pending a safe configuration.
Post-conversion amendments need an explicit review/synchronization policy in a later block.
No Parcel, operational navigation, PWA, API or scanner implementation is included.

## Real local Stripe TEST payment

The current local database's seeded `logistics` plan is inactive, with
`price_yearly=0.00` and empty `regional_prices`. The first checkout gate raises
`The Logistics offering is inactive` and the view returns 503 before calling Stripe.
Approval and conversion intentionally do not activate the offering. The local
operational configuration above leaves Stripe disabled, with empty keys and Price
mappings. To test payment instead, configure the prerequisites below and disable
the bypass; do not activate the zero-priced placeholder or change subscription
status manually.

1. Create a root `.env` from `.env.example` if absent. Keep `DEBUG=True`,
   `ALLOWED_HOSTS=127.0.0.1,localhost`, the local CSRF origins, and
   `LOGISTICS_LOCAL_BILLING_BYPASS=False`. The existing Pydantic settings loader
   reads this file when `python3 src/manage.py runserver` starts from the repo root.
2. In the same Stripe TEST account, create two active recurring annual Prices,
   EUR and USD, with interval count 1, licensed/per-unit pricing and positive
   amounts. Set `STRIPE_ENABLED=true`, `STRIPE_PUBLISHABLE_KEY=pk_test_...`,
   `STRIPE_SECRET_KEY=sk_test_...`, `STRIPE_PRICE_LOGISTICS_YEARLY_EUR=price_...`
   and `STRIPE_PRICE_LOGISTICS_YEARLY_USD=price_...` in `.env`. Use the real TEST
   values, not these placeholders. Keep the twelve existing SERVICE Price
   variables and `STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID=bpc_...` configured
   for this same account: shared SDK validation requires them even for Logistics.
   This does not enable Logistics Customer Portal.
3. Install Stripe CLI, authenticate with `stripe login` to that same TEST account,
   and leave this forwarding command running (no `--live`):

   ```bash
   stripe listen --forward-to http://localhost:8000/billing/webhooks/stripe/
   ```

   Set `STRIPE_WEBHOOK_SECRET` to the `whsec_...` printed by this listener, not a
   Dashboard endpoint's signing secret. Restart Django after setting it. Stripe's
   [local webhook instructions](https://docs.stripe.com/webhooks#local-listener)
   describe this signed forwarding flow. Forward the account's snapshot events;
   no fake application webhook or `stripe trigger` payment shortcut is needed.
4. In `/admin/businesses/clarivoplan/5/change/` (or select the existing `logistics`
   row from `/admin/businesses/clarivoplan/`), keep `slug=logistics`,
   `family=LOGISTICS`, and `price_monthly=0.00`. Set a positive `price_yearly`
   default and explicit `regional_prices` entries for both currencies:

   ```json
   {
     "usd": {"currency": "USD", "yearly": "<positive USD annual amount>"},
     "eur": {"currency": "EUR", "yearly": "<positive EUR annual amount>"}
   }
   ```

   Replace the amount placeholders with decimal amounts exactly matching the TEST
   Prices (`yearly * 100 == unit_amount`). Then select `is_active` and save. The
   existing Admin form verifies the remote Prices; invalid configuration rejects
   saving. No monthly Logistics Price or trial configuration is required.
5. Run `python3 src/manage.py check`. Diagnose the existing enrollment without
   changing any records or creating a Session:

   ```bash
   python3 src/manage.py check_logistics_checkout --application-id <application-uuid> --verify-provider
   ```

   This checks the existing subscription and both annual currency Prices; omitting
   `--verify-provider` performs only local configuration checks. A rejected
   enrollment prints stable reason codes and exits nonzero. Start/restart
   `python3 src/manage.py runserver`, sign in as the existing enrolled OWNER at
   `http://localhost:8000`, and open `/logistics/enroll/complete/`. Click
   **Continue to annual checkout**. The POST reuses the existing Business and
   pending subscription, using its enrolled USD/EUR currency. Stripe must show
   TEST mode and the agreed annual amount with no trial. Success/cancel return
   URLs use the request's local host and port.
6. Complete Checkout with test card `4242 4242 4242 4242`, a future expiration,
   any three-digit CVC and the requested billing details. See Stripe's
   [test cards](https://docs.stripe.com/testing). The return page remains
   informational: it cannot activate access.
7. Confirm forwarded webhook requests return 200. Inspect the existing
   BusinessSubscription in Admin: signed webhook processing populates its Stripe
   customer/subscription IDs, changes status to `active` and synchronizes its
   provider period; trial dates remain empty and effective access becomes FULL.
   The existing webhook ledger and outbox deduplicate retries. Re-deliver the same
   signed event through Stripe's retry tooling and verify the same subscription
   and event ledger row are retained. Do not create another enrollment.

Checkout warnings include local application/Business IDs, a stable `reason`, and a
safe wrapper message. Reasons distinguish inactive offering, disabled Stripe,
invalid annual amount, existing Stripe configuration check IDs (including missing
Price, secret key or unsupported currency), invalid application/revision,
ineligible subscription, remote Price verification and provider session failures.
Provider exception chains, secret values and raw provider responses are not logged
or rendered by the application. Django's Stripe SDK logger suppresses INFO/DEBUG
provider details; leave the SDK's separate `STRIPE_LOG` environment setting unset.
Configuration failures remain 503; enrollment/eligibility and session
provider failures retain the existing 409 response behavior.

The shared webhook accepts billing periods at both the legacy subscription level
and the single subscription-item level used by the installed SDK's current API.
Stripe documents this change in its
[billing period migration](https://docs.stripe.com/changelog/basil/2025-03-31/deprecate-subscription-current-period-start-and-end).
Both shapes use the existing signed-event ledger and subscription synchronization.

The implementation is identical when promoted: Local uses TEST keys/Prices with
CLI forwarding; Development/Staging uses TEST keys/Prices with its deployed signed
webhook URL; Production uses LIVE keys/Prices with its production signed webhook
URL and endpoint-specific secret. The deployed endpoint path remains
`/billing/webhooks/stripe/`. Only configuration changes.
