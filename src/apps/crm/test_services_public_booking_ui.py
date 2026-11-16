"""Public presentation and payload acceptance remain the server's existing contract."""

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.appointments.models import Appointment
from apps.businesses.test_service_allowances import ServicesFixture
from apps.crm.models import Lead
from apps.crm.test_services_dashboard_ui import assert_disposable


class PublicBookingPresentationTests(ServicesFixture, TestCase):
    def setUp(self):
        assert_disposable()
        super().setUp()
        self.url = reverse("public_booking", args=[self.business.slug])

    def test_form_hooks_review_and_error_payload(self):
        page = self.client.get(self.url)
        for hook in (
            "public-booking-slot-data",
            "public-booking-address-data",
            "data-booking-review",
            "services-public-booking.js",
            'data-preferred-date-id="id_preferred_date"',
        ):
            self.assertContains(page, hook)
        page = self.client.post(self.url, {"booking_intent": "book_now"})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "data-booking-error-summary")
        self.assertContains(page, "id_service_errors")
        self.assertEqual(Appointment.objects.count(), 0)

    def test_direct_booking_and_retry_keep_original_records_and_generic_outcome(self):
        payload = self.payload()
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 302)
        item = Appointment.objects.get()
        self.assertEqual(item.status, "scheduled")
        self.assertEqual(item.source_lead, Lead.objects.get())
        self.client.post(self.url, payload)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 1)
        page = self.client.get(response.url)
        self.assertNotIn("appointment", page.context)
        self.assertNotContains(page, "services-bookings.css")

    def test_contact_intent_and_individual_keep_existing_semantics(self):
        payload = self.payload(
            booking_intent="book_later",
            preferred_date="",
            preferred_time="",
            staff_member="",
            client_type="INDIVIDUAL",
            company_name="Stale company",
        )
        self.assertEqual(self.client.post(self.url, payload).status_code, 302)
        self.assertFalse(Appointment.objects.exists())
        self.assertEqual(Lead.objects.get().company_name, "")

    def test_edit_and_terminal_status_do_not_add_notifications(self):
        self.login()
        item = self.appointment()
        before = len(mail.outbox)
        self.client.post(
            reverse("appointment_change_status", args=[item.pk]), {"status": "cancelled"}
        )
        item.refresh_from_db()
        self.assertEqual(item.status, "cancelled")
        self.assertEqual(len(mail.outbox), before)

    def test_contact_intent_with_supplied_invalid_slot_still_uses_server_validation(self):
        payload = self.payload(booking_intent="book_later", preferred_time="not-a-time")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("preferred_time", response.context["form"].errors)
        self.assertFalse(Appointment.objects.exists())
        self.assertFalse(Lead.objects.exists())
