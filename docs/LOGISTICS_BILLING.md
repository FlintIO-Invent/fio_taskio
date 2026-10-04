# Logistics offering foundation (Block 2)

`ClarivoPlan.family` defaults to `SERVICE`, including all existing plans. Migration
0026 seeds one `logistics` plan in the `LOGISTICS` family. Its inactive state and
zero prices mean **commercial pricing is unset**, not a free offer. Nullable limits
are also awaiting a commercial decision. Configure prices/limits before deliberately
activating this plan; no final pricing is supplied. Block 5 admission, commercial
validation and checkout are documented in [LOGISTICS_CHECKOUT.md](LOGISTICS_CHECKOUT.md).
Existing rows are backfilled to SERVICE by the new field default. Reapplying the
seed preserves configured values; rollback refuses to delete an activated/priced
offering, and subscription references retain the existing PROTECT safeguard.

The public catalog remains Starter / Pro / Business. `billing_policy.py` separately
defines Stripe-billable offerings, compatible business verticals, billing intervals
and trial days. Logistics supports yearly billing only and no trial. Checkout creates
a pending row with no access; signed webhooks activate the paid subscription. SERVICE
retains its existing monthly/yearly billing and 14-day trial. Existing metadata keys,
webhook verification, event ordering and idempotency remain unchanged.

Optional environment configuration:

```
STRIPE_PRICE_LOGISTICS_YEARLY_USD=price_...
STRIPE_PRICE_LOGISTICS_YEARLY_EUR=price_...
```

No Logistics monthly mapping exists or is accepted. All twelve SERVICE mappings remain
required when Stripe is enabled. Logistics annual mappings are validated if configured;
checkout requires the requested currency mapping. Set matching database display pricing
and Stripe annual prices before activation. No Stripe prices are created by migrations.

The shared Checkout service, webhook lifecycle, notification outbox, reminder discovery
and grace/restricted access evaluation recognize annual Logistics subscriptions. Trial
reminders do not apply. Public registration remains SERVICE-only. The billing resume
route now admits current converted Logistics approvals through the shared pipeline;
approval and enrollment were added in Blocks 3–4.

Logistics Customer Portal and payment-recovery Portal sessions are deliberately disabled.
The single existing portal configuration ID does not establish a safe offering-specific
configuration. Before enabling it, use a validated configuration with subscription plan
and interval changes disabled (or rigorously restricted). Keep Logistics excluded from
the SERVICE Portal's product catalog. The existing SERVICE configuration already requires
subscription plan updates disabled; see `STRIPE_SUBSCRIPTION_CONFIG.md`. Cross-family and
monthly Logistics updates also fail local webhook validation. Payment recovery can still
be reflected through valid Stripe payment/subscription webhooks, but Logistics has no
self-service recovery Portal yet. Notifications must not promise one.
