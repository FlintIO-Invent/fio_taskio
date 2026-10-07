# Logistics checkout approval reconciliation

Logistics Checkout Sessions and their Stripe subscriptions carry the application
ID, approved revision and immutable approval decision ID. A fresh approval decision
requires fresh checkout authorization, including when the revision is unchanged.
SERVICE checkout metadata, trial behavior and idempotency keys are unchanged.

Checkout locks the application before the subscription and checks current approval,
conversion revision, business snapshot, active enrolled owner, offering, currency,
annual interval and review hold before creating or reusing a session. Legacy sessions
without the binding must be expired before replacement. A failed provider retrieval
or expiration blocks replacement; retries keep the same Stripe idempotency key.

Recording a decision invalidates the existing session locally and attempts to expire
it after the database transaction commits. Provider failure never restores local
eligibility. The session ID is retained for retries and payment correlation. Material
changes invalidate the conversion revision even when the pilot policy approves the
new application revision. Reapproval of an unchanged, unpaid enrollment can create a
new session after expiration of the old one.

A late successful checkout, subscription or invoice event with stale/missing approval
metadata is acknowledged and deduplicated, but keeps the subscription suspended with
`logistics_approval_review_required=True`. Provider identities and billing dates remain
available for reconciliation. The webhook ledger records the need for admin review.
No activation/recovery notification is sent. The hold denies operational access even
with the local billing bypass, and future success events and reapproval cannot clear
it after a provider subscription is linked. Approval changes on a paid subscription
also suspend access immediately.

An administrator must review the application, revision, enrollment and Stripe payment
(including whether a refund/cancellation is needed). The subscription admin exposes
the hold in its list/filter/form. Access can resume only after the administrator clears
the hold and reconciles the subscription's status and provider approval metadata with
the current approval decision. No automatic refund, cancellation of a paid subscription
or payment replay is introduced by this change.
