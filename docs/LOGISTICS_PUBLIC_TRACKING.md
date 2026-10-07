# Anonymous parcel tracking (Block 7)

`GET /logistics/track/` displays an anonymous form; CSRF-protected POST accepts
only an exact existing 48-character uppercase tracking code. Codes are bearer
secrets with 192 random bits. No PK, UUID, tenant selection, query-string lookup,
search, API or customer account is supported. POST keeps codes out of normal
access-log URLs. Never configure request-body logging on this endpoint.

## Public projection and privacy

`apps.logistics.public_tracking.lookup_public_tracking(code)` returns a plain,
JSON-compatible allowlisted dictionary or `None`. Future API/PWA clients can
reuse this boundary; none are implemented here. The HTML template receives only
the projection, generic error text and CSRF token, without workspace context
processors. It escapes all public text and sets no-store, same-origin referrer policy and
noindex/noarchive headers. No lookup history or application lookup logging exists.
Tracking inputs are redacted from Django production exception reports.

Public fields are tracking code, current status/label, business display name,
and chronological public event messages, status/label and ISO 8601 timestamps
with UTC offsets. Events must have a nonblank `public_message`; internal-only
events do not expose even timestamps/statuses. Events are filtered by both
parcel and business ownership. Parcel/Client ownership must also agree.

Origin, destination and event location are unrestricted text without an explicit
public designation, so they are omitted rather than guessing a safe granularity.
Business contact fields are not explicitly public and are also omitted. The
support area directs the customer to contact the courier using their receipt.
Client details, all addresses, package data, declared value, internal notes,
actors, database identifiers, invoices/payments, applications, private manifests
and admin metadata never enter the projection.

Staff must keep customer-facing `public_message` free of private information;
the projection does not try to infer or redact personal data from that explicitly
public text. Existing staff UI, registration, lifecycle, enrollment, billing,
SERVICE workflows, demo defaults and purge safeguards are unchanged.

## Business lifecycle

An active LOGISTICS Business with a compatible active plan, parcels/tracking
entitlements and **full effective subscription access** may expose tracking.
The existing access evaluator handles expiry, provider periods and grace dates;
there are no Stripe calls or persisted state changes during tracking.

- Inactive business, missing subscription, inactive/incompatible plan,
  pending checkout, suspended, expired, cancelled or no-access subscription:
  unavailable.
- Restricted access (including expired payment grace): unavailable, even though
  staff may retain read access.
- Full payment grace: available until the existing grace boundary.
- Scheduled cancellation: available only while full access lasts, then unavailable.
- Delivered and cancelled parcels: retain their public timeline with no new
  retention deadline, subject to the same business policy and existing purge.
- SERVICE businesses cannot expose parcels, including corrupt/legacy rows.
- Individual staff/owner account changes do not define tenant lifecycle. Tracking
  follows Business/subscription state, independent of actors and memberships.

All invalid or inaccessible lookups use the same 404 template, message and
security headers, without echoing the input or indicating any lifecycle reason.
This is response equivalence, not a constant-time database lookup guarantee.

## Abuse controls and deployment limits

No reusable limiter exists in this project. Before every POST lookup, a small
Django-cache fixed-window throttle allows 30 attempts per direct peer per minute.
Counters expire after two minutes. Keys contain a secret-key HMAC of the peer,
never the raw IP or tracking code. All attempts count, including invalid codes.
Cache failures return generic 429 without querying parcels; 429 includes
`Retry-After: 60`. GET only serves the blank form and performs no parcel lookup.

`LOGISTICS_TRACKING_CLIENT_IP_MODE=direct` uses a normalized socket peer and
ignores all forwarding headers. This is for direct ingress (including Local),
not a claim that a reverse proxy's socket address identifies the customer.
On Heroku Common Runtime, explicitly set the mode to `heroku`: the dyno must
only be reachable through the Heroku router. That router appends its observed
client IP to the right of `X-Forwarded-For`; tracking uses only that last value,
never a client-supplied left-hand value, `Forwarded`, or `X-Real-IP`. It does not
walk upstream CDN/proxy chains. Customers behind an upstream proxy share its
limit conservatively. Heroku mode requires the platform `DYNO` environment
variable. Missing/malformed identity denies POST with 429 before parcel lookup;
IPv4-mapped IPv6 addresses share their IPv4 counter. No general request IP
middleware or SERVICE security behavior is changed.

When `DEBUG=False`, tracking denies POST unless its selected cache backend is
shared Redis/Memcached with a location; LocMem remains available for Local.
Redis is included in normal deployment dependencies. Configure the dedicated
alias through `LOGISTICS_TRACKING_CACHE_*`; use one Redis primary, not a read
replica list. Redis connection/read timeouts are two seconds. Each environment
needs its own cache and prefix; all workers within that environment must share
the cache, prefix and Django SECRET_KEY. Never clear the entire cache for QA.
The opt-in pilot checks diagnose configuration; runtime protection does not
require those checks to be enabled. Fixed windows allow bursts across boundaries.
This bounded protection is not a general distributed abuse solution.

The native form posts back to `/logistics/track/` with a CSRF token and cookie.
The tracking response uses `Referrer-Policy: same-origin`: same-origin Origin
and HTTPS Referer checks work, while external sites receive no referrer.
`no-referrer` would make browser form POSTs send `Origin: null`; never add `null`
to trusted origins or exempt this view from CSRF. Keep `CSRF_TRUSTED_ORIGINS` as
exact supported origins and the existing `USE_X_FORWARDED_PROTO` HTTPS proxy
configuration. No tracking code is put in a URL or an external request.

For a real four-process atomic-counter test, set the private environment variable
`TRACKING_REDIS_TEST_URL` and run `python src/manage.py test
apps.logistics.test_tracking_shared_cache`. It uses a unique prefix and synthetic
identity, checks exactly 30 accepted attempts out of 40, verifies expiry, and
deletes only its own counter. Browser/deployed proxy tests are also required.
See [Heroku routing](https://devcenter.heroku.com/articles/http-routing) and
[Django referrer policy](https://docs.djangoproject.com/en/5.2/ref/middleware/#referrer-policy).

## Block 8

No code blocker is known for building on the projection. Block 8 scope still
needs definition. If it introduces public location/contact data, define explicit
customer-visible fields first. Resolve deployment-wide throttling/proxy policy
before higher public traffic or multiple workers. Any future API/PWA entry point
must reuse the same privacy/lifecycle policy and add appropriate abuse controls.
