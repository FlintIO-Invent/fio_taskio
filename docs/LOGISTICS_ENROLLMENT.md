# Logistics enrollment (Block 4)

## Direct pilot signup

With `LOGISTICS_AUTO_APPROVE_ALL=True`, public signup collects a new-account password
and confirmation. `LogisticsSignupForm` validates them with Django's existing password
policy; credentials never enter `LogisticsApplication`, decision audits or session
data. An applicant can choose the existing-account flow without entering a new
password. Registered emails always require the secure existing-account enrollment
process, even if a new password was submitted or the applicant is already logged in.
There is no public account-existence lookup.

`enroll_new_pilot_application` locks and rechecks the automatically approved current
revision and pilot configuration, then calls the same conversion routine as token
enrollment. It rejects converted applications and all existing identities, including
email races; failures roll back conversion while preserving the application for
review/recovery. Session-bound identical POST retries reuse their own application;
only its authenticated active owner can resume a converted workspace.

Success uses Django login, selects the current Business, and redirects to the
dashboard. A pending Logistics owner sees account-created/payment onboarding only,
including when the offering is still staged/inactive. No operational dashboard data
is queried. **Continue to payment** posts to the existing approved Logistics checkout
endpoint. Subscription guards still block operational reads and writes; annual-only,
no-trial billing and authoritative webhook activation are unchanged. SERVICE dashboard
and registration behavior are unchanged.

Strict mode, existing accounts, manual review and administrative recovery retain the
token architecture below. Strict-mode application submission does not collect or
retain passwords and never provisions, even for a strict automatically approved
application.

## Secure enrollment links

An authorized application reviewer uses **Enrollment link** in Django Admin to
issue or replace a link for an APPROVED application at its displayed current
revision. Issuing requires POST and the existing application change permission.
Revocation uses the same permission. No email or external notification is sent.
The reviewer must deliver the link privately to the application's approved email
address; possession of this link is the new applicant's email verification.

Each grant uses 32 random bytes (256 bits), stores only its SHA-256 digest, expires
seven days after issuance, and records its application/revision, issuer, revocation
and consumption time. Only the issuance response displays the raw link. Enrollment
and issuance pages disable caching and use `Referrer-Policy: no-referrer`. Deployment
access logs should redact enrollment paths, as with other bearer-token URLs.
A replacement revokes earlier grants. Every new decision, including same-revision
reapproval, revokes grants. Material changes reevaluate under the existing rules
and revoke grants even when the new revision is automatically approved.

## Identity and conversion

`apps.logistics.enrollment.enroll_application` is the reusable domain entry point.
It locks the application, then its grant, and rechecks approval, evaluated/approved
revision, expiry and revocation. A new email needs a password validated by existing
Django password validators. Existing emails require the authenticated matching,
active User; the browser can authenticate with that account's password directly,
including accounts without a workspace. Email matching alone never reuses an
account. Ambiguous case-insensitive matches fail closed. Passwords and existing
profile settings are never overwritten.

The service locks the User before checking the existing active-member/active-business
conflict rule. A conflicting active workspace blocks conversion and asks for review.
Inactive membership/business behavior follows the existing product policy. Normal
SERVICE registration is unchanged. Database unique email conflicts require sign-in
and retry; they never fall back to unverified reuse.

One transaction creates a LOGISTICS Business, OWNER BusinessUser, required
SaaSUserProfile, and the existing BusinessSubscription in `pending_checkout`, with
Logistics family, yearly interval, selected USD/EUR currency and no trial. Business
name, email, phone, address, country, timezone and currency come from the approved
application. New User names/company map to the existing 30/100-character field
limits; full original values remain on the application. Operational inputs and
other sales/application data remain on the application. Existing profile values
are preserved; new profiles receive business and billing defaults.

The subscription is staged against the existing Logistics plan even if inactive
and unpriced. No Price, checkout, customer or provider subscription is created.
Pending status denies operational access, including when the plan is activated.
Block 5 must enforce Block 2's offering activation, annual Price and billing policy
before starting checkout. This block introduces no trial or activation lifecycle.

The application stores a unique protected Business link, protected enrolled User,
conversion timestamp and revision. A database check requires the conversion fields
to be either all absent or all present. Model saves cannot inject these fields;
only the service writes the complete linkage. The application and User locks,
unique Business link, subscription OneToOne and atomic writes prevent duplicates.
Only the authenticated converted owner can retry a consumed grant and receive the
same records. Expired, revoked, stale or anonymously replayed grants remain denied.
A failed transaction leaves the grant unused and no partial conversion.

## Lifecycle and verification

Application inspection includes conversion IDs/revision/time and subscription
presence, without raw grants or contact details. Admin shows readonly conversion
and grant lifecycle history. Tenant inventory explicitly registers the protected
application relation. Ordinary User/Business deletion is protected by the linkage.
Block 11 lets the existing controlled purge release the Business FK into a retained
`business_id_snapshot` only after all original safety gates pass. Application
inputs, decisions, grants and the enrolled User survive; grants are revoked and
purged conversions cannot enroll again. Retention release rolls back with any
failed purge. Matching email/name remains neither ownership nor a selector.

SQLite tests exercise authorization, identity, idempotent retries, rollback,
constraints, browser/admin security, inventory and pending access. PostgreSQL-only
transaction tests exercise simultaneous requests and conflicting applications for
one User. PostgreSQL is required to verify row-lock concurrency; SQLite does not
provide that verification.

## Block 5 checkout

Block 5 implements checkout from the authenticated converted application through the
shared Stripe pipeline; see [LOGISTICS_CHECKOUT.md](LOGISTICS_CHECKOUT.md). Supply
commercial prices, configure supported annual USD/EUR Stripe Prices and activate the
offering through its validated Admin form before accepting payments.
Keep the existing Logistics Customer Portal disabled until its configuration can
prove vertical and annual-only switching restrictions. Decide pilot territories
and any automated applicant-email delivery separately. Eligibility reasons are
advisory with the pilot default `LOGISTICS_AUTO_APPROVE_ALL=True`; False restores
strict review, including empty territory defaults. No Parcel/PWA/API/scanner work is added.
