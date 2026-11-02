# Logistics free-test registration

Core, Growth and Scale use the existing private free-test endpoint:

```text
<BASE_URL>/accounts/free-test/logistics-core/<CORE_SECRET>/
<BASE_URL>/accounts/free-test/logistics-growth/<GROWTH_SECRET>/
<BASE_URL>/accounts/free-test/logistics-scale/<SCALE_SECRET>/
```

## Availability and paid activation

`ClarivoPlan.logistics_free_test_enabled` permits free access independently of
`is_active`. It defaults to false for every existing and new plan. Migration
`businesses.0037_clarivoplan_logistics_free_test_enabled` only adds this field; it
does not enable tiers, alter capacities, or rewrite subscriptions.

An operator can enable **Logistics free-test access** in Django Admin while leaving
**Is active** unchecked. Admin accepts this flag only for Core/Growth/Scale in family
`LOGISTICS` with every `LOGISTICS_TIER_CAPACITY_FIELDS` value configured. Free
registration repeats those family/capacity checks for both GET and POST. Existing
active tiers continue to accept free-test registrations without the new flag.

The inactive-plan access exception requires the enabled, complete Logistics tier
and both `provisioning_source=FREE_TEST` and `payment_provider=LOCAL`. Workspace
compatibility, business activation, approval suspension, subscription status,
permissions, and quota checks still apply. Disabling the plan's free-test flag
removes this exception; use the registration settings/tokens to stop only new signups.

Enabling free access makes no Stripe calls and works with production LIVE keys or
with Stripe disabled. Paid activation still requires the existing Stripe TEST
validation, including when the free flag is set. Paid Checkout still requires an
active plan and all existing enrollment, owner, amount, currency, Price and provider
checks. Public signup and Services/Beta behavior are unchanged.

## Exact operator steps for Scale in production

These steps are for a future, separately authorized production rollout. This local
implementation does not execute them or change production configuration/data/Stripe.
Use the production runtime's Python executable in place of `.venv/bin/python` where
needed; commands below assume the repository root.

1. Release the reviewed code through the normal deployment process and apply the
   additive migration using that release's production runtime:

   ```bash
   .venv/bin/python src/manage.py migrate businesses
   ```

2. In Django Admin, open `/admin/businesses/clarivoplan/`, select the row whose exact
   slug is `logistics-scale`, and verify its family is `LOGISTICS` and all capacities
   are populated. Check **Logistics free-test access**, leave **Is active** unchecked,
   and save. Preserve its capacities, prices, and feature flags. Leave Core/Growth
   unchanged. This save does not configure or contact Stripe.

3. Generate a private URL-safe secret in a private terminal:

   ```bash
   .venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))'
   ```

   Store that value in production secret configuration as
   `FREE_TEST_LOGISTICS_SCALE_TOKEN`. Enable the existing shared flag:

   ```dotenv
   FREE_TEST_REGISTRATION_ENABLED=True
   FREE_TEST_LOGISTICS_SCALE_TOKEN=<GENERATED_SECRET>
   ```

   The shared flag also controls Services free-test registration. Existing Services
   tokens and the Beta settings need no changes. Core/Growth tokens can stay empty.
   Keep the Stripe LIVE configuration unchanged and keep
   `LOGISTICS_LOCAL_BILLING_BYPASS=False` in production.

4. Reload application configuration using the normal production restart process.
   The reusable production link is exactly:

   ```text
   https://<PRODUCTION_HOST>/accounts/free-test/logistics-scale/<GENERATED_SECRET>/
   ```

   If the existing `MOTIONMATE_PUBLIC_BASE_URL` setting contains the production HTTPS
   origin, print the link from the reloaded production runtime with this read-only
   command. It reads the configured token rather than generating a second one:

   ```bash
   .venv/bin/python src/manage.py shell -c 'from django.conf import settings; from django.urls import reverse; from apps.accounts.free_test_registration import get_configured_free_test_registration_token, free_test_plan_queryset; base = settings.MOTIONMATE_PUBLIC_BASE_URL.strip().rstrip("/"); token = get_configured_free_test_registration_token("logistics-scale"); assert base.startswith("https://"), "Verify the production HTTPS base URL"; assert settings.FREE_TEST_REGISTRATION_ENABLED and token and free_test_plan_queryset("logistics-scale").exists(), "Scale free registration is unavailable"; print(base + reverse("register_business_free_test", args=["logistics-scale", token]))'
   ```

   Share the output privately. No dedicated Logistics link-generation command is
   required. A recipient uses a new account email and a valid password; the link
   fixes the Logistics vertical and Scale tier server-side.

## Lifecycle

Registration atomically creates the user, `LOGISTICS` business, `LogisticsProfile`
with normal defaults, owner membership, user profile and exact tier subscription.
The existing success path logs in the owner and selects the current business.
Location review and operations permissions retain their normal defaults.

The subscription is `ACTIVE`, `FREE_TEST`, `LOCAL`, with
`billing_interval=yearly`, no Stripe identifiers, no trial, and no access deadline.
Yearly is a compatibility marker and does not expire access after one year. Existing
tier features, capacities, quota enforcement and free-test restrictions apply.
Owners cannot change tiers through the subscription form. Checkout is not started;
Logistics Customer Portal and payment recovery remain unavailable.

Links are reusable across new accounts and have no time-based expiry. To stop new
registrations, clear only `FREE_TEST_LOGISTICS_SCALE_TOKEN` or disable the shared
registration flag, then reload configuration. Rotate the link by replacing only
its token. Existing accounts retain access after token removal/rotation or disabling
the shared registration setting; keep the plan's **Logistics free-test access** enabled for their ongoing
access while its paid activation remains off. Business/subscription suspensions
continue to apply. No payment conversion, renewals, installments or expiry automation
is introduced.

## Local validation (2026-11-02)

- **223 tests passed** on a fresh disposable UTF-8 PostgreSQL 14 cluster, including
  all **21 Logistics free-test tests**. Coverage includes production LIVE-mode free
  registration with no tier Price configuration, no-key free registration, selected
  tier Admin enablement, invalid capacities/family, unchanged paid activation and
  Checkout rejection, Services/Beta/public registration, account/password protection,
  quota enforcement, suspension, token removal/rotation, access after 800 days,
  reconciliation, signed webhooks and PostgreSQL concurrency. The free-test module
  blocks Stripe HTTP and asserts it was never called; paid tests use provider mocks.
- Ruff, Black, Django system checks, migration drift checking, and
  `git diff --check` passed. The test database applied migration 0037 successfully.
- The first broader run used an incorrectly initialized SQL_ASCII test cluster and
  failed on UTF-8 webhook notification content. The cluster was recreated as UTF-8;
  the complete 223-test rerun passed under the ordinary Python runtime.
- No production deployment, configuration/data changes, real Stripe calls, or
  Stripe resource changes were performed. The normal local application database
  was not migrated or modified.
