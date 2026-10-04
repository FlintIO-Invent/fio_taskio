# Logistics annual checkout (Block 5)

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
