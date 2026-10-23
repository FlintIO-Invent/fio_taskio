# Block E3: staged Logistics Stripe Price configuration

Audit: `config.Settings` types/normalizes environment values; `taskio.settings`
builds `STRIPE_PRICE_ID_MAP`; `businesses.stripe_config` resolves that map using
checkout-enabled offerings and checks key modes. `logistics.billing` validates
legacy annual provider Prices against regional display amounts. Its enrollment,
activation and Checkout guards remain legacy-only. New tiers are deliberately
absent from checkout/webhook resolution and remain disabled in `billing_policy`.

E3 adds three typed, trimmed optional string settings (empty by default):

| Tier | Environment variable | EUR/year | Stripe `unit_amount` |
| --- | --- | ---: | ---: |
| `logistics-core` | `STRIPE_PRICE_LOGISTICS_CORE_YEARLY_EUR` | 1700.00 | 170000 |
| `logistics-growth` | `STRIPE_PRICE_LOGISTICS_GROWTH_YEARLY_EUR` | 2300.00 | 230000 |
| `logistics-scale` | `STRIPE_PRICE_LOGISTICS_SCALE_YEARLY_EUR` | 3000.00 | 300000 |

Settings construct a separate `STRIPE_LOGISTICS_TIER_PRICE_ID_MAP`, keyed by
`(full-hyphenated-slug, "yearly", "eur")`; environment attribute names use underscores.
This staged map never enters the existing checkout/webhook resolver. It imposes
no new requirements on SERVICE-only or legacy Logistics installations.

The opt-in `configured_tier_prices()` check requires all three mappings, nonempty
`price_` IDs and distinct IDs, including no reuse of existing SERVICE/legacy IDs.
Unknown dimensions, monthly and USD mappings are rejected. No USD settings or
amounts are added. `validate_tier_stripe_price()` additionally retrieves each Price
and requires exact ID, active status, matching key-mode `livemode`, EUR currency,
the approved amount above, recurring yearly interval/count 1, licensed usage,
per-unit billing and Price metadata `motionmate_plan_slug` equal to that tier.
Mixed/missing keys, disabled Stripe, retrieval errors and malformed Prices fail.
LIVE-key verification is refused in any environment other than `production`;
production verification is read-only and does not authorize checkout.

No application, enrollment, subscription, migration, existing Stripe helper,
Customer Portal, plan activation or payment execution changes are part of E3.
No deployed database/configuration or real provider object was changed.

## Manual Stripe TEST setup (operator actions; not executed)

1. Select the intended Stripe **sandbox/test environment** and confirm the displayed
   API keys are `pk_test_...` and `sk_test_...` from that same account/environment.
   Do not copy anything to live mode.
2. In **More → Product catalog → +Add product**, create `Motionmate Logistics Core`.
   Choose **Flat-rate**, **Recurring**, **EUR 1700.00**, billing period **Yearly**
   (every 1 year), quantity-based/licensed usage. Save the product and its Price.
   Repeat for `Motionmate Logistics Growth` at **EUR 2300.00/year** and
   `Motionmate Logistics Scale` at **EUR 3000.00/year**. Add no monthly/USD Prices.
   Inspect existing sandbox products first to avoid creating duplicates.
3. Open each Price's details and record its distinct `price_...` ID. On the **Price**
   (not just the Product), add metadata `motionmate_plan_slug` with its exact
   corresponding slug from the table. If metadata editing is unavailable in the
   Dashboard, run this explicit operator command once per Price, substituting the
   actual Price ID and slug, using only that sandbox's TEST secret:

   ```sh
   stripe prices update price_REPLACE --api-key "$STRIPE_SECRET_KEY" \
     -d 'metadata[motionmate_plan_slug]=logistics-core'
   ```

4. On your operator-selected local/test configuration only, assign the three
   variables above to their respective IDs. Never commit secrets. Existing
   `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
   `STRIPE_CUSTOMER_PORTAL_CONFIGURATION_ID`, SERVICE Price matrix and any existing
   legacy mappings retain their existing meanings; do not replace them with tier IDs.
5. Check local mappings without provider contact:

   ```sh
   python src/manage.py check_logistics_tier_prices
   ```

   Then, only with the existing shared Stripe configuration valid and
   `STRIPE_ENABLED=true` using matching TEST keys, retrieve/verify the Prices:

   ```sh
   python src/manage.py check_logistics_tier_prices --verify-provider
   ```

   This opt-in command only retrieves Prices. Default execution cannot prove
   provider amounts, activity, metadata or mode. Neither command enables tier
   checkout or changes plan/subscription records. Do not activate tier payment
   flows, send payment requests, or create subscriptions during E3.

Stripe references: [product/price creation](https://docs.stripe.com/products-prices/manage-prices),
[Price attributes and metadata](https://docs.stripe.com/api/prices/object),
[sandbox isolation](https://docs.stripe.com/sandboxes).

## Validation results

- Final E3 and existing shared Stripe configuration tests: 26 passed.
- Existing SERVICE checkout/Portal/return/webhook services, legacy Logistics
  billing/Checkout, capacity tiers and E2 enrollment: 142 tests OK, one
  PostgreSQL-only concurrency skip. No database/concurrency implementation changed.
- Fresh-process typed environment-to-map wiring checked all three hyphenated
  slugs. Ruff, Black, Django system checks, migration drift and whitespace passed.

Raw logs: `/tmp/logistics-e3-unit-final.log`, `/tmp/logistics-e3-regression.log`.
Provider calls were mocked; actual sandbox Price verification remains an operator
setup step. No real Stripe object or deployed setting was inspected or modified.
