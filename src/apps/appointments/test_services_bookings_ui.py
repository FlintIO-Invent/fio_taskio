"""Presentation contracts; writes require the owned disposable test harness."""

from datetime import UTC, datetime
from types import SimpleNamespace

from django import forms
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.businesses.test_service_allowances import ServicesFixture
from apps.crm.models import Lead
from apps.crm.test_services_dashboard_ui import assert_disposable

from .templatetags.services_bookings import booking_time, booking_widget, business_zone


class FormattingTests(SimpleTestCase):
    def test_business_local_midnight_and_dst(self):
        business = SimpleNamespace(timezone="America/Lower_Princes")
        self.assertEqual(
            booking_time(datetime(2026, 11, 16, 2, tzinfo=UTC), business), "Nov 15, 2026 22:00"
        )
        business.timezone = "Europe/Amsterdam"
        for hour in (0, 1):
            self.assertEqual(
                booking_time(datetime(2026, 10, 25, hour, 30, tzinfo=UTC), business),
                "Oct 25, 2026 02:30",
            )
        business.timezone = "../invalid"
        self.assertEqual(str(business_zone(business)), "UTC")
        self.assertEqual(booking_time(None, business), "")

    def test_widget_retains_identity_and_associates_errors(self):
        class Form(forms.Form):
            title = forms.CharField(
                help_text="A short title", widget=forms.TextInput(attrs={"data-hook": "keep"})
            )

        form = Form({"title": ""})
        markup = booking_widget(form["title"])
        for value in (
            'name="title"',
            'id="id_title"',
            'data-hook="keep"',
            'aria-invalid="true"',
            "id_title_errors",
            "id_title_helptext",
        ):
            self.assertIn(value, markup)
        self.assertEqual(form.data["title"], "")


class BookingPresentationTests(ServicesFixture, TestCase):
    def setUp(self):
        assert_disposable()
        super().setUp()
        self.login()

    def test_get_keeps_rows_and_operation_fields(self):
        item = self.appointment()
        page = self.client.get(reverse("appointment_list"))
        self.assertContains(page, "services-bookings.css")
        self.assertContains(page, 'data-label="Classification"')
        self.assertContains(page, "Europe/Berlin")
        self.assertEqual(len(page.context["workspace_page"]), 1)
        for url in (reverse("appointment_create"), reverse("appointment_update", args=[item.pk])):
            page = self.client.get(url)
            for field in (
                "client",
                "service",
                "staff_member",
                "title",
                "start_time",
                "end_time",
                "location",
                "notes",
                "operation_key",
            ):
                self.assertContains(page, f'name="{field}"')
            self.assertContains(page, 'name="csrfmiddlewaretoken"')
        self.assertContains(self.client.get(reverse("appointment_create")), 'id="draftClientModal"')

    def test_terminal_edit_and_status_forms(self):
        item = self.appointment()
        page = self.client.get(reverse("appointment_detail", args=[item.pk]))
        self.assertContains(page, "bookingStatusConfirmation")
        self.assertContains(page, 'name="status" value="cancelled"')
        self.assertContains(page, "data-booking-status-form", count=3)
        item.status = "cancelled"
        item.save()
        page = self.client.get(reverse("appointment_update", args=[item.pk]))
        self.assertContains(page, "Editing does not reopen")
        self.assertNotContains(
            self.client.get(reverse("appointment_detail", args=[item.pk])),
            'id="bookingStatusConfirmation"',
        )

    def test_request_completion_and_interest_legacy(self):
        lead = Lead.objects.create(
            business=self.business,
            lead_type="REQUEST",
            first_name="Taylor",
            last_name="Customer",
            email="incomplete@example.test",
        )
        page = self.client.get(reverse("staff_lead_detail", args=[lead.pk]))
        self.assertContains(page, "services-bookings.css")
        page = self.client.get(reverse("staff_lead_convert_to_client", args=[lead.pk]))
        self.assertContains(page, "Saving opens Client Details")
        lead.lead_type = "INTEREST"
        lead.save()
        page = self.client.get(reverse("staff_lead_detail", args=[lead.pk]))
        self.assertNotContains(page, "services-bookings.css")
        self.assertContains(page, "Booking Details")
        page = self.client.post(
            reverse("staff_lead_update", args=[lead.pk]), {"lead_type": "INTEREST"}
        )
        self.assertNotContains(page, "services-bookings.css")
        self.assertEqual(page.context["form"]["lead_type"].value(), "INTEREST")

    def test_dashboard_and_other_pages_do_not_load_booking_assets(self):
        for name in ("agent_dashboard", "staff_client_list", "invoice_list"):
            self.assertNotContains(self.client.get(reverse(name)), "services-bookings.css")

    def test_split_parent_defaults_are_unchanged(self):
        parent = render_to_string("inheritance/split_forms_parent.html")
        self.assertIn("<body>", parent)
        self.assertNotIn("services-bookings", parent)

    def test_missing_request_type_keeps_validation_in_the_services_layout(self):
        response = self.client.post(reverse("staff_lead_create"), {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "services-bookings.css")
        self.assertContains(response, "data-booking-error-summary")
        self.assertIsNone(response.context["form"]["lead_type"].value())
        self.assertIn("lead_type", response.context["form"].errors)
        self.assertFalse(Lead.objects.exists())
