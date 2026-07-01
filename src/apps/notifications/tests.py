from types import SimpleNamespace
from unittest import mock

from django.core import mail
from django.test import SimpleTestCase, override_settings

from .emails import send_templated_email


class SendTemplatedEmailTests(SimpleTestCase):
    def _context(self):
        return {
            "user": SimpleNamespace(first_name="Alex", email="alex@example.com"),
            "email_title": "Your MotionMate password was changed",
            "support_email": "support@motionmate.test",
        }

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="MotionMate <noreply@motionmate.test>",
    )
    def test_send_templated_email_supports_html_attachments_and_reply_to(self):
        if hasattr(mail, "outbox"):
            mail.outbox.clear()

        sent = send_templated_email(
            subject_template="emails/password_change_subject.txt",
            body_template="emails/password_change_body.txt",
            html_template="emails/password_change_body.html",
            context=self._context(),
            recipient_list=["alex@example.com"],
            attachments=[("notice.txt", b"attached", "text/plain")],
            reply_to=["support@motionmate.test"],
            log_label="test helper",
        )

        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["alex@example.com"])
        self.assertEqual(message.reply_to, ["support@motionmate.test"])
        self.assertEqual(message.subject, "Your MotionMate password was changed")
        self.assertIn("Your MotionMate password was changed successfully.", message.body)
        self.assertTrue(any(alternative[1] == "text/html" for alternative in message.alternatives))
        self.assertEqual(len(message.attachments), 1)
        attachment = message.attachments[0]
        self.assertEqual(attachment.filename, "notice.txt")
        self.assertEqual(attachment.content, "attached")
        self.assertEqual(attachment.mimetype, "text/plain")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_templated_email_skips_invalid_recipients_and_logs_safely(self):
        if hasattr(mail, "outbox"):
            mail.outbox.clear()

        with self.assertLogs("apps.notifications.emails", level="INFO") as captured:
            sent = send_templated_email(
                subject_template="emails/password_change_subject.txt",
                body_template="emails/password_change_body.txt",
                context=self._context(),
                recipient_list=["not-an-email", ""],
                log_label="invalid recipient test",
            )

        self.assertFalse(sent)
        self.assertEqual(len(getattr(mail, "outbox", [])), 0)
        self.assertTrue(
            any("Skipping email notification with invalid recipient address." in message for message in captured.output)
        )
        self.assertTrue(
            any(
                "Skipping invalid recipient test email notification because no recipient is configured."
                in message
                for message in captured.output
            )
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_templated_email_logs_backend_failures_without_exception_text(self):
        with self.assertLogs("apps.notifications.emails", level="ERROR") as captured:
            with mock.patch(
                "apps.notifications.emails.EmailMultiAlternatives.send",
                side_effect=RuntimeError("SMTP unavailable password=secret-token"),
            ):
                sent = send_templated_email(
                    subject_template="emails/password_change_subject.txt",
                    body_template="emails/password_change_body.txt",
                    context=self._context(),
                    recipient_list=["alex@example.com"],
                    log_label="backend failure test",
                )

        self.assertFalse(sent)
        log_output = "\n".join(captured.output)
        self.assertIn("Failed to send backend failure test email notification.", log_output)
        self.assertNotIn("SMTP unavailable", log_output)
        self.assertNotIn("secret-token", log_output)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_templated_email_logs_zero_send_count_without_exception_text(self):
        with self.assertLogs("apps.notifications.emails", level="ERROR") as captured:
            with mock.patch(
                "apps.notifications.emails.EmailMultiAlternatives.send",
                return_value=0,
            ):
                sent = send_templated_email(
                    subject_template="emails/password_change_subject.txt",
                    body_template="emails/password_change_body.txt",
                    context=self._context(),
                    recipient_list=["alex@example.com"],
                    log_label="zero delivery test",
                )

        self.assertFalse(sent)
        log_output = "\n".join(captured.output)
        self.assertIn("Failed to send zero delivery test email notification.", log_output)
        self.assertNotIn("alex@example.com", log_output)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_templated_email_reraises_when_fail_safely_is_false(self):
        with self.assertLogs("apps.notifications.emails", level="ERROR"):
            with mock.patch(
                "apps.notifications.emails.EmailMultiAlternatives.send",
                side_effect=RuntimeError("SMTP unavailable"),
            ):
                with self.assertRaises(RuntimeError):
                    send_templated_email(
                        subject_template="emails/password_change_subject.txt",
                        body_template="emails/password_change_body.txt",
                        context=self._context(),
                        recipient_list=["alex@example.com"],
                        log_label="unsafe failure test",
                        fail_safely=False,
                    )
