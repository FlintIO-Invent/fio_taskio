"""Logistics CSV entitlements use the same persisted limits as manual creation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.businesses.models import Business, BusinessSubscription, ClarivoPlan
from apps.businesses.utils import (
    business_limit_reached,
    get_business_plan_limit,
    resolve_business_plan_limit,
)

from .importing.client_execution import ClientImportExecutionCode
from .importing.client_preview import project_client_capacity
from .models import Client
from .test_client_execution import ClientExecutionTestMixin


class LogisticsClientCapacityMixin(ClientExecutionTestMixin):
    def setUp(self):
        super().setUp()
        self.business.vertical = Business.Vertical.LOGISTICS
        self.business.save(update_fields=["vertical"])
        self.plan, _ = ClarivoPlan.objects.update_or_create(
            slug="logistics",
            defaults={
                "name": "Legacy Logistics",
                "family": ClarivoPlan.Family.LOGISTICS,
                "is_active": True,
                "max_clients": None,
            },
        )
        self.subscription.plan = self.plan
        self.subscription.billing_interval = BusinessSubscription.BillingInterval.YEARLY
        self.subscription.payment_provider = BusinessSubscription.PaymentProvider.STRIPE
        self.subscription.billing_currency = BusinessSubscription.BillingCurrency.EUR
        self.subscription.save(
            update_fields=["plan", "billing_interval", "payment_provider", "billing_currency"]
        )
        self.business.refresh_from_db()

    def capacity(self, requested=1):
        self.business.refresh_from_db()
        return project_client_capacity(business=self.business, new_importable_clients=requested)

    def manual_client_data(self):
        return {
            **self.valid_row,
            "email": "manual@example.com",
            "phone": "+1 721 555 0900",
            "client_type": Client.ClientType.BUSINESS,
            "client_status": Client.ClientStatus.LEAD,
            "priority": Client.Priority.MEDIUM,
            "preferred_contact_method": Client.PreferredContactMethod.EMAIL,
            "country": "Sint Maarten",
        }


@override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False)
class LogisticsClientCapacityTests(LogisticsClientCapacityMixin, TestCase):
    def test_manual_create_and_csv_both_accept_legacy_unlimited_entitlement(self):
        self.login()
        response = self.client.post(reverse("staff_client_create"), self.manual_client_data())
        self.assertRedirects(response, reverse("staff_client_list"))
        self.assertTrue(
            Client.objects.filter(business=self.business, email="manual@example.com").exists()
        )
        job = self.ready_job([self.valid_row])
        self.assertTrue(self.execute(job).completed)
        self.assertEqual(self.capacity().current_active_clients, 2)

    def test_legacy_unlimited_is_available_for_preview_execution_and_retry(self):
        self.existing_client()
        capacity = self.capacity(requested=20)
        self.assertTrue(capacity.available)
        self.assertTrue(capacity.allowed)
        self.assertEqual(capacity.current_active_clients, 1)
        self.assertIsNone(capacity.plan_limit)
        self.assertIsNone(capacity.remaining_capacity)
        self.assertFalse(business_limit_reached(self.business, "clients"))
        job = self.ready_job([self.valid_row])
        self.assertEqual(self.execute(job).code, ClientImportExecutionCode.COMPLETED)
        self.assertEqual(self.execute(job).code, ClientImportExecutionCode.ALREADY_COMPLETED)
        self.assertEqual(Client.objects.filter(business=self.business).count(), 2)

    def test_unlimited_preview_renders_label_and_confirmation(self):
        job = self.ready_job([self.valid_row])
        self.login()
        response = self.client.get(reverse("client_import_preview", args=[job.pk]))
        self.assertContains(response, "Unlimited", count=2)
        self.assertContains(response, "Confirm Client Import")
        self.assertNotContains(response, "Client plan capacity could not be verified")

    def test_numeric_limit_and_active_usage_match_manual_creation(self):
        self.plan.max_clients = 2
        self.plan.save(update_fields=["max_clients"])
        self.existing_client()
        self.existing_client(client_status=Client.ClientStatus.INACTIVE)
        self.existing_client(client_status=Client.ClientStatus.ARCHIVED)
        self.existing_client(is_active=False)
        capacity = self.capacity()
        self.assertEqual(capacity.current_active_clients, 1)
        self.assertEqual(capacity.plan_limit, 2)
        self.assertEqual(capacity.remaining_capacity, 1)
        self.assertTrue(capacity.allowed)
        self.assertEqual(get_business_plan_limit(self.business, "clients"), 2)
        self.assertFalse(business_limit_reached(self.business, "clients"))
        job = self.ready_job([self.valid_row])
        self.assertTrue(self.execute(job).completed)
        self.assertTrue(business_limit_reached(self.business, "clients"))
        capacity = self.capacity()
        self.assertTrue(capacity.available)
        self.assertFalse(capacity.allowed)
        self.assertEqual(capacity.code, "client_capacity_exceeded")
        self.assertEqual(capacity.remaining_capacity, 0)
        self.login()
        self.assertRedirects(
            self.client.get(reverse("staff_client_create")), reverse("staff_client_list")
        )

    def test_numeric_preview_displays_usage_allowance_and_remaining(self):
        self.plan.max_clients = 250
        self.plan.save(update_fields=["max_clients"])
        self.existing_client()
        job = self.ready_job([self.valid_row])
        self.login()
        response = self.client.get(reverse("client_import_preview", args=[job.pk]))
        capacity = response.context["capacity"]
        self.assertEqual(
            (
                capacity["current_active_clients"],
                capacity["plan_limit"],
                capacity["remaining_capacity"],
            ),
            (1, 250, 249),
        )
        self.assertContains(response, "250")
        self.assertContains(response, "249")

    def test_zero_limit_is_exceeded_rather_than_unavailable(self):
        self.plan.max_clients = 0
        self.plan.save(update_fields=["max_clients"])
        capacity = self.capacity()
        self.assertTrue(capacity.available)
        self.assertFalse(capacity.allowed)
        self.assertEqual(capacity.code, "client_capacity_exceeded")

    def test_missing_subscription_is_unavailable(self):
        self.subscription.delete()
        capacity = self.capacity()
        self.assertFalse(capacity.available)
        self.assertFalse(capacity.allowed)
        self.assertEqual(capacity.code, "client_capacity_unavailable")

    def test_inaccessible_subscription_states_do_not_grant_unlimited_capacity(self):
        for status in (
            BusinessSubscription.Status.EXPIRED,
            BusinessSubscription.Status.CANCELLED,
            BusinessSubscription.Status.SUSPENDED,
            BusinessSubscription.Status.PENDING_CHECKOUT,
            BusinessSubscription.Status.PAST_DUE,
        ):
            with self.subTest(status=status):
                self.subscription.status = status
                self.subscription.save(update_fields=["status"])
                self.assertFalse(self.capacity().available)

    def test_expired_active_period_is_unavailable(self):
        self.subscription.current_period_end = timezone.now() - timedelta(seconds=1)
        self.subscription.save(update_fields=["current_period_end"])
        self.assertFalse(self.capacity().available)

    def test_inactive_plan_and_business_are_unavailable(self):
        self.plan.is_active = False
        self.plan.save(update_fields=["is_active"])
        self.assertFalse(self.capacity().available)
        self.plan.is_active = True
        self.plan.save(update_fields=["is_active"])
        self.business.is_active = False
        self.business.save(update_fields=["is_active"])
        self.assertFalse(self.capacity().available)

    def test_family_mismatch_and_monthly_logistics_are_unavailable(self):
        self.plan.family = ClarivoPlan.Family.SERVICE
        self.plan.save(update_fields=["family"])
        self.assertFalse(self.capacity().available)
        self.plan.family = ClarivoPlan.Family.LOGISTICS
        self.plan.save(update_fields=["family"])
        # Simulate incompatible historical data without bypassing model save validation in production.
        BusinessSubscription.objects.filter(pk=self.subscription.pk).update(
            billing_interval=BusinessSubscription.BillingInterval.MONTHLY
        )
        self.assertFalse(self.capacity().available)

    def test_unknown_limit_is_unavailable_and_legacy_scalar_api_is_preserved(self):
        self.assertFalse(resolve_business_plan_limit(self.business, "unknown").available)
        self.assertFalse(resolve_business_plan_limit(None, "clients").available)
        self.assertIsNone(get_business_plan_limit(self.business, "unknown"))
        entitlement = resolve_business_plan_limit(self.business, "clients")
        self.assertTrue(entitlement.available)
        self.assertIsNone(entitlement.limit)

    def test_limit_reduction_after_preview_rejects_entire_import(self):
        job = self.ready_job(
            [
                self.valid_row,
                {**self.valid_row, "email": "second@example.com", "phone": "+1 721 555 0200"},
            ]
        )
        self.plan.max_clients = 1
        self.plan.save(update_fields=["max_clients"])
        self.assertEqual(self.execute(job).code, ClientImportExecutionCode.CAPACITY_CHANGED)
        self.assertFalse(Client.objects.filter(business=self.business).exists())

    def test_expiration_after_preview_rejects_entire_import(self):
        job = self.ready_job([self.valid_row])
        self.subscription.status = BusinessSubscription.Status.EXPIRED
        self.subscription.save(update_fields=["status"])
        self.assertEqual(self.execute(job).code, ClientImportExecutionCode.CAPACITY_CHANGED)
        self.assertFalse(Client.objects.filter(business=self.business).exists())

    @override_settings(
        DEBUG=True, MOTIONMATE_ENVIRONMENT="local", LOGISTICS_LOCAL_BILLING_BYPASS=True
    )
    def test_guarded_local_test_lab_entitlement_can_import_without_payment(self):
        self.plan.is_active = False
        self.plan.save(update_fields=["is_active"])
        self.subscription.status = BusinessSubscription.Status.PENDING_CHECKOUT
        self.subscription.payment_provider = BusinessSubscription.PaymentProvider.STRIPE
        self.subscription.billing_currency = BusinessSubscription.BillingCurrency.EUR
        self.subscription.save(update_fields=["status", "payment_provider", "billing_currency"])
        self.assertTrue(self.capacity().available)
        job = self.ready_job([self.valid_row])
        self.assertTrue(self.execute(job).completed)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, BusinessSubscription.Status.PENDING_CHECKOUT)
        for environment in ("development", "staging", "production"):
            with (
                self.subTest(environment=environment),
                override_settings(MOTIONMATE_ENVIRONMENT=environment),
            ):
                self.assertFalse(self.capacity().available)
        with override_settings(DEBUG=False):
            self.assertFalse(self.capacity().available)

    @override_settings(
        DEBUG=True, MOTIONMATE_ENVIRONMENT="local", LOGISTICS_LOCAL_BILLING_BYPASS=True
    )
    def test_local_bypass_preserves_numeric_capacity_and_approval_hold(self):
        self.plan.max_clients = 0
        self.plan.save(update_fields=["max_clients"])
        self.subscription.status = BusinessSubscription.Status.PENDING_CHECKOUT
        self.subscription.payment_provider = BusinessSubscription.PaymentProvider.STRIPE
        self.subscription.billing_currency = BusinessSubscription.BillingCurrency.EUR
        self.subscription.save(update_fields=["status", "payment_provider", "billing_currency"])
        self.assertEqual(self.capacity().code, "client_capacity_exceeded")
        self.subscription.logistics_approval_review_required = True
        self.subscription.save(update_fields=["logistics_approval_review_required"])
        self.assertFalse(self.capacity().available)

    def test_service_null_import_policy_is_unchanged(self):
        self.business.vertical = Business.Vertical.SERVICE
        self.business.save(update_fields=["vertical"])
        self.plan.family = ClarivoPlan.Family.SERVICE
        self.plan.save(update_fields=["family"])
        self.assertFalse(self.capacity().available)


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency requires PostgreSQL")
@override_settings(LOGISTICS_LOCAL_BILLING_BYPASS=False)
class LogisticsClientCapacityConcurrencyTests(LogisticsClientCapacityMixin, TransactionTestCase):
    def race(self, actions):
        barrier = Barrier(2)

        def worker(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return action()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, action) for action in actions]
            return [future.result(timeout=30) for future in futures]

    def test_two_imports_cannot_overfill_last_slot(self):
        self.plan.max_clients = 1
        self.plan.save(update_fields=["max_clients"])
        first = self.ready_job([self.valid_row])
        second = self.ready_job(
            [{**self.valid_row, "email": "other@example.com", "phone": "+1 721 555 0200"}]
        )
        self.assertCountEqual(
            self.race([lambda: self.execute(first).code, lambda: self.execute(second).code]),
            [ClientImportExecutionCode.COMPLETED, ClientImportExecutionCode.CAPACITY_CHANGED],
        )
        self.assertEqual(Client.objects.filter(business=self.business).count(), 1)

    def test_concurrent_unlimited_import_retry_creates_only_one_client(self):
        job = self.ready_job([self.valid_row])
        self.assertCountEqual(
            self.race([lambda: self.execute(job).code] * 2),
            [ClientImportExecutionCode.COMPLETED, ClientImportExecutionCode.ALREADY_COMPLETED],
        )
        self.assertEqual(Client.objects.filter(business=self.business).count(), 1)

    def test_manual_create_and_csv_cannot_overfill_last_slot(self):
        self.plan.max_clients = 1
        self.plan.save(update_fields=["max_clients"])
        job = self.ready_job([self.valid_row])
        self.login()

        def manual_create():
            response = self.client.post(reverse("staff_client_create"), self.manual_client_data())
            self.assertEqual(response.status_code, 302)
            return (
                "created" if Client.objects.filter(email="manual@example.com").exists() else "full"
            )

        results = self.race([lambda: self.execute(job).code, manual_create])
        self.assertEqual(Client.objects.filter(business=self.business).count(), 1)
        self.assertEqual(
            sum(result in (ClientImportExecutionCode.COMPLETED, "created") for result in results), 1
        )
