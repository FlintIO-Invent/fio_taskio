import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.businesses.models import (
    Business,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    SubscriptionNotification,
)
from apps.businesses.subscription_notifications import deliver_subscription_notification
from apps.businesses.test_logistics_usage_limits import HARD_LIMITS, QuotaFixture

from .models import ParcelEvent
from .monitoring import observe_document, record_signal
from .parcel_services import change_parcel_status
from .public_tracking import lookup_public_tracking
from .subscription_usage import HARD_METRICS, logistics_subscription_usage
from .usage_warnings import WARNING_TYPE, enqueue_usage_warnings


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
)
class SubscriptionUsageTests(QuotaFixture, TestCase):
    def snapshot(self):
        return logistics_subscription_usage(business=self.business)

    def row(self, name, snapshot=None):
        usage = snapshot or self.snapshot()
        return next(row for row in usage["hard"] + usage["monitoring"] if row["name"] == name)

    def approaching(self):
        self.limit("clients", 5)
        for _ in range(3):
            self.create("clients")

    def test_dashboard_shows_all_metrics_annual_price_and_unknown_measurements(self):
        self.login()
        response = self.client.get(reverse("business_subscription"))
        self.assertEqual(response.status_code, 200)
        for _, label in HARD_METRICS:
            self.assertContains(response, label)
        self.assertContains(response, "1,700")
        self.assertContains(response, "/ year · EUR")
        self.assertContains(response, "Not measured")
        self.assertContains(response, "UTC")
        self.assertNotContains(response, "None")
        self.assertNotContains(response, "14-day trial")
        self.assertNotContains(response, "No active Motionmate plans")
        self.assertNotContains(response, "Appointments this month")
        self.assertEqual(self.row("users")["used"], 1)
        self.assertEqual(self.row("clients")["percent"], Decimal("0.4"))

    def test_admin_read_only_usage_service_and_staff_permissions_unchanged(self):
        self.membership.role = "admin"
        self.membership.save(update_fields=["role"])
        self.login()
        response = self.client.get(reverse("business_subscription"))
        self.assertContains(response, "Logistics usage")
        self.assertNotContains(response, "Manage billing")
        self.assertEqual(
            self.client.post(reverse("business_subscription"), {"plan": self.plan.pk}).status_code,
            403,
        )
        for role in ("staff", "accountant"):
            self.membership.role = role
            self.membership.save(update_fields=["role"])
            self.assertEqual(self.client.get(reverse("business_subscription")).status_code, 403)
        self.membership.role = "admin"
        self.membership.save(update_fields=["role"])
        self.business.vertical = "SERVICE"
        self.business.save(update_fields=["vertical"])
        self.assertEqual(self.client.get(reverse("business_subscription")).status_code, 403)

    def test_tenant_selection_cannot_expose_another_business(self):
        other = Business.objects.create(
            name="Private other tenant", slug="private-other", vertical="LOGISTICS"
        )
        self.login()
        session = self.client.session
        session["current_business_id"] = other.pk
        session.save()
        response = self.client.get(reverse("business_subscription"))
        self.assertNotContains(response, "Private other tenant")
        self.assertContains(response, self.business.name)

    def test_legacy_unlimited_is_distinct_from_unavailable_subscription(self):
        legacy = ClarivoPlan.objects.get(slug="logistics")
        legacy.is_active = True
        legacy.save(update_fields=["is_active"])
        self.subscription.plan = legacy
        self.subscription.save(update_fields=["plan"])
        self.login()
        response = self.client.get(reverse("business_subscription"))
        for row in self.snapshot()["hard"]:
            self.assertTrue(row["unlimited"])
            self.assertEqual(row["allowance_display"], "Unlimited")
            self.assertIsNone(row["percent"])
        self.assertContains(response, "Unlimited")
        self.assertEqual(enqueue_usage_warnings(business=self.business)["created"], 0)
        self.subscription.delete()
        response = self.client.get(reverse("business_subscription"))
        self.assertContains(response, "Unavailable")
        self.assertEqual(self.row("clients")["state"], "unavailable")
        self.assertFalse(self.row("clients")["unlimited"])

    def test_all_seven_hard_metrics_warn_at_exact_eighty_and_one_hundred(self):
        for metric in HARD_LIMITS:
            with self.subTest(metric=metric):
                self.limit(metric, 5)
                while self.row(metric)["used"] < 3:
                    self.create(metric)
                self.assertEqual(self.row(metric)["state"], "within")
                self.create(metric)
                self.assertEqual(self.row(metric)["state"], "approaching")
                self.assertEqual(self.row(metric)["percent"], 80)
                self.create(metric)
                self.assertEqual(self.row(metric)["state"], "full")
                self.assertEqual(self.row(metric)["percent"], 100)

    def test_unavailable_configuration_and_zero_allowance_render_safely(self):
        self.limit("locations", 0)
        row = self.row("locations")
        self.assertEqual(row["state"], "full")
        self.assertEqual(row["percent_display"], "No capacity")
        self.limit("clients", None)
        self.assertEqual(self.row("clients")["state"], "unavailable")
        self.assertEqual(self.row("clients")["used"], 1)

    def test_monthly_counters_and_reset_are_utc_and_survive_deleted_invoices(self):
        before = datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
        after = datetime(2027, 1, 1, tzinfo=UTC)
        with (
            patch("django.utils.timezone.now", return_value=before),
            patch.object(ParcelEvent._meta.get_field("timestamp"), "_get_default", lambda: before),
        ):
            invoice = self.create("invoices_per_month")
            invoice.delete()
            self.create("parcels_per_month")
            self.create("shipments_per_month")
            usage = self.snapshot()
            self.assertEqual(usage["period"], "2026-12")
            self.assertEqual(usage["reset_at"], after)
            for name in (
                "invoices_per_month",
                "parcels_per_month",
                "shipments_per_month",
                "parcel_events_per_month",
            ):
                self.assertEqual(self.row(name, usage)["used"], 1, name)
        with patch("django.utils.timezone.now", return_value=after):
            usage = self.snapshot()
            for name in (
                "invoices_per_month",
                "parcels_per_month",
                "shipments_per_month",
                "parcel_events_per_month",
            ):
                self.assertEqual(self.row(name, usage)["used"], 0)

    def test_warnings_deduplicate_thresholds_recipients_and_month_and_get_never_enqueues(self):
        admin = self.new_user()
        BusinessUser.objects.create(business=self.business, user=admin, role="admin")
        BusinessUser.objects.create(business=self.business, user=self.new_user(), role="staff")
        self.approaching()
        self.assertEqual(enqueue_usage_warnings(business=self.business)["created"], 2)
        self.assertEqual(enqueue_usage_warnings(business=self.business)["duplicates"], 2)
        self.create("clients")
        self.assertEqual(enqueue_usage_warnings(business=self.business)["created"], 2)
        self.login()
        self.client.get(reverse("business_subscription"))
        self.assertEqual(
            SubscriptionNotification.objects.filter(notification_type=WARNING_TYPE).count(), 4
        )
        self.assertEqual(
            set(SubscriptionNotification.objects.values_list("recipient_user_id", flat=True)),
            {self.user.pk, admin.pk},
        )
        with patch("django.utils.timezone.now", return_value=datetime(2027, 1, 1, tzinfo=UTC)):
            self.assertEqual(enqueue_usage_warnings(business=self.business)["created"], 2)

    def test_email_backend_acceptance_subset_excludes_queue_and_retries(self):
        self.approaching()
        enqueue_usage_warnings(business=self.business)
        notification = SubscriptionNotification.objects.get(notification_type=WARNING_TYPE)
        self.assertEqual(self.snapshot()["accepted_subscription_emails"], 0)
        with patch(
            "apps.businesses.subscription_notifications.send_templated_email",
            side_effect=[RuntimeError("transport failed"), True],
        ) as sender:
            self.assertEqual(deliver_subscription_notification(notification).status, "failed")
            self.assertEqual(self.snapshot()["accepted_subscription_emails"], 0)
            self.assertEqual(deliver_subscription_notification(notification).status, "sent")
            self.assertEqual(deliver_subscription_notification(notification).status, "skipped")
            self.assertEqual(sender.call_count, 2)
        usage = self.snapshot()
        self.assertEqual(usage["accepted_subscription_emails"], 1)
        email = self.row("transactional_emails_per_month", usage)
        self.assertIsNone(email["used"])
        self.assertEqual(email["state"], "not_measured")
        self.assertIsNone(email["percent"])

    def test_stale_warning_is_cancelled_after_capacity_drops(self):
        self.approaching()
        enqueue_usage_warnings(business=self.business)
        note = SubscriptionNotification.objects.get(notification_type=WARNING_TYPE)
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        with patch("apps.businesses.subscription_notifications.send_templated_email") as sender:
            self.assertEqual(deliver_subscription_notification(note).status, "cancelled")
            sender.assert_not_called()

    def test_warning_verification_failure_does_not_abort_notification_dispatch(self):
        self.approaching()
        enqueue_usage_warnings(business=self.business)
        note = SubscriptionNotification.objects.get(notification_type=WARNING_TYPE)
        with (
            patch(
                "apps.logistics.usage_warnings.obsolete_usage_warning",
                side_effect=ValueError("malformed snapshot"),
            ),
            patch("apps.businesses.subscription_notifications.send_templated_email") as sender,
        ):
            self.assertEqual(deliver_subscription_notification(note).status, "failed")
            sender.assert_not_called()

    def test_warning_does_not_send_to_former_admin_or_after_period_reset(self):
        self.approaching()
        enqueue_usage_warnings(business=self.business)
        note = SubscriptionNotification.objects.get(notification_type=WARNING_TYPE)
        self.membership.role = "staff"
        self.membership.save(update_fields=["role"])
        with patch("apps.businesses.subscription_notifications.send_templated_email") as sender:
            self.assertEqual(deliver_subscription_notification(note).status, "cancelled")
            sender.assert_not_called()
        self.membership.role = "owner"
        self.membership.save(update_fields=["role"])
        SubscriptionNotification.objects.filter(pk=note.pk).update(status="pending")
        with patch("django.utils.timezone.now", return_value=datetime(2027, 1, 1, tzinfo=UTC)):
            self.assertEqual(deliver_subscription_notification(note).status, "cancelled")

    def test_event_over_budget_and_same_key_retry_do_not_block_or_double_count(self):
        self.limit("parcel_events_per_month", 1)
        parcel = self.create("parcels_per_month")
        key = uuid4()
        for _ in range(2):
            change_parcel_status(
                business=self.business,
                actor=self.user,
                parcel=parcel,
                status="RECEIVED",
                idempotency_key=key,
            )
        self.assertEqual(self.row("parcel_events_per_month")["used"], 2)
        self.assertEqual(self.row("parcel_events_per_month")["percent"], 200)
        change_parcel_status(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            status="CANCELLED",
            idempotency_key=uuid4(),
        )
        self.assertEqual(self.row("parcel_events_per_month")["used"], 3)
        self.assertEqual(enqueue_usage_warnings(business=self.business)["created"], 0)

    def test_email_scope_and_storage_fallback_never_scan_storage(self):
        other = Business.objects.create(name="Other", slug="email-other", vertical="SERVICE")
        sub = BusinessSubscription.objects.create(
            business=other, plan=ClarivoPlan.objects.get(slug="starter")
        )
        SubscriptionNotification.objects.create(
            business=self.business,
            subscription=sub,
            notification_type="subscription_activated",
            status="sent",
            sent_at=timezone.now(),
            deduplication_key="cross-tenant-invalid",
        )
        with patch(
            "django.core.files.storage.default_storage.listdir",
            side_effect=AssertionError("Storage scan forbidden"),
        ):
            usage = self.snapshot()
        self.assertEqual(usage["accepted_subscription_emails"], 0)
        storage = self.row("storage_gb", usage)
        self.assertEqual(storage["allowance"], 1)
        self.assertIsNone(storage["used"])
        self.assertEqual(storage["state"], "not_measured")

    def test_collector_has_bounded_queries_and_reuses_c_counters(self):
        for metric in ("invoices_per_month", "parcels_per_month", "shipments_per_month"):
            self.create(metric)
        with CaptureQueriesContext(connection) as queries:
            self.snapshot()
        self.assertLessEqual(len(queries), 16)
        sql = [query["sql"].lower() for query in queries]
        self.assertFalse(
            any(
                "count(" in query
                and (
                    'from "logistics_parcel"' in query
                    or 'from "logistics_shipment"' in query
                    or 'from "billings_invoice"' in query
                )
                for query in sql
            )
        )

    def test_monitor_command_is_read_only_until_enqueue_and_never_sends(self):
        self.approaching()
        output = StringIO()
        call_command(
            "monitor_logistics_usage",
            business_id=self.business.pk,
            database_size=True,
            stdout=output,
        )
        self.assertFalse(SubscriptionNotification.objects.exists())
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(lines[0]["read_only"])
        if connection.vendor == "postgresql":
            self.assertGreater(lines[-1]["database_bytes"], 0)
        else:
            self.assertIsNone(lines[-1]["database_bytes"])
        with patch("apps.businesses.subscription_notifications.send_templated_email") as sender:
            call_command(
                "monitor_logistics_usage",
                business_id=self.business.pk,
                enqueue=True,
                stdout=StringIO(),
            )
            call_command(
                "monitor_logistics_usage",
                business_id=self.business.pk,
                enqueue=True,
                stdout=StringIO(),
            )
            sender.assert_not_called()
        self.assertEqual(SubscriptionNotification.objects.count(), 1)
        paged = StringIO()
        call_command("monitor_logistics_usage", after_business_id=self.business.pk, stdout=paged)
        self.assertEqual(paged.getvalue(), "")

    def test_usage_warnings_never_jump_ahead_of_billing_mail_in_dispatch(self):
        self.approaching()
        enqueue_usage_warnings(business=self.business)
        warning = SubscriptionNotification.objects.get(notification_type=WARNING_TYPE)
        essential = SubscriptionNotification.objects.create(
            business=self.business,
            subscription=self.subscription,
            notification_type="subscription_activated",
            recipient_email=self.user.email,
            recipient_user=self.user,
            deduplication_key="essential-after-warning",
        )
        with patch(
            "apps.businesses.subscription_notifications.send_templated_email", return_value=True
        ):
            call_command("send_subscription_notifications", limit=1, stdout=StringIO())
        essential.refresh_from_db()
        warning.refresh_from_db()
        self.assertEqual(essential.status, "sent")
        self.assertEqual(warning.status, "pending")

    def test_observability_is_private_nonblocking_and_not_a_cost_estimate(self):
        secret = "do-not-log-bearer-secret"
        with self.assertLogs("apps.logistics.monitoring", level="INFO") as logs:
            self.assertIsNone(lookup_public_tracking(secret))
        self.assertNotIn(secret, " ".join(logs.output))
        self.assertIn("tracking_lookup", " ".join(logs.output))
        with patch(
            "apps.logistics.monitoring.logger.info", side_effect=RuntimeError("logger unavailable")
        ):
            record_signal("test")
            wrapped = observe_document("test")(lambda **kwargs: "document")
            self.assertEqual(wrapped(business=self.business), "document")


@skipUnless(connection.vendor == "postgresql", "Outbox concurrency requires PostgreSQL")
@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
)
class UsageWarningConcurrencyTests(QuotaFixture, TransactionTestCase):
    def test_concurrent_discovery_and_delivery_use_existing_unique_outbox_claim(self):
        self.limit("clients", 1)
        barrier = Barrier(2)

        def discover():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return enqueue_usage_warnings(business=self.business)["created"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: discover(), range(2)))
        self.assertEqual(sum(results), 1)
        note = SubscriptionNotification.objects.get(notification_type=WARNING_TYPE)
        barrier = Barrier(2)

        def deliver():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return deliver_subscription_notification(note.pk).status
            finally:
                connections.close_all()

        with patch(
            "apps.businesses.subscription_notifications.send_templated_email", return_value=True
        ) as sender:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: deliver(), range(2)))
            self.assertCountEqual(results, ["sent", "skipped"])
            sender.assert_called_once()
