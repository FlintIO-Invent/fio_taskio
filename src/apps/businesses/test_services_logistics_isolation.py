"""Services appointment guards must preserve Logistics' previous SQL writers."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.db.models import F
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.crm.client_capacity import lock_client_capacity_scope
from apps.crm.models import Client, Lead
from apps.crm.services import sync_client_from_lead

from .models import Business, BusinessSubscription, ClarivoPlan
from .quota_middleware import QuotaErrorMiddleware
from .usage_limits import QuotaError


class LogisticsAppointmentWriterIsolationTests(TestCase):
    def setUp(self):
        plan = ClarivoPlan.objects.get(slug="logistics-core")
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        self.business = Business.objects.create(
            name="Historical Logistics appointments",
            slug="appointment-isolation",
            vertical="LOGISTICS",
        )
        BusinessSubscription.objects.create(
            business=self.business, plan=plan, status="active", billing_interval="yearly"
        )
        self.customer = Client.objects.create(
            business=self.business, first_name="Existing", last_name="Client"
        )

    def appointment(self, title="Existing appointment"):
        start = timezone.now() + timedelta(days=1)
        return Appointment(
            business=self.business,
            client=self.customer,
            title=title,
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

    def test_logistics_bulk_create_retains_conflict_handling_and_sql_path(self):
        row = self.appointment()
        Appointment.objects.bulk_create([row], ignore_conflicts=True)
        self.assertEqual(Appointment.objects.filter(business=self.business).count(), 1)

    def test_logistics_update_retains_sql_expressions_and_row_count(self):
        row = self.appointment()
        row.save()
        self.assertEqual(Appointment.objects.filter(pk=row.pk).update(status=F("status")), 1)
        self.assertEqual(
            Appointment.objects.filter(pk=row.pk).update(status=Appointment.Status.CANCELLED), 1
        )
        row.refresh_from_db()
        self.assertEqual(row.status, Appointment.Status.CANCELLED)

    def test_logistics_bulk_update_retains_sql_expressions(self):
        row = self.appointment()
        row.save()
        row.status = F("status")
        self.assertEqual(Appointment.objects.bulk_update([row], ["status"]), 1)
        row.refresh_from_db()
        self.assertEqual(row.status, Appointment.Status.SCHEDULED)


class LogisticsSharedBoundaryIsolationTests(TestCase):
    setUp = LogisticsAppointmentWriterIsolationTests.setUp

    def test_logistics_client_sync_does_not_acquire_the_services_matching_lock(self):
        lead = Lead.objects.create(
            business=self.business, first_name="Legacy", last_name="Lead", email="lead@example.test"
        )
        with patch(
            "apps.crm.client_capacity.lock_client_capacity_scope",
            wraps=lock_client_capacity_scope,
        ) as matching_lock:
            client, created = sync_client_from_lead(lead)
        self.assertTrue(created)
        self.assertEqual(client.business_id, self.business.pk)
        matching_lock.assert_not_called()

    def test_anonymous_logistics_quota_errors_keep_the_existing_template(self):
        request = RequestFactory().post("/logistics/enroll/")
        request.user = AnonymousUser()
        request.current_business = self.business
        request.resolver_match = SimpleNamespace(url_name="logistics_enroll")
        with patch("apps.businesses.quota_middleware.render") as render:
            QuotaErrorMiddleware(lambda request: None).process_exception(
                request, QuotaError("Existing Logistics quota error")
            )
        self.assertEqual(render.call_args.args[1], "businesses/quota_exceeded.html")
