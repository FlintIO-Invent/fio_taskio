# MotionMate Production Email Readiness

This runbook prepares MotionMate for production transactional email delivery.
It covers password resets, password-change confirmations, team invitations, customer request confirmations, internal business alerts, appointment confirmations, and invoice emails.

This does not add marketing email, newsletters, background workers, webhooks, or scheduled reminders.

## Current Email-Producing Flows

The current repository sends or prepares transactional email for:

- password reset
- password change confirmation
- business team invitation
- public service request customer confirmation
- public service request internal business alert
- public booking request customer receipt
- public booking request internal business alert
- appointment confirmation
- invoice email with PDF attachment

Local development uses the console email backend by default. Staging and production should use SMTP through a transactional provider.

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
7. Trigger a customer request confirmation email from `/crm/public_request/<business_slug>/`.
8. Trigger an internal business alert from `/crm/public_request/<business_slug>/`.
9. Trigger a public booking receipt and internal alert from `/book/<business_slug>/`.
10. Trigger an appointment confirmation email when a booking request is scheduled as an appointment.
11. Trigger an invoice email with a PDF attachment.
12. Confirm each email arrives in the expected inbox.
13. Confirm password reset and invitation links point to the intended MotionMate app URL.
14. Confirm customer-facing emails do not contain staff-only notes or internal-only data.
15. Confirm the invoice PDF attachment opens.
16. Confirm failed sends are logged safely by temporarily using invalid staging SMTP credentials.
17. Confirm logs do not contain passwords, reset tokens, SMTP credentials, API keys, or private DNS values.

No test-management command is required for this block. The safest staging test is to exercise the real transactional flows above because they also verify templates, links, attachments, and view-level failure behavior.

## MotionMate Pilot Email Runbook

Use this short runbook during the pilot smoke pass.

Check Heroku config vars without sharing secrets:

```bash
heroku config:get EMAIL_BACKEND --app <app-name>
heroku config:get EMAIL_HOST --app <app-name>
heroku config:get EMAIL_PORT --app <app-name>
heroku config:get EMAIL_USE_TLS --app <app-name>
heroku config:get EMAIL_USE_SSL --app <app-name>
heroku config:get EMAIL_TIMEOUT --app <app-name>
heroku config:get DEFAULT_FROM_EMAIL --app <app-name>
heroku config:get SERVER_EMAIL --app <app-name>
heroku config:get MOTIONMATE_SUPPORT_EMAIL --app <app-name>
heroku config:get MOTIONMATE_PUBLIC_BASE_URL --app <app-name>
```

Confirm `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` are set in Heroku, but do not paste or share their values.

Send a simple SMTP test email from Heroku:

```bash
heroku run "python src/manage.py shell -c \"from django.conf import settings; from django.core.mail import send_mail; send_mail('MotionMate test email', 'This is a one-time transactional email configuration test.', settings.DEFAULT_FROM_EMAIL, ['recipient@example.com'], fail_silently=False)\"" --app <app-name>
```

Replace `recipient@example.com` with an internal pilot-test inbox.

Trigger pilot-critical transactional flows:

- Password reset: open `/accounts/password-reset/`, submit a pilot user email, and verify the reset link uses the expected MotionMate app URL.
- Team invitation: as an owner/admin, open `/businesses/team/`, invite a test teammate, and verify the invite link uses the expected MotionMate app URL.
- Customer request confirmation: submit `/crm/public_request/<business_slug>/` for a pilot business and verify the customer receives the confirmation.
- Internal request alert: after the same public request submission, verify the business notification recipient receives the internal alert with the internal request link.
- Public booking receipt and alert: submit `/book/<business_slug>/` and verify the visitor receipt plus internal alert are delivered.
- Appointment confirmation: schedule or confirm an appointment from a booking request and verify the customer receives the appointment details.
- Invoice PDF email: from an invoice detail page, manually click the invoice email action and verify the client receives exactly one email with an opening PDF attachment.

Inspect Heroku logs safely:

```bash
heroku logs --tail --app <app-name>
```

Do not log, paste, screenshot, or share SMTP credentials, provider API keys, reset links, reset tokens, invitation links, passwords, or private DNS record values. When reporting an email failure, share only the flow name, timestamp, recipient domain if needed, and the safe error class/message.

If emails go to spam:

- Re-check SPF, DKIM, DMARC, return-path/bounce verification, and from-domain alignment in the provider dashboard.
- Send to a different internal mailbox to compare behavior.
- Review provider activity logs for delivery, bounce, suppression, or spam signals.

If links point to the wrong domain:

- Fix `MOTIONMATE_PUBLIC_BASE_URL`.
- Use the real app URL, not a marketing page.
- Remove any trailing slash from `MOTIONMATE_PUBLIC_BASE_URL`.
- Re-trigger password reset and invitation emails after changing the config var.

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
- Public booking receipt and internal alert arrive.
- Appointment confirmation email arrives.
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
