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
processors. It escapes all public text and sets no-store, no-referrer and
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

Forwarded headers are ignored because there is no application-level proxy trust
policy. Behind a proxy, the direct peer limit may be shared by customers. Verify
that a trusted server/proxy chain supplies the correct `REMOTE_ADDR`; never trust
arbitrary client-supplied forwarding headers. The default local memory cache
protects each process separately, and fixed windows allow bursts across boundaries.
Block 11 configures a dedicated shared cache through `LOGISTICS_TRACKING_CACHE_*`
and checks for Redis/Memcached atomic add/incr in opt-in pilot deployment checks.
All workers must share the cache, key prefix and Django SECRET_KEY. An independent
edge limit is useful additional protection; it does not change the application
counter. This bounded protection is not a general distributed abuse solution.

## Block 8

No code blocker is known for building on the projection. Block 8 scope still
needs definition. If it introduces public location/contact data, define explicit
customer-visible fields first. Resolve deployment-wide throttling/proxy policy
before higher public traffic or multiple workers. Any future API/PWA entry point
must reuse the same privacy/lifecycle policy and add appropriate abuse controls.
