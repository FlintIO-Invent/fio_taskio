import csv
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from importlib import import_module
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.apps import apps
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, connections, transaction
from django.test import Client as WebClient
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.forms import AppointmentForm
from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.billings.services import create_invoice_for_client
from apps.crm.importing.client_execution import execute_client_import
from apps.crm.importing.client_preview import persist_client_preview, project_client_capacity
from apps.crm.importing.clients import CLIENT_STANDARD_TEMPLATE_FIELDS, validate_client_import
from apps.crm.importing.jobs import create_import_job
from apps.crm.importing.types import ImportType
from apps.crm.models import BusinessService, Client, Lead
from apps.crm.services import sync_client_from_lead

from .models import (
    Business,
    BusinessBookingSettings,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    WeeklyAvailability,
)
from .service_limits import appointment_usage
from .usage_limits import QuotaError, utc_month_bounds
from .utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    accept_business_invitation_for_user,
    create_or_refresh_business_invitation,
    get_business_plan_usage_summary,
    get_business_usage_count,
)

ROLLOUT = import_module("apps.businesses.migrations.0035_services_allowances")


class ServicesFixture:
    def setUp(self):
        super().setUp()
        cache.clear()
        self.plan = ClarivoPlan.objects.create(
            name="Services quota test",
            slug="services-quota-test",
            max_users=10,
            max_clients=None,
            max_invoices_per_month=500,
            max_appointments_per_month=750,
            allow_invoicing=True,
            allow_appointments=True,
            allow_public_booking=True,
        )
        self.business = Business.objects.create(
            name="Services", slug="services-quota", timezone="Europe/Berlin"
        )
        self.subscription = BusinessSubscription.objects.create(
            business=self.business, plan=self.plan, status="active", payment_provider="local"
        )
        self.owner = self.user()
        self.member = BusinessUser.objects.create(
            business=self.business, user=self.owner, role="owner"
        )
        self.customer = self.new_client()
        self.service = BusinessService.objects.create(
            business=self.business,
            name="Consultation",
            unit_price=50,
            is_bookable_online=True,
            default_duration_minutes=60,
        )
        BusinessBookingSettings.objects.create(
            business=self.business,
            booking_enabled=True,
            minimum_notice_hours=0,
            maximum_days_ahead=365,
        )
        for day in range(7):
            WeeklyAvailability.objects.create(
                business=self.business,
                day_of_week=day,
                start_time=time(0),
                end_time=time(23, 59),
                is_active=True,
            )
        self.start = (
            (timezone.now() + timedelta(days=40))
            .astimezone(ZoneInfo(self.business.timezone))
            .replace(hour=10, minute=0, second=0, microsecond=0)
        )

    def user(self):
        return TaskIOUser.objects.create_user(
            email=f"service-{uuid.uuid4().hex}@example.test", password="test-only-password"
        )

    def new_client(self, **overrides):
        return Client.objects.create(
            **{
                "business": self.business,
                "first_name": "Test",
                "last_name": "Customer",
                "email": f"{uuid.uuid4().hex}@example.test",
                "phone": "+17215550100",
                "company_name": "Household",
                "street_address": "12 Example Street",
                **overrides,
            }
        )

    def limit(self, **values):
        ClarivoPlan.objects.filter(pk=self.plan.pk).update(**values)
        self.plan.refresh_from_db()
        self.business._state.fields_cache.pop("subscription", None)

    def appointment(self, start=None, **overrides):
        return Appointment.objects.create(
            **{
                "business": self.business,
                "client": self.customer,
                "title": "Visit",
                "start_time": start or self.start,
                "end_time": (start or self.start) + timedelta(hours=1),
                **overrides,
            }
        )

    def payload(self, **overrides):
        return {
            "operation_key": str(uuid.uuid4()),
            "booking_intent": "book_now",
            "service": self.service.pk,
            "staff_member": self.owner.pk,
            "preferred_date": self.start.date().isoformat(),
            "preferred_time": self.start.strftime("%H:%M"),
            "first_name": "Public",
            "last_name": "Customer",
            "company_name": "Household",
            "email": "public@example.test",
            "phone": "+17215550101",
            "street_address": "14 Example Street",
            "country": "Sint Maarten",
            "consent_to_contact": "on",
            **overrides,
        }

    def login(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()


class ServiceAllowanceTests(ServicesFixture, TestCase):
    def test_starter_description_migration_preserves_custom_and_protected_values(self):
        copy_rollout = import_module("apps.businesses.migrations.0036_services_starter_description")
        for description in (
            copy_rollout.BASELINE_DESCRIPTION,
            "A customized Starter description",
            copy_rollout.APPROVED_DESCRIPTION,
        ):
            with self.subTest(description=description):
                ClarivoPlan.objects.filter(slug="starter").update(description=description)
                expected = list(ClarivoPlan.objects.order_by("pk").values())
                if description == copy_rollout.BASELINE_DESCRIPTION:
                    for row in expected:
                        if row["slug"] == "starter":
                            row["description"] = copy_rollout.APPROVED_DESCRIPTION
                copy_rollout.update_starter_description(
                    apps, type("Editor", (), {"connection": connection})()
                )
                self.assertEqual(expected, list(ClarivoPlan.objects.order_by("pk").values()))

    def test_commercial_and_beta_catalog_and_prices(self):
        for slug, (_, expected) in ROLLOUT.CONFIGURATIONS.items():
            plan = ClarivoPlan.objects.get(slug=slug)
            self.assertEqual(tuple(getattr(plan, field) for field in ROLLOUT.FIELDS), expected)
            self.assertTrue(plan.allow_public_booking)
        business = ClarivoPlan.objects.get(slug="business")
        self.assertEqual((business.price_monthly, business.price_yearly), (159, 1590))
        self.assertEqual(
            (
                business.get_pricing_data(region="eur")["monthly"],
                business.get_pricing_data(region="eur")["yearly"],
            ),
            (149, 1490),
        )
        beta = ClarivoPlan.objects.get(slug="beta")
        self.assertEqual((beta.price_monthly, beta.price_yearly), (0, 0))

    def test_migration_repeatability_and_protected_values(self):
        before = list(ClarivoPlan.objects.order_by("pk").values())
        subscription = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        for slug, (old, _) in ROLLOUT.CONFIGURATIONS.items():
            ClarivoPlan.objects.filter(slug=slug).update(
                **dict(zip(ROLLOUT.FIELDS, old, strict=True))
            )
        ROLLOUT.update_allowances(apps, type("Editor", (), {"connection": connection})())
        ROLLOUT.update_allowances(apps, type("Editor", (), {"connection": connection})())
        self.assertEqual(before, list(ClarivoPlan.objects.order_by("pk").values()))
        self.assertEqual(
            subscription, BusinessSubscription.objects.values().get(pk=self.subscription.pk)
        )

    def test_migration_customization_is_reported_without_partial_updates(self):
        for slug in ("starter", "beta"):
            with self.subTest(slug=slug), transaction.atomic():
                ClarivoPlan.objects.filter(slug="pro").update(
                    **dict(zip(ROLLOUT.FIELDS, ROLLOUT.CONFIGURATIONS["pro"][0], strict=True))
                )
                ClarivoPlan.objects.filter(slug=slug).update(max_users=83)
                before = list(ClarivoPlan.objects.order_by("pk").values())
                with self.assertRaisesRegex(RuntimeError, "NOT completed"):
                    ROLLOUT.update_allowances(
                        apps, type("Editor", (), {"connection": connection})()
                    )
                self.assertEqual(before, list(ClarivoPlan.objects.order_by("pk").values()))
                transaction.set_rollback(True)

    def test_unlimited_zero_and_unavailable_clients(self):
        self.assertTrue(
            project_client_capacity(business=self.business, new_importable_clients=500).allowed
        )
        self.new_client()
        self.limit(max_clients=0)
        with self.assertRaises(QuotaError):
            self.new_client()
        BusinessSubscription.objects.filter(pk=self.subscription.pk).update(status="expired")
        self.business._state.fields_cache.pop("subscription", None)
        self.assertFalse(
            project_client_capacity(business=self.business, new_importable_clients=1).available
        )
        with self.assertRaises(QuotaError):
            self.new_client()

    def test_unlimited_import_preview_and_execution(self):
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=CLIENT_STANDARD_TEMPLATE_FIELDS)
        writer.writeheader()
        writer.writerow(
            {
                "first_name": "Imported",
                "last_name": "Customer",
                "email": "imported@example.test",
                "phone": "+17215550102",
                "company_name": "Imported",
                "street_address": "16 Example Street",
            }
        )
        validation = validate_client_import(
            SimpleUploadedFile("clients.csv", stream.getvalue().encode()), business=self.business
        )
        job = create_import_job(
            business=self.business,
            actor=self.owner,
            import_type=ImportType.CLIENTS,
            schema_version="1",
            parsed_file=validation.parsed_file,
        )
        persist_client_preview(validation, job=job, business=self.business, actor=self.owner)
        self.assertTrue(
            execute_client_import(job_id=job.pk, business=self.business, actor=self.owner).completed
        )
        self.assertEqual(
            Client.objects.filter(business=self.business, email="imported@example.test").count(), 1
        )

    def test_conversion_and_quick_client_paths(self):
        lead = Lead.objects.create(
            business=self.business,
            lead_type="REQUEST",
            first_name="Convert",
            last_name="Me",
            email="convert@example.test",
            phone="+17215550103",
            company_name="Convert",
            street_address="18 Example Street",
        )
        _, created = sync_client_from_lead(lead)
        self.assertTrue(created)
        self.assertFalse(sync_client_from_lead(lead)[1])
        self.login()
        response = self.client.post(
            reverse("invoice_quick_create_client"),
            {
                "first_name": "Quick",
                "last_name": "Client",
                "email": "quick@example.test",
                "phone": "+17215550104",
                "company_name": "Quick",
                "street_address": "20 Example Street",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.limit(max_clients=0)
        with patch("apps.billings.views.business_limit_reached", return_value=False):
            denied = self.client.post(
                reverse("invoice_quick_create_client"),
                {
                    "first_name": "Race",
                    "last_name": "Denied",
                    "email": "race-denied@example.test",
                    "phone": "+17215550105",
                    "company_name": "Race",
                    "street_address": "22 Example Street",
                },
            )
        self.assertEqual(denied.status_code, 409)
        self.assertIn("errors", denied.json())
        self.assertFalse(Client.objects.filter(email="race-denied@example.test").exists())

    def test_destination_month_rescheduling_and_deletion(self):
        self.limit(max_appointments_per_month=1)
        first = self.appointment()
        next_month = utc_month_bounds(self.start)[1] + timedelta(days=1)
        second = self.appointment(next_month)
        second.start_time, second.end_time = self.start, self.start + timedelta(hours=1)
        with self.assertRaises(QuotaError):
            second.save()
        first.title = "Same month edit"
        first.save()
        first.status = "cancelled"
        first.save()
        with self.assertRaises(QuotaError):
            self.appointment()
        first.delete()
        second.save()
        self.assertEqual(appointment_usage(self.business, self.start), 1)

    def test_bulk_rescheduling_cannot_bypass_allowance(self):
        first = self.appointment()
        second = self.appointment(utc_month_bounds(self.start)[1] + timedelta(days=1))
        self.limit(max_appointments_per_month=1)
        with self.assertRaises(QuotaError):
            Appointment.objects.filter(pk=second.pk).update(
                start_time=first.start_time, end_time=first.end_time
            )

    def test_shared_public_internal_usage_and_retry(self):
        self.limit(max_appointments_per_month=2, max_public_bookings_per_month=0)
        self.appointment(self.start + timedelta(hours=2))
        payload = self.payload()
        url = reverse("public_booking", args=[self.business.slug])
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(url, payload).status_code, 302)
        sent = len(mail.outbox)
        self.assertGreater(sent, 0)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(len(mail.outbox), sent)
        self.assertEqual(appointment_usage(self.business, self.start), 2)
        self.assertEqual(Lead.objects.filter(business=self.business).count(), 1)
        payload["message"] = "different details"
        self.assertEqual(self.client.post(url, payload).status_code, 409)
        payload = self.payload(preferred_time="15:00")
        self.assertEqual(self.client.post(url, payload).status_code, 409)
        self.assertEqual(Lead.objects.filter(business=self.business).count(), 1)

    def test_contact_first_consumes_only_when_scheduled(self):
        self.limit(max_appointments_per_month=0, max_public_bookings_per_month=0)
        url = reverse("public_booking", args=[self.business.slug])
        payload = self.payload(
            booking_intent="book_later", preferred_date="", preferred_time="", staff_member=""
        )
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(appointment_usage(self.business, self.start), 0)
        lead = Lead.objects.get(business=self.business)
        self.limit(max_appointments_per_month=2)
        self.appointment(source_lead=lead)
        self.appointment(source_lead=lead)
        self.assertEqual(appointment_usage(self.business, self.start), 2)

    def test_internal_form_retry_and_multiple_deliberate_requests(self):
        self.login()
        self.limit(max_appointments_per_month=1)
        payload = {
            "client": self.customer.pk,
            "title": "Visit",
            "start_time": self.start.strftime("%Y-%m-%dT%H:%M"),
            "end_time": (self.start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "operation_key": str(uuid.uuid4()),
        }
        url = reverse("appointment_create")
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        payload["operation_key"] = str(uuid.uuid4())
        self.assertEqual(self.client.post(url, payload).status_code, 409)

    def test_timezone_dst_and_utc_boundaries(self):
        form = AppointmentForm(current_business=self.business)
        field = form.fields["start_time"]
        self.assertEqual(
            field.clean("2026-07-01T00:30").astimezone(UTC),
            datetime(2026, 6, 30, 22, 30, tzinfo=UTC),
        )
        from django.core.exceptions import ValidationError

        for value in ("2026-03-29T02:30", "2026-10-25T02:30"):
            with self.assertRaises(ValidationError):
                field.clean(value)
        self.appointment(datetime(2027, 1, 1, tzinfo=UTC))
        self.assertEqual(
            appointment_usage(self.business, datetime(2026, 12, 31, 23, 59, tzinfo=UTC)), 0
        )
        self.assertEqual(appointment_usage(self.business, datetime(2027, 1, 1, tzinfo=UTC)), 1)

    def test_request_conversion_retries_and_deliberate_multiple_appointments(self):
        self.login()
        self.limit(max_appointments_per_month=2)
        lead = Lead.objects.create(
            business=self.business, lead_type="REQUEST", email=self.customer.email
        )
        payload = {
            "client": self.customer.pk,
            "title": "From request",
            "start_time": self.start.strftime("%Y-%m-%dT%H:%M"),
            "end_time": (self.start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "operation_key": str(uuid.uuid4()),
        }
        url = reverse("appointment_create_from_request", args=[lead.pk])
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(Appointment.objects.filter(source_lead=lead).count(), 1)
        payload["operation_key"] = str(uuid.uuid4())
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(Appointment.objects.filter(source_lead=lead).count(), 2)

    def test_invoice_creation_only_and_existing_history_untouched(self):
        self.limit(max_invoices_per_month=1)
        invoice = create_invoice_for_client(actor=self.owner, client=self.customer)
        invoice.notes = "Updated"
        invoice.save()
        with self.assertRaises(QuotaError):
            create_invoice_for_client(actor=self.owner, client=self.customer)
        self.assertEqual((invoice.status, invoice.total), ("DRAFT", 0))
        self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 1)

    def test_seat_reservation_acceptance_and_reactivation(self):
        self.limit(max_users=2)
        user = self.user()
        invitation, _ = create_or_refresh_business_invitation(
            business=self.business, email=user.email, role="admin", invited_by=self.owner
        )
        self.assertEqual(
            get_business_usage_count(self.business, "users", include_pending_invitations=True), 2
        )
        member, _, _ = accept_business_invitation_for_user(invitation, user)
        self.assertEqual(
            get_business_usage_count(self.business, "users", include_pending_invitations=True), 2
        )
        member.is_active = False
        member.save()
        BusinessUser.objects.create(business=self.business, user=self.user(), role="accountant")
        member.is_active = True
        with self.assertRaises(QuotaError):
            member.save()
        with self.assertRaises(QuotaError):
            create_or_refresh_business_invitation(
                business=self.business,
                email=self.user().email,
                role="viewer",
                invited_by=self.owner,
            )

    def test_subscription_statuses_keep_linked_entitlements_and_billing(self):
        for status, source in (
            ("trialing", "standard"),
            ("active", "free_test"),
            ("active", "beta"),
        ):
            now = timezone.now()
            BusinessSubscription.objects.filter(pk=self.subscription.pk).update(
                status=status,
                provisioning_source=source,
                trial_start=now,
                trial_end=now + timedelta(days=14),
            )
            before = BusinessSubscription.objects.values().get(pk=self.subscription.pk)
            self.new_client()
            self.appointment()
            self.assertEqual(
                before, BusinessSubscription.objects.values().get(pk=self.subscription.pk)
            )

    def test_usage_display_has_no_separate_public_quota(self):
        names = {item["name"] for item in get_business_plan_usage_summary(self.business, self.plan)}
        self.assertNotIn("public_bookings_per_month", names)

    def test_invoice_email_resend_and_download_do_not_consume(self):
        self.limit(max_invoices_per_month=1)
        invoice = create_invoice_for_client(actor=self.owner, client=self.customer)
        self.login()
        with (
            patch("apps.billings.views.render_invoice_pdf", return_value=b"%PDF-test"),
            patch("apps.billings.views.send_invoice_email", return_value=True),
        ):
            for _ in range(2):
                self.assertEqual(
                    self.client.post(reverse("invoice_email_send", args=[invoice.pk])).status_code,
                    302,
                )
            self.assertEqual(
                self.client.get(reverse("invoice_pdf_download", args=[invoice.pk])).status_code, 200
            )
        invoice.refresh_from_db()
        self.assertEqual((invoice.email_send_count, invoice.status), (2, "DRAFT"))
        self.assertEqual(Invoice.objects.filter(business=self.business).count(), 1)

    def test_missing_subscription_is_not_unlimited_and_initial_owner_bootstrap(self):
        business = Business.objects.create(name="Unprovisioned", slug="unprovisioned")
        BusinessUser.objects.create(business=business, user=self.user(), role="owner")
        with self.assertRaises(QuotaError):
            Client.objects.create(business=business, first_name="Denied", last_name="Client")
        with self.assertRaises(QuotaError):
            BusinessUser.objects.create(business=business, user=self.user(), role="admin")

    def test_owner_and_elevated_roles_are_seats_even_when_user_disabled(self):
        self.limit(max_users=2)
        user = self.user()
        user.is_active = False
        user.save()
        BusinessUser.objects.create(business=self.business, user=user, role="viewer")
        self.assertEqual(get_business_usage_count(self.business, "users"), 2)
        with self.assertRaises(QuotaError):
            BusinessUser.objects.create(business=self.business, user=self.user(), role="admin")

    def test_migration_wrong_family_or_missing_plan_does_not_complete(self):
        for missing in (False, True):
            with self.subTest(missing=missing), transaction.atomic():
                if missing:
                    ClarivoPlan.objects.filter(slug="starter").delete()
                else:
                    ClarivoPlan.objects.filter(slug="starter").update(family="LOGISTICS")
                with self.assertRaisesRegex(RuntimeError, "NOT completed"):
                    ROLLOUT.update_allowances(
                        apps, type("Editor", (), {"connection": connection})()
                    )
                transaction.set_rollback(True)

    def test_public_throttle_is_independent_and_csrf_remains(self):
        from django.test import RequestFactory

        from apps.crm.booking_protection import allow_booking_submission

        request = RequestFactory().post("/", REMOTE_ADDR="127.0.0.1")
        self.assertTrue(all(allow_booking_submission(request, self.business.pk) for _ in range(30)))
        self.assertFalse(allow_booking_submission(request, self.business.pk))
        self.assertTrue(allow_booking_submission(request, self.business.pk + 1))
        with patch("apps.crm.booking_protection.caches", new={}):
            self.assertFalse(allow_booking_submission(request, self.business.pk))
        response = WebClient(enforce_csrf_checks=True).post(
            reverse("public_booking", args=[self.business.slug]), self.payload()
        )
        self.assertEqual(response.status_code, 403)
        logistics = Business.objects.create(
            name="Logistics", slug="logistics-no-service-booking", vertical="LOGISTICS"
        )
        with patch("apps.crm.views.allow_booking_submission") as throttle:
            self.assertEqual(
                self.client.post(
                    reverse("public_booking", args=[logistics.slug]), self.payload()
                ).status_code,
                403,
            )
        throttle.assert_not_called()


@skipUnless(connection.vendor == "postgresql", "Real PostgreSQL row locks required")
class ServiceConcurrencyTests(ServicesFixture, TransactionTestCase):
    def race(self, actions):
        barrier = Barrier(len(actions))

        def worker(action):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                barrier.wait(timeout=10)
                try:
                    action()
                    return "ok"
                except QuotaError:
                    return "quota"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            futures = [pool.submit(worker, action) for action in actions]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_appointments(self):
        self.limit(max_appointments_per_month=1)
        self.assertCountEqual(self.race([self.appointment, self.appointment]), ["ok", "quota"])
        self.assertEqual(appointment_usage(self.business, self.start), 1)

    def test_concurrent_invoices(self):
        self.limit(max_invoices_per_month=1)

        def action():
            return create_invoice_for_client(actor=self.owner, client=self.customer)

        self.assertCountEqual(self.race([action, action]), ["ok", "quota"])
        self.assertEqual(Invoice.objects.filter(business=self.business).count(), 1)

    def test_concurrent_cross_month_move_and_creation(self):
        self.limit(max_appointments_per_month=1)
        moved = self.appointment(utc_month_bounds(self.start)[1] + timedelta(days=1))

        def reschedule():
            moved.start_time, moved.end_time = self.start, self.start + timedelta(hours=1)
            moved.save()

        self.assertCountEqual(self.race([reschedule, self.appointment]), ["ok", "quota"])
        self.assertEqual(appointment_usage(self.business, self.start), 1)

    def test_concurrent_invitations(self):
        self.limit(max_users=2)
        users = [self.user(), self.user()]
        actions = [
            lambda user=user: create_or_refresh_business_invitation(
                business=self.business, email=user.email, role="staff", invited_by=self.owner
            )
            for user in users
        ]
        self.assertCountEqual(self.race(actions), ["ok", "quota"])
        self.assertEqual(
            get_business_usage_count(self.business, "users", include_pending_invitations=True), 2
        )

    def test_concurrent_membership_reactivation(self):
        self.limit(max_users=2)
        members = [
            BusinessUser.objects.create(business=self.business, user=self.user(), is_active=False)
            for _ in range(2)
        ]

        def activate(member):
            member.is_active = True
            member.save()

        self.assertCountEqual(
            self.race([lambda m=m: activate(m) for m in members]), ["ok", "quota"]
        )

    def test_concurrent_reserved_acceptances(self):
        self.limit(max_users=3)
        users = [self.user(), self.user()]
        invitations = [
            create_or_refresh_business_invitation(
                business=self.business, email=user.email, role="staff", invited_by=self.owner
            )[0]
            for user in users
        ]
        self.assertEqual(
            self.race(
                [
                    lambda i=i, u=u: accept_business_invitation_for_user(i, u)
                    for i, u in zip(invitations, users, strict=True)
                ]
            ),
            ["ok", "ok"],
        )
        self.assertEqual(
            get_business_usage_count(self.business, "users", include_pending_invitations=True), 3
        )

    def test_concurrent_public_slot_booking(self):
        statuses = []

        def submit():
            response = WebClient().post(
                reverse("public_booking", args=[self.business.slug]), self.payload()
            )
            statuses.append(response.status_code)

        self.assertEqual(self.race([submit, submit]), ["ok", "ok"])
        self.assertCountEqual(statuses, [302, 200])
        self.assertEqual(Appointment.objects.filter(business=self.business).count(), 1)

    def test_concurrent_public_submission_retry(self):
        payload = self.payload()
        statuses = []

        def submit():
            statuses.append(
                WebClient()
                .post(reverse("public_booking", args=[self.business.slug]), payload)
                .status_code
            )

        self.assertEqual(self.race([submit, submit]), ["ok", "ok"])
        self.assertEqual(statuses, [302, 302])
        self.assertEqual(Lead.objects.filter(business=self.business).count(), 1)
        self.assertEqual(Appointment.objects.filter(business=self.business).count(), 1)
