# MotionMate Production Email Readiness

This runbook prepares MotionMate for production transactional email delivery.
It covers password resets, password-change confirmations, team invitations, customer request confirmations, internal business alerts, appointment confirmations, and invoice emails.

This does not add marketing email, newsletters, background workers, webhooks, or scheduled reminders.

## Provider Choice

Use a transactional email provider for staging and production.

Recommended pilot provider:

- Postmark

Acceptable alternatives if the project owner chooses differently:

- Mailgun
- SendGrid
- Brevo
- Amazon SES

Do not use Gmail SMTP for production app email. Gmail is built for mailbox use, not application delivery. It can throttle or block transactional traffic, has weaker operational controls for domain authentication and bounce handling, and makes production deliverability/debugging harder than a provider designed for app email.

## Required Environment Variables

Store these in the production platform environment configuration, not in the repository.

```dotenv
MOTIONMATE_PUBLIC_BASE_URL=https://www.motionmate.net
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_TIMEOUT=10
DEFAULT_FROM_EMAIL=MotionMate <noreply@motionmate.net>
SERVER_EMAIL=MotionMate System <system@motionmate.net>
MOTIONMATE_SUPPORT_EMAIL=support@motionmate.net
```

Notes:

- `MOTIONMATE_PUBLIC_BASE_URL` must be the real deployed MotionMate app URL.
- `MOTIONMATE_PUBLIC_BASE_URL` must not have a trailing slash.
- `EMAIL_HOST` comes from the selected provider dashboard.
- `EMAIL_HOST_USER` comes from the selected provider dashboard.
- `EMAIL_HOST_PASSWORD` must be stored only in production or staging environment config.
- `EMAIL_PORT=587`, `EMAIL_USE_TLS=True`, and `EMAIL_USE_SSL=False` are the recommended SMTP defaults unless the provider instructs otherwise.
- `EMAIL_TIMEOUT=10` keeps slow SMTP connections from blocking requests indefinitely.
- `DEFAULT_FROM_EMAIL` is the visible sender identity for transactional email.
- `SERVER_EMAIL` is used for server-originated email.
- `MOTIONMATE_SUPPORT_EMAIL` is shown in support/security email copy.

## DNS Readiness

The selected provider must verify `motionmate.net` before production sending.
Configure the records in the DNS provider for `motionmate.net`.

Expected record types:

- SPF
- DKIM
- DMARC
- Return-Path or bounce domain, if required by the provider

Do not invent DNS values. The exact hostnames, record types, and values must come from the chosen provider dashboard.

Domain verification process:

1. Add `motionmate.net` as a sending domain in the provider dashboard.
2. Add the provider-generated DNS records at the DNS host for `motionmate.net`.
3. Wait for DNS propagation.
4. Use the provider dashboard verification button/status page.
5. Confirm SPF and DKIM pass for the sending domain.
6. Confirm a DMARC policy exists for the domain.
7. Confirm the provider's return-path or bounce domain is verified if it requires one.

## Staging Send Checklist

Run this on staging before production launch.

1. Set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`.
2. Set the provider SMTP `EMAIL_HOST`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD`.
3. Set `EMAIL_PORT=587`, `EMAIL_USE_TLS=True`, and `EMAIL_USE_SSL=False`, unless the provider requires different values.
4. Set `MOTIONMATE_PUBLIC_BASE_URL` to the staging app URL, or to `https://www.motionmate.net` if testing against the production domain.
5. Trigger a password reset email.
6. Trigger a team invitation email.
7. Trigger a customer request confirmation email from the public request/booking flow.
8. Trigger an internal business alert from the public request/booking flow.
9. Trigger an appointment confirmation email if appointments are enabled for the staging scope.
10. Trigger an invoice email with a PDF attachment.
11. Confirm each email arrives in the expected inbox.
12. Confirm password reset and invitation links point to the intended MotionMate app URL.
13. Confirm customer-facing emails do not contain staff-only notes or internal-only data.
14. Confirm the invoice PDF attachment opens.
15. Confirm failed sends are logged safely by temporarily using invalid staging SMTP credentials.
16. Confirm logs do not contain passwords, reset tokens, SMTP credentials, API keys, or private DNS values.

No test-management command is required for this block. The safest staging test is to exercise the real transactional flows above because they also verify templates, links, attachments, and view-level failure behavior.

## Production Launch Checklist

Complete this before enabling production email delivery for real users.

- Domain is verified in the provider dashboard.
- SPF passes for `motionmate.net`.
- DKIM passes for `motionmate.net`.
- DMARC exists for `motionmate.net`.
- Return-Path or bounce domain is verified if required by the provider.
- `DEFAULT_FROM_EMAIL=MotionMate <noreply@motionmate.net>` works.
- `SERVER_EMAIL=MotionMate System <system@motionmate.net>` is configured.
- `MOTIONMATE_SUPPORT_EMAIL=support@motionmate.net` routes to a monitored inbox.
- Reply-to/support routing works for customer and invoice conversations.
- Password reset email arrives.
- Password reset link points to `https://www.motionmate.net`.
- Team invitation email arrives.
- Invitation link points to `https://www.motionmate.net`.
- Customer request confirmation email arrives.
- Internal business alert email arrives.
- Appointment confirmation email arrives if appointments are in launch scope.
- Invoice email arrives with a PDF attachment.
- Invoice PDF attachment opens.
- `EMAIL_TIMEOUT=10` is configured.
- `MOTIONMATE_PUBLIC_BASE_URL=https://www.motionmate.net` is configured with no trailing slash.
- `DEBUG=False` is configured.
- `ALLOWED_HOSTS` includes the production host.
- `CSRF_TRUSTED_ORIGINS` includes the production HTTPS origin.
- No SMTP passwords, provider API keys, tokens, or DNS private values are committed to the repository.
- Production logs do not expose SMTP secrets, passwords, reset tokens, or provider credentials.

## Troubleshooting

- If links point to `testserver`, localhost, or a staging host, fix `MOTIONMATE_PUBLIC_BASE_URL`.
- If links contain double slashes after the host, remove the trailing slash from `MOTIONMATE_PUBLIC_BASE_URL`.
- If email is printed to logs instead of delivered, confirm `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`.
- If all sends fail, confirm provider SMTP host, username, password, port, TLS/SSL settings, and domain verification.
- If messages land in spam, re-check SPF, DKIM, DMARC, from-domain alignment, and provider reputation guidance.
- If invitation email fails during launch, use the existing manual fallback invitation link while SMTP settings are corrected.
