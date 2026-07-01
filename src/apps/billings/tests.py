from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.crm.models import ActivityLog, BusinessService, Client

from .models import Invoice, InvoiceLine


class BillingBusinessScopingTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Alpha Workspace",
            slug="alpha-workspace",
            currency="XCD",
            tax_rate=Decimal("6.50"),
            invoice_prefix="CLR",
            invoice_start_number=250,
        )
        self.other_business = Business.objects.create(
            name="Bravo Workspace",
            slug="bravo-workspace",
            currency="USD",
            tax_rate=Decimal("10.00"),
            invoice_prefix="BRV",
            invoice_start_number=100,
        )
        self.invoicing_plan = ClarivoPlan.objects.create(
            name="Billing Enabled",
            slug="billing-enabled-tests",
            allow_invoicing=True,
        )
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.invoicing_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        BusinessSubscription.objects.create(
            business=self.other_business,
            plan=self.invoicing_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        self.user = TaskIOUser.objects.create_user(
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
            password="testpass123",
        )
        self.other_user = TaskIOUser.objects.create_user(
            email="other@example.com",
            first_name="Other",
            last_name="User",
            password="testpass123",
        )
        self.staff_user = TaskIOUser.objects.create_user(
            email="staff@example.com",
            first_name="Staff",
            last_name="User",
            password="testpass123",
        )
        self.accountant_user = TaskIOUser.objects.create_user(
            email="accountant@example.com",
            first_name="Accountant",
            last_name="User",
            password="testpass123",
        )
        self.viewer_user = TaskIOUser.objects.create_user(
            email="viewer@example.com",
            first_name="Viewer",
            last_name="User",
            password="testpass123",
        )

        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        BusinessUser.objects.create(
            user=self.other_user,
            business=self.other_business,
            role=BusinessUser.Role.OWNER,
        )
        BusinessUser.objects.create(
            user=self.staff_user,
            business=self.business,
            role=BusinessUser.Role.STAFF,
        )
        BusinessUser.objects.create(
            user=self.accountant_user,
            business=self.business,
            role=BusinessUser.Role.ACCOUNTANT,
        )
        BusinessUser.objects.create(
            user=self.viewer_user,
            business=self.business,
            role=BusinessUser.Role.VIEWER,
        )

        self.client_record = Client.objects.create(
            business=self.business,
            first_name="Alicia",
            last_name="Client",
            email="alicia@example.com",
            phone="+1 721 555 0001",
            company_name="Alpha Co",
            street_address="12 Main Street",
        )
        self.other_client_record = Client.objects.create(
            business=self.other_business,
            first_name="Boris",
            last_name="Client",
            email="boris@example.com",
            phone="+1 721 555 0002",
            company_name="Bravo Co",
            street_address="34 Side Street",
        )
        self.business_service = BusinessService.objects.create(
            business=self.business,
            name="Septic Pumping",
            description="Scheduled septic pumping service",
            unit_price=Decimal("125.00"),
            tax_rate=Decimal("6.50"),
        )
        self.other_business_service = BusinessService.objects.create(
            business=self.other_business,
            name="Roof Inspection",
            description="Roof inspection service",
            unit_price=Decimal("175.00"),
            tax_rate=Decimal("10.00"),
        )
        self.unpriced_service = BusinessService.objects.create(
            business=self.business,
            name="Custom Follow-up",
            description="Custom follow-up service",
            unit_price=Decimal("0.00"),
            tax_rate=Decimal("6.50"),
        )
        self.start_time = timezone.now().replace(second=0, microsecond=0)
        self.appointment = Appointment.objects.create(
            business=self.business,
            client=self.client_record,
            service=self.business_service,
            staff_member=self.staff_user,
            title="Scheduled septic visit",
            start_time=self.start_time,
            end_time=self.start_time + timedelta(hours=2),
            location="12 Main Street",
        )
        self.other_appointment = Appointment.objects.create(
            business=self.other_business,
            client=self.other_client_record,
            service=self.other_business_service,
            staff_member=self.other_user,
            title="Other workspace visit",
            start_time=self.start_time,
            end_time=self.start_time + timedelta(hours=2),
            location="34 Side Street",
        )
        self.manual_name_appointment = Appointment.objects.create(
            business=self.business,
            client=self.client_record,
            service=None,
            service_name="Emergency Callout",
            staff_member=self.staff_user,
            title="Emergency visit",
            start_time=self.start_time + timedelta(days=1),
            end_time=self.start_time + timedelta(days=1, hours=1),
            location="Client warehouse",
        )
        self.unpriced_appointment = Appointment.objects.create(
            business=self.business,
            client=self.client_record,
            service=self.unpriced_service,
            staff_member=self.staff_user,
            title="Unpriced visit",
            start_time=self.start_time + timedelta(days=2),
            end_time=self.start_time + timedelta(days=2, hours=1),
            location="Client warehouse",
        )

        self.invoice = Invoice.objects.create(
            invoice_number="INV-ALPHA-001",
            business=self.business,
            client=self.client_record,
        )
        self.other_invoice = Invoice.objects.create(
            invoice_number="INV-BRAVO-001",
            business=self.other_business,
            client=self.other_client_record,
        )

    def _add_invoice_line(
        self,
        invoice: Invoice | None = None,
        *,
        description: str = "Scheduled septic pumping service",
        quantity: Decimal = Decimal("1.00"),
        unit_price: Decimal = Decimal("125.00"),
    ) -> InvoiceLine:
        invoice = invoice or self.invoice
        line = InvoiceLine.objects.create(
            invoice=invoice,
            description=description,
            quantity=quantity,
            unit_price=unit_price,
        )
        line.refresh_from_db()
        invoice.subtotal = line.line_total
        invoice.tax = Decimal("8.13")
        invoice.total = Decimal("133.13")
        invoice.save(update_fields=["subtotal", "tax", "total"])
        return line

    def _create_admin_user(self) -> TaskIOUser:
        admin_user = TaskIOUser.objects.create_user(
            email="admin-billing@example.com",
            first_name="Admin",
            last_name="Billing",
            password="testpass123",
        )
        BusinessUser.objects.create(
            user=admin_user,
            business=self.business,
            role=BusinessUser.Role.ADMIN,
        )
        return admin_user

    def test_invoice_list_only_shows_current_business_invoices(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("invoice_list"))

        self.assertEqual(response.status_code, 200)
        invoices = list(response.context["invoices"])
        self.assertEqual(invoices, [self.invoice])

    def test_invoice_detail_blocks_other_business_invoice(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("invoice_detail", args=[self.other_invoice.id]))

        self.assertEqual(response.status_code, 404)

    def test_owner_admin_staff_accountant_and_viewer_can_download_invoice_pdf(self):
        self._add_invoice_line()
        admin_user = self._create_admin_user()

        for user in [
            self.user,
            admin_user,
            self.staff_user,
            self.accountant_user,
            self.viewer_user,
        ]:
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(reverse("invoice_pdf_download", args=[self.invoice.id]))
                self.client.logout()

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/pdf")
                self.assertIn(
                    'filename="invoice-INV-ALPHA-001.pdf"', response["Content-Disposition"]
                )
                self.assertTrue(response.content.startswith(b"%PDF"))
                self.assertIn(b"INV-ALPHA-001", response.content)
                self.assertIn(b"XCD 133.13", response.content)

    def test_invoice_pdf_download_blocks_other_business_invoice(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("invoice_pdf_download", args=[self.other_invoice.id]))

        self.assertEqual(response.status_code, 404)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MOTIONMATE_PUBLIC_BASE_URL="https://www.motionmate.net/",
        MOTIONMATE_SUPPORT_EMAIL="support@motionmate.test",
    )
    def test_invoice_email_sends_pdf_attachment_and_tracks_delivery(self):
        mail.outbox.clear()
        self._add_invoice_line()
        self.business.email = "billing@alpha.test"
        self.business.phone = "+1 721 555 0101"
        self.business.save(update_fields=["email", "phone", "updated_at"])
        original_status = self.invoice.status
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_email_send", args=[self.invoice.id]),
            follow=True,
        )

        self.invoice.refresh_from_db()
        activity_log = ActivityLog.objects.get(
            client=self.client_record,
            action_type=ActivityLog.ActionType.EMAIL_SENT,
        )

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertContains(response, "Invoice emailed to alicia@example.com.")
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["alicia@example.com"])
        self.assertEqual(message.reply_to, ["billing@alpha.test"])
        self.assertIn("Invoice INV-ALPHA-001 from Alpha Workspace", message.subject)
        self.assertIn("MotionMate", message.body)
        self.assertIn("Hi Alicia Client", message.body)
        self.assertIn("Invoice number: INV-ALPHA-001", message.body)
        self.assertIn("Issue date:", message.body)
        self.assertIn("Amount due: XCD 133.13", message.body)
        self.assertIn("Attachment: invoice-INV-ALPHA-001.pdf", message.body)
        self.assertIn("billing@alpha.test", message.body)
        self.assertIn("+1 721 555 0101", message.body)
        self.assertNotIn(reverse("invoice_detail", args=[self.invoice.id]), message.body)
        self.assertNotIn("https://www.motionmate.net//", message.body)
        self.assertTrue(any(alternative[1] == "text/html" for alternative in message.alternatives))
        html_body = next(
            alternative[0]
            for alternative in message.alternatives
            if alternative[1] == "text/html"
        )
        self.assertIn("Invoice number:</strong> INV-ALPHA-001", html_body)
        self.assertNotIn(reverse("invoice_detail", args=[self.invoice.id]), html_body)
        self.assertEqual(len(message.attachments), 1)
        attachment_name, attachment_content, mimetype = message.attachments[0]
        self.assertEqual(attachment_name, "invoice-INV-ALPHA-001.pdf")
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(attachment_content.startswith(b"%PDF"))
        self.assertIn(b"INV-ALPHA-001", attachment_content)
        self.assertEqual(self.invoice.emailed_to, "alicia@example.com")
        self.assertIsNotNone(self.invoice.emailed_at)
        self.assertEqual(self.invoice.email_send_count, 1)
        self.assertEqual(self.invoice.status, original_status)
        self.assertEqual(activity_log.business, self.business)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        MOTIONMATE_SUPPORT_EMAIL="support@motionmate.test",
    )
    def test_invoice_email_failure_does_not_track_delivery_or_expose_smtp_error(self):
        mail.outbox.clear()
        self._add_invoice_line()
        original_status = self.invoice.status
        self.client.force_login(self.user)

        with self.assertLogs("apps.notifications.emails", level="ERROR") as captured:
            with mock.patch(
                "apps.notifications.emails.EmailMultiAlternatives.send",
                side_effect=RuntimeError("SMTP unavailable password=secret"),
            ):
                response = self.client.post(
                    reverse("invoice_email_send", args=[self.invoice.id]),
                    follow=True,
                )

        self.invoice.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertContains(response, "Invoice email could not be sent.")
        self.assertNotContains(response, "SMTP unavailable")
        self.assertNotContains(response, "password=secret")
        self.assertEqual(self.invoice.emailed_to, "")
        self.assertIsNone(self.invoice.emailed_at)
        self.assertEqual(self.invoice.email_send_count, 0)
        self.assertEqual(self.invoice.status, original_status)
        self.assertFalse(
            ActivityLog.objects.filter(
                client=self.client_record,
                action_type=ActivityLog.ActionType.EMAIL_SENT,
            ).exists()
        )
        self.assertTrue(
            any(
                "Failed to send invoice email notification." in message
                for message in captured.output
            )
        )
        self.assertFalse(any("SMTP unavailable" in message for message in captured.output))
        self.assertFalse(any("password=secret" in message for message in captured.output))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_staff_can_email_invoice(self):
        mail.outbox.clear()
        self._add_invoice_line()
        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse("invoice_email_send", args=[self.invoice.id]),
            follow=True,
        )

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertContains(response, "Invoice emailed to alicia@example.com.")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_invoice_email_fails_gracefully_when_client_email_missing(self):
        mail.outbox.clear()
        self.client_record.email = ""
        self.client_record.save(update_fields=["email", "updated_at"])
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_email_send", args=[self.invoice.id]),
            follow=True,
        )

        self.invoice.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertContains(response, "valid email address")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.invoice.emailed_to, "")
        self.assertIsNone(self.invoice.emailed_at)
        self.assertEqual(self.invoice.email_send_count, 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_invoice_email_blocks_other_business_invoice(self):
        mail.outbox.clear()
        self.client.force_login(self.user)

        response = self.client.post(reverse("invoice_email_send", args=[self.other_invoice.id]))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_viewer_cannot_email_invoice(self):
        mail.outbox.clear()
        self.client.force_login(self.viewer_user)

        response = self.client.post(reverse("invoice_email_send", args=[self.invoice.id]))

        self.assertRedirects(
            response,
            reverse("invoice_list"),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_appointment_created_invoice_supports_pdf_and_email(self):
        mail.outbox.clear()
        linked_invoice = Invoice.objects.create(
            invoice_number="INV-ALPHA-APPT",
            business=self.business,
            client=self.client_record,
            appointment=self.appointment,
        )
        self._add_invoice_line(linked_invoice)
        self.client.force_login(self.accountant_user)

        pdf_response = self.client.get(reverse("invoice_pdf_download", args=[linked_invoice.id]))
        email_response = self.client.post(reverse("invoice_email_send", args=[linked_invoice.id]))

        linked_invoice.refresh_from_db()

        self.assertEqual(pdf_response.status_code, 200)
        self.assertIn(b"INV-ALPHA-APPT", pdf_response.content)
        self.assertIn(b"Scheduled septic visit", pdf_response.content)
        self.assertRedirects(
            email_response,
            reverse("invoice_detail", args=[linked_invoice.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["alicia@example.com"])
        self.assertEqual(linked_invoice.email_send_count, 1)

    def test_invoice_create_from_client_sets_invoice_business(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_client", args=[self.client_record.id])
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )
        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(created_invoice.business, self.business)
        self.assertEqual(created_invoice.client, self.client_record)
        self.assertEqual(created_invoice.invoice_number, "CLR-0250")
        self.assertEqual(created_invoice.tax, Decimal("0.00"))

    def test_invoice_create_from_client_blocks_other_business_client(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("invoice_create_from_client", args=[self.other_client_record.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_invoice_create_page_only_lists_current_business_services(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("invoice_create_from_client", args=[self.client_record.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.business_service.name)
        self.assertContains(response, "$125.00")
        self.assertNotContains(response, self.other_business_service.name)

    def test_invoice_create_page_line_item_numbers_step_in_whole_units(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("invoice_create_from_client", args=[self.client_record.id])
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'name="quantity" value="" step="1.00" min="1.00" inputmode="numeric"',
            html,
        )
        self.assertIn('name="unit_price" value="" step="1.00" min="0"', html)
        self.assertNotIn('step="0.01"', html)
        self.assertIn("function isWholeUnitQuantity(value)", html)
        self.assertIn("quantityInput.value = '1.00';", html)

    def test_invoice_create_from_client_uses_service_snapshot_values(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_client", args=[self.client_record.id]),
            data={
                "service_id": [str(self.business_service.id)],
                "description": [""],
                "quantity": [""],
                "unit_price": [""],
            },
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )
        line = created_invoice.lines.get()

        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(line.service, self.business_service)
        self.assertEqual(line.description, self.business_service.description)
        self.assertEqual(line.quantity, Decimal("1.00"))
        self.assertEqual(line.unit_price, Decimal("125.00"))
        self.assertEqual(line.line_total, Decimal("125.00"))
        self.assertEqual(created_invoice.subtotal, Decimal("125.00"))
        self.assertEqual(created_invoice.tax, Decimal("8.13"))
        self.assertEqual(created_invoice.total, Decimal("133.13"))

    def test_invoice_create_from_client_allows_manual_line_item(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_client", args=[self.client_record.id]),
            data={
                "service_id": [""],
                "description": ["After-hours emergency callout"],
                "quantity": ["2"],
                "unit_price": ["75.00"],
            },
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )
        line = created_invoice.lines.get()

        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertIsNone(line.service)
        self.assertEqual(line.description, "After-hours emergency callout")
        self.assertEqual(line.quantity, Decimal("2.00"))
        self.assertEqual(line.unit_price, Decimal("75.00"))
        self.assertEqual(line.line_total, Decimal("150.00"))
        self.assertEqual(created_invoice.subtotal, Decimal("150.00"))
        self.assertEqual(created_invoice.tax, Decimal("9.75"))
        self.assertEqual(created_invoice.total, Decimal("159.75"))

    def test_invoice_create_from_appointment_prefills_context_on_get(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("invoice_create_from_appointment", args=[self.appointment.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create Invoice from Appointment")
        self.assertContains(response, reverse("appointment_detail", args=[self.appointment.id]))
        self.assertContains(response, self.business_service.description)
        self.assertContains(response, "Created from appointment")

    def test_invoice_create_from_appointment_sets_business_client_and_relation(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_appointment", args=[self.appointment.id]),
            data={
                "service_id": [str(self.business_service.id)],
                "description": [""],
                "quantity": ["1"],
                "unit_price": [""],
            },
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )

        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(created_invoice.business, self.business)
        self.assertEqual(created_invoice.client, self.appointment.client)
        self.assertEqual(created_invoice.appointment, self.appointment)
        self.assertIn("Created from appointment", created_invoice.notes)

    def test_invoice_create_from_appointment_blocks_other_business_appointment(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("invoice_create_from_appointment", args=[self.other_appointment.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_invoice_create_from_appointment_uses_service_snapshot_values(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_appointment", args=[self.appointment.id]),
            data={
                "service_id": [str(self.business_service.id)],
                "description": [""],
                "quantity": [""],
                "unit_price": [""],
            },
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )
        line = created_invoice.lines.get()

        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(line.service, self.business_service)
        self.assertEqual(line.description, self.business_service.description)
        self.assertEqual(line.unit_price, Decimal("125.00"))
        self.assertEqual(created_invoice.appointment, self.appointment)

    def test_invoice_create_from_appointment_allows_manual_line_item(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_appointment", args=[self.manual_name_appointment.id]),
            data={
                "service_id": [""],
                "description": ["Emergency Callout"],
                "quantity": ["2"],
                "unit_price": ["85.00"],
            },
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )
        line = created_invoice.lines.get()

        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertIsNone(line.service)
        self.assertEqual(line.description, "Emergency Callout")
        self.assertEqual(line.unit_price, Decimal("85.00"))
        self.assertEqual(created_invoice.appointment, self.manual_name_appointment)

    def test_invoice_create_from_appointment_allows_manual_price_for_unpriced_service(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_appointment", args=[self.unpriced_appointment.id]),
            data={
                "service_id": [str(self.unpriced_service.id)],
                "description": [self.unpriced_service.description],
                "quantity": ["1"],
                "unit_price": ["95.00"],
            },
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )
        line = created_invoice.lines.get()

        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(line.service, self.unpriced_service)
        self.assertEqual(line.description, self.unpriced_service.description)
        self.assertEqual(line.unit_price, Decimal("95.00"))
        self.assertEqual(line.line_total, Decimal("95.00"))

    def test_invoice_create_from_appointment_redirects_when_linked_invoice_exists(self):
        linked_invoice = Invoice.objects.create(
            invoice_number="CLR-0249",
            business=self.business,
            client=self.client_record,
            appointment=self.appointment,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("invoice_create_from_appointment", args=[self.appointment.id]),
            follow=True,
        )

        self.assertRedirects(response, reverse("invoice_detail", args=[linked_invoice.id]))
        self.assertContains(response, linked_invoice.invoice_number)

    def test_invoice_create_rejects_service_from_other_business(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_client", args=[self.client_record.id]),
            data={
                "service_id": [str(self.other_business_service.id)],
                "description": ["Tampered line"],
                "quantity": ["1"],
                "unit_price": ["999.00"],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "selected service is not available in this workspace")
        self.assertFalse(
            Invoice.objects.filter(
                business=self.business,
                invoice_number="CLR-0250",
            ).exists()
        )

    def test_invoice_status_change_logs_activity_for_current_business(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_change_status", args=[self.invoice.id]),
            data={"status": Invoice.Status.SENT},
        )

        self.invoice.refresh_from_db()
        activity_log = ActivityLog.objects.get(
            client=self.client_record, action_type=ActivityLog.ActionType.STATUS_CHANGED
        )

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertEqual(self.invoice.status, Invoice.Status.SENT)
        self.assertEqual(activity_log.business, self.business)

    def test_invoice_routes_redirect_owner_to_subscription_when_invoicing_is_not_included(self):
        locked_plan = ClarivoPlan.objects.create(
            name="CRM Only",
            slug="crm-only-billing-tests",
            allow_invoicing=False,
        )
        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = locked_plan
        subscription.save(update_fields=["plan", "updated_at"])

        self.client.force_login(self.user)

        response = self.client.get(reverse("invoice_list"), follow=True)

        self.assertRedirects(response, reverse("business_subscription"))
        self.assertContains(response, "Invoicing is not included in the current workspace plan")

    def test_invoice_create_from_appointment_redirects_owner_to_subscription_when_locked(self):
        locked_plan = ClarivoPlan.objects.create(
            name="CRM Only Appointment Lock",
            slug="crm-only-appointment-billing-tests",
            allow_invoicing=False,
            allow_appointments=True,
        )
        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = locked_plan
        subscription.save(update_fields=["plan", "updated_at"])

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("invoice_create_from_appointment", args=[self.appointment.id]),
            follow=True,
        )

        self.assertRedirects(response, reverse("business_subscription"))
        self.assertContains(response, "Invoicing is not included in the current workspace plan")

    def test_staff_can_view_invoices(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("invoice_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.invoice.invoice_number)

    def test_staff_can_open_invoice_create_page(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(
            reverse("invoice_create_from_client", args=[self.client_record.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create Invoice from Client")

    def test_staff_can_open_invoice_create_from_appointment_page(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(
            reverse("invoice_create_from_appointment", args=[self.appointment.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create Invoice from Appointment")

    def test_staff_and_accountant_can_open_invoice_edit_page(self):
        for user in [self.staff_user, self.accountant_user]:
            with self.subTest(user=user.email):
                self.client.force_login(user)

                response = self.client.get(reverse("invoice_edit", args=[self.invoice.id]))

                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_viewer_cannot_edit_invoice(self):
        self.client.force_login(self.viewer_user)

        response = self.client.get(reverse("invoice_edit", args=[self.invoice.id]), follow=True)

        self.assertRedirects(response, reverse("invoice_list"))
        self.assertContains(response, "You do not have permission to manage invoices.")

    def test_viewer_cannot_open_invoice_create_from_appointment_page(self):
        self.client.force_login(self.viewer_user)

        response = self.client.get(
            reverse("invoice_create_from_appointment", args=[self.appointment.id]),
            follow=True,
        )

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertContains(response, "You do not have permission to manage invoices.")

    def test_staff_and_accountant_can_create_invoice_from_client(self):
        for user in [self.staff_user, self.accountant_user]:
            with self.subTest(user=user.email):
                self.client.force_login(user)

                response = self.client.post(
                    reverse("invoice_create_from_client", args=[self.client_record.id]),
                    data={
                        "service_id": [str(self.business_service.id)],
                        "description": [""],
                        "quantity": ["1"],
                        "unit_price": [""],
                    },
                )

                created_invoice = Invoice.objects.get(
                    business=self.business,
                    invoice_number="CLR-0250",
                )

                self.assertRedirects(
                    response,
                    reverse("invoice_detail", args=[created_invoice.id]),
                )
                self.assertEqual(created_invoice.client, self.client_record)
                created_invoice.delete()
                self.client.logout()

    def test_invoice_edit_page_line_item_numbers_step_in_whole_units(self):
        self._add_invoice_line()
        self.client.force_login(self.user)

        response = self.client.get(reverse("invoice_edit", args=[self.invoice.id]))
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'name="quantity" value="1.00" step="1.00" min="1.00" inputmode="numeric"',
            html,
        )
        self.assertIn(
            'name="new_quantity" step="1.00" min="1.00" inputmode="numeric" disabled',
            html,
        )
        self.assertIn('name="unit_price" value="125.00" step="1.00" min="0"', html)
        self.assertNotIn('step="0.01"', html)
        self.assertIn("function isWholeUnitQuantity(value)", html)
        self.assertIn(
            "setInputValue(lineItem, 'quantity', 'new_quantity', '1.00');",
            html,
        )

    def test_admin_can_create_invoice_from_appointment(self):
        admin_user = self._create_admin_user()
        self.client.force_login(admin_user)

        response = self.client.post(
            reverse("invoice_create_from_appointment", args=[self.appointment.id]),
            data={
                "service_id": [str(self.business_service.id)],
                "description": [""],
                "quantity": ["1"],
                "unit_price": [""],
            },
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )

        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(created_invoice.appointment, self.appointment)

    def test_accountant_can_create_invoice_from_appointment(self):
        self.client.force_login(self.accountant_user)

        response = self.client.post(
            reverse("invoice_create_from_appointment", args=[self.appointment.id]),
            data={
                "service_id": [str(self.business_service.id)],
                "description": [""],
                "quantity": ["1"],
                "unit_price": [""],
            },
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )

        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(created_invoice.appointment, self.appointment)

    def test_viewer_invoice_detail_hides_edit_and_status_actions(self):
        self.client.force_login(self.viewer_user)

        response = self.client.get(reverse("invoice_detail", args=[self.invoice.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("invoice_edit", args=[self.invoice.id]))
        self.assertNotContains(response, reverse("invoice_change_status", args=[self.invoice.id]))

    def test_invoice_detail_links_back_to_appointment_when_linked(self):
        self.invoicing_plan.allow_appointments = True
        self.invoicing_plan.save(update_fields=["allow_appointments", "updated_at"])
        linked_invoice = Invoice.objects.create(
            invoice_number="INV-ALPHA-APPT",
            business=self.business,
            client=self.client_record,
            appointment=self.appointment,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("invoice_detail", args=[linked_invoice.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("appointment_detail", args=[self.appointment.id]))
        self.assertContains(response, self.appointment.title)

    def test_staff_invoice_list_is_shown_in_dashboard_navigation(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("invoice_list"))
        self.assertNotContains(response, "Invoices Restricted")

    def test_invoice_numbers_are_unique_per_business(self):
        Invoice.objects.create(
            invoice_number="SHARED-0001",
            business=self.business,
            client=self.client_record,
        )
        cross_business_invoice = Invoice.objects.create(
            invoice_number="SHARED-0001",
            business=self.other_business,
            client=self.other_client_record,
        )

        self.assertEqual(cross_business_invoice.business, self.other_business)

        with self.assertRaises(ValidationError):
            Invoice.objects.create(
                invoice_number="SHARED-0001",
                business=self.business,
                client=self.client_record,
            )

    def test_invoice_rejects_linked_appointment_from_other_business(self):
        invoice = Invoice(
            invoice_number="INV-BAD-APPT",
            business=self.business,
            client=self.client_record,
            appointment=self.other_appointment,
        )

        with self.assertRaises(ValidationError):
            invoice.full_clean()

    def test_invoice_rejects_linked_appointment_for_other_client(self):
        mismatch_client = Client.objects.create(
            business=self.business,
            first_name="Mismatch",
            last_name="Client",
            email="mismatch@example.com",
            phone="+1 721 555 9090",
            company_name="Mismatch Co",
            street_address="90 Other Street",
        )
        invoice = Invoice(
            invoice_number="INV-BAD-CLIENT",
            business=self.business,
            client=mismatch_client,
            appointment=self.appointment,
        )

        with self.assertRaises(ValidationError):
            invoice.full_clean()

    def test_invoice_edit_recalculates_tax_from_business_rate(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_edit", args=[self.invoice.id]),
            data={
                "notes": "Updated invoice",
                "new_description": ["Service call"],
                "new_quantity": ["2"],
                "new_unit_price": ["100.00"],
            },
        )

        self.invoice.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertEqual(self.invoice.subtotal, Decimal("200.00"))
        self.assertEqual(self.invoice.tax, Decimal("13.00"))
        self.assertEqual(self.invoice.total, Decimal("213.00"))

    def test_invoice_edit_uses_current_business_service_snapshot_values(self):
        line = InvoiceLine.objects.create(
            invoice=self.invoice,
            description="Old line",
            quantity=Decimal("1.00"),
            unit_price=Decimal("50.00"),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_edit", args=[self.invoice.id]),
            data={
                "notes": "Updated invoice",
                "line_id": [str(line.id)],
                "service_id": [str(self.business_service.id)],
                "description": ["Tampered description"],
                "quantity": ["2"],
                "unit_price": ["999.00"],
            },
        )

        self.invoice.refresh_from_db()
        line.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertEqual(line.service, self.business_service)
        self.assertEqual(line.description, self.business_service.description)
        self.assertEqual(line.quantity, Decimal("2.00"))
        self.assertEqual(line.unit_price, Decimal("125.00"))
        self.assertEqual(line.line_total, Decimal("250.00"))
        self.assertEqual(self.invoice.subtotal, Decimal("250.00"))
        self.assertEqual(self.invoice.tax, Decimal("16.25"))
        self.assertEqual(self.invoice.total, Decimal("266.25"))

    def test_invoice_edit_rejects_service_from_other_business(self):
        line = InvoiceLine.objects.create(
            invoice=self.invoice,
            description="Existing line",
            quantity=Decimal("1.00"),
            unit_price=Decimal("50.00"),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_edit", args=[self.invoice.id]),
            data={
                "notes": "Updated invoice",
                "line_id": [str(line.id)],
                "service_id": [str(self.other_business_service.id)],
                "description": ["Tampered description"],
                "quantity": ["2"],
                "unit_price": ["999.00"],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "selected service is not available in this workspace")
        line.refresh_from_db()
        self.assertEqual(line.description, "Existing line")
        self.assertEqual(line.unit_price, Decimal("50.00"))

    def test_invoice_edit_preserves_existing_service_snapshot_when_service_is_unchanged(self):
        line = InvoiceLine.objects.create(
            invoice=self.invoice,
            service=self.business_service,
            description="Quoted septic pumping service",
            quantity=Decimal("1.00"),
            unit_price=Decimal("110.00"),
        )
        self.business_service.description = "Updated service description"
        self.business_service.unit_price = Decimal("140.00")
        self.business_service.save()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_edit", args=[self.invoice.id]),
            data={
                "notes": "Keep the original quote",
                "line_id": [str(line.id)],
                "service_id": [str(self.business_service.id)],
                "description": ["Tampered description"],
                "quantity": ["2"],
                "unit_price": ["140.00"],
            },
        )

        self.invoice.refresh_from_db()
        line.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertEqual(line.service, self.business_service)
        self.assertEqual(line.description, "Quoted septic pumping service")
        self.assertEqual(line.unit_price, Decimal("110.00"))
        self.assertEqual(line.quantity, Decimal("2.00"))
        self.assertEqual(line.line_total, Decimal("220.00"))
        self.assertEqual(self.invoice.subtotal, Decimal("220.00"))
        self.assertEqual(self.invoice.tax, Decimal("14.30"))
        self.assertEqual(self.invoice.total, Decimal("234.30"))

    def test_invoice_edit_refreshes_existing_service_snapshot_when_reselected_intentionally(self):
        line = InvoiceLine.objects.create(
            invoice=self.invoice,
            service=self.business_service,
            description="Quoted septic pumping service",
            quantity=Decimal("1.00"),
            unit_price=Decimal("110.00"),
        )
        self.business_service.description = "Updated service description"
        self.business_service.unit_price = Decimal("140.00")
        self.business_service.save()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_edit", args=[self.invoice.id]),
            data={
                "notes": "Refresh the quote from the saved service",
                "line_id": [str(line.id)],
                "service_id": [str(self.business_service.id)],
                "description": [self.business_service.description],
                "quantity": ["2"],
                "unit_price": [str(self.business_service.unit_price)],
            },
        )

        self.invoice.refresh_from_db()
        line.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertEqual(line.description, "Updated service description")
        self.assertEqual(line.unit_price, Decimal("140.00"))
        self.assertEqual(line.quantity, Decimal("2.00"))
        self.assertEqual(line.line_total, Decimal("280.00"))
        self.assertEqual(self.invoice.subtotal, Decimal("280.00"))
        self.assertEqual(self.invoice.tax, Decimal("18.20"))
        self.assertEqual(self.invoice.total, Decimal("298.20"))

    def test_viewer_cannot_change_invoice_status(self):
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            reverse("invoice_change_status", args=[self.invoice.id]),
            data={"status": Invoice.Status.SENT},
            follow=True,
        )

        self.invoice.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_list"))
        self.assertContains(response, "You do not have permission to manage invoices.")
        self.assertEqual(self.invoice.status, Invoice.Status.DRAFT)

    def test_staff_and_accountant_can_change_invoice_status(self):
        for user in [self.staff_user, self.accountant_user]:
            with self.subTest(user=user.email):
                self.invoice.status = Invoice.Status.DRAFT
                self.invoice.save(update_fields=["status"])
                self.client.force_login(user)

                response = self.client.post(
                    reverse("invoice_change_status", args=[self.invoice.id]),
                    data={"status": Invoice.Status.SENT},
                )

                self.invoice.refresh_from_db()

                self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
                self.assertEqual(self.invoice.status, Invoice.Status.SENT)
                self.client.logout()
