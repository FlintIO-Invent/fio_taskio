# Logistics local development and promotion

The same subscription access policy, dashboard, navigation and Parcel/Shipment
services run in Local, Development/Staging and Production. Only configuration
changes when promoting the code.

| Environment | ENV | DEBUG | LOGISTICS_LOCAL_BILLING_BYPASS |
| --- | --- | --- | --- |
| Local, optional payment bypass | local | True | True |
| Local, normal billing testing | local | True | False |
| Development / Staging | development / staging | False | False |
| Production | production | False | False |

`LOGISTICS_LOCAL_BILLING_BYPASS` defaults to False. To test unpaid local operations:

```dotenv
ENV=local
DEBUG=True
LOGISTICS_LOCAL_BILLING_BYPASS=True
```

Restart the local Django process after changing environment settings. Do not enable
this option on hosted Development/Staging or Production. An explicit `ENV=local`
is required, so accidentally enabling DEBUG in a deployed environment is insufficient.
The normal Django startup/check command reports `logistics.E014` if the flag is
enabled without both local environment and debug mode. The access policy independently
denies the override under invalid configuration, even if system checks are skipped.

## Effective access, truthful billing state

`BusinessSubscription.effective_access_state_at` applies the local override only
after normal offering compatibility and active-Business checks. The subscription
must be Logistics-family, annual, non-trial, Stripe-backed, USD/EUR and
`pending_checkout`. Missing subscriptions, SERVICE tenants, incompatible offerings,
inactive Businesses and cancelled/expired/suspended/past-due subscriptions never
receive the override. Existing role and module entitlement checks still apply.

A compatible staged Logistics plan may remain inactive and unpriced locally;
the bypass changes neither the plan nor subscription. No Stripe call, provider
identity, payment record or trial is created. Status remains `pending_checkout`.
The effective result is FULL with reason `local_logistics_billing_bypass`, exposed
through the same access helpers that normal paid subscriptions use.

Turning the flag off immediately restores normal effective billing gates. In
Development/Staging, use the existing Stripe TEST-mode annual checkout and verified
webhooks. Production uses normal configured production billing. Return URLs alone
never change payment state; the webhook remains authoritative. Stripe activation,
annual pricing, offering entitlements and SERVICE access behavior are unchanged.

## Dashboard and navigation

FULL effective access shows the existing operational Logistics dashboard. A local
override adds only `LOCAL DEVELOPMENT — billing bypass active`. Paid FULL access
shows the identical dashboard without the indicator. Pending/restricted Logistics
access shows payment/subscription resolution at the same dashboard route.

The dashboard shows active parcels, registered/received parcels, in-transit and
ready parcels, active shipments and distinct delivered parcels this calendar month
in the Business timezone. Lists show the five most recent parcel events, five
active shipments and five parcels on hold or awaiting shipment, oldest first.
All queries use the current tenant and existing domain services/status definitions.

Register Parcel, Create Shipment, Add Client and Public Tracking actions use normal
role and effective module access. Navigation does the same; SERVICE-only areas stay
unavailable. No view, navigation or template checks DEBUG or the environment flag.

Run `python src/manage.py check` after configuring each deployment. No migrations
or source edits are required to switch from local bypass to normal payment access.
