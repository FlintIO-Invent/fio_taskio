"""Operational quotas, real writer boundaries and PostgreSQL races."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import import_module
from io import StringIO
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, connections, transaction
from django.db.models import F
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice
from apps.billings.services import create_invoice_for_client
from apps.crm.importing.client_execution import ClientImportExecutionCode
from apps.crm.importing.service_execution import ServiceImportExecutionCode, execute_service_import
from apps.crm.models import BusinessService, Client, ServiceCategory
from apps.crm.test_client_execution import ClientExecutionTestMixin
from apps.crm.test_service_execution import ServiceExecutionTestMixin
from apps.logistics.billing_services import add_charge, invoice_charges
from apps.logistics.location_services import save_location
from apps.logistics.models import LogisticsLocation, Parcel, ParcelEvent
from apps.logistics.parcel_services import (
    change_parcel_status,
    register_parcel,
)
from apps.logistics.scan import resolve_scanned_parcel
from apps.logistics.shipment_services import create_shipment, generate_manifest

from .models import (
    Business,
    BusinessInvitation,
    BusinessSubscription,
    BusinessUser,
    ClarivoPlan,
    DemoSeedRun,
)
from .usage_limits import QuotaError, utc_month_bounds
from .utils import (
    CURRENT_BUSINESS_SESSION_KEY,
    PLAN_LIMIT_FIELDS,
    accept_business_invitation_for_user,
    create_or_refresh_business_invitation,
    get_business_usage_count,
)

SEED = import_module("apps.businesses.migrations.0029_logistics_capacity_plans")
HARD_LIMITS = (
    "users",
    "locations",
    "clients",
    "services",
    "parcels_per_month",
    "shipments_per_month",
    "invoices_per_month",
)


class QuotaFixture:
    def setUp(self):
        super().setUp()
        defaults = SEED.tier_defaults(*SEED.TIERS[0][1:])
        defaults["is_active"] = True
        self.plan, _ = ClarivoPlan.objects.update_or_create(
            slug="logistics-core", defaults=defaults
        )
        self.business = Business.objects.create(
            name="Quota fixture",
            slug="quota-fixture",
            vertical="LOGISTICS",
            country="Sint Maarten",
            timezone="Pacific/Kiritimati",
        )
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status="active",
            payment_provider="local",
            billing_interval="yearly",
            billing_currency="eur",
        )
        self.user = self.new_user()
        self.membership = BusinessUser.objects.create(
            business=self.business, user=self.user, role="owner"
        )
        self.customer = Client.objects.create(
            business=self.business,
            first_name="Existing",
            last_name="Customer",
            email="existing@example.test",
        )
        self.valid_row = {
            "first_name": "New",
            "last_name": "Customer",
            "email": "new@example.test",
            "phone": "+1 721 555 0100",
            "company_name": "Cargo",
            "street_address": "12 Example Street",
        }
        self.parcel_fields = {
            "origin": "Miami",
            "destination": "Curacao",
            "package_description": "Books",
            "quantity": 1,
        }

    def new_user(self):
        return TaskIOUser.objects.create_user(
            email=f"quota-{uuid.uuid4().hex}@example.test", password="fixture-only-password"
        )

    def limit(self, metric, value):
        ClarivoPlan.objects.filter(pk=self.plan.pk).update(**{PLAN_LIMIT_FIELDS[metric]: value})
        self.plan.refresh_from_db()
        self.business.refresh_from_db()

    def create(self, metric):
        key = uuid.uuid4().hex[:16]
        with transaction.atomic():
            if metric == "users":
                return BusinessUser.objects.create(
                    business=self.business, user=self.new_user(), role="staff"
                )
            if metric == "locations":
                return save_location(
                    business=self.business,
                    actor=self.user,
                    code=f"S-{key}",
                    name=f"Site {key}",
                    location_type="WAREHOUSE",
                    country_code="SX",
                    city="Philipsburg",
                    is_active=True,
                )
            if metric == "clients":
                return Client.objects.create(
                    business=self.business,
                    first_name="New",
                    last_name=key,
                    email=f"{key}@example.test",
                )
            if metric == "services":
                return BusinessService.objects.create(
                    business=self.business, name=f"Freight {key}", unit_price="1.00"
                )
            if metric == "parcels_per_month":
                return register_parcel(
                    business=self.business,
                    actor=self.user,
                    client=self.customer,
                    idempotency_key=uuid.uuid4(),
                    **self.parcel_fields,
                )
            if metric == "shipments_per_month":
                return create_shipment(
                    business=self.business,
                    actor=self.user,
                    idempotency_key=uuid.uuid4(),
                    origin="Miami",
                    destination="Curacao",
                )
            return create_invoice_for_client(actor=self.user, client=self.customer)

    def login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()


@override_settings(
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class LogisticsQuotaTests(QuotaFixture, TestCase):
    def test_all_seven_limits_at_n_minus_one_n_and_n_plus_one(self):
        # Small, explicit plan fixtures exercise the same resolver and boundary;
        # Block B tests separately assert every actual Core/Growth/Scale value.
        for metric in HARD_LIMITS:
            with self.subTest(metric=metric):
                self.limit(metric, 2)
                if get_business_usage_count(self.business, metric) == 0:
                    self.create(metric)
                self.assertEqual(get_business_usage_count(self.business, metric), 1)
                self.create(metric)
                self.assertEqual(get_business_usage_count(self.business, metric), 2)
                with self.assertRaises(QuotaError):
                    self.create(metric)
                self.assertEqual(get_business_usage_count(self.business, metric), 2)

    def test_real_owner_inclusive_seat_limits_for_all_tiers(self):
        for slug, name, yearly, capacities in SEED.TIERS:
            with self.subTest(slug=slug), transaction.atomic():
                plan, _ = ClarivoPlan.objects.update_or_create(
                    slug=slug,
                    defaults={**SEED.tier_defaults(name, yearly, capacities), "is_active": True},
                )
                self.subscription.plan = plan
                self.subscription.save(update_fields=["plan"])
                self.business.refresh_from_db()
                target = capacities[0]
                while get_business_usage_count(self.business, "users") < target - 1:
                    self.create("users")
                self.create("users")
                with self.assertRaises(QuotaError):
                    self.create("users")
                self.assertEqual(get_business_usage_count(self.business, "users"), target)

    def test_client_service_location_and_membership_reactivation(self):
        for metric, model in (
            ("clients", Client),
            ("services", BusinessService),
            ("locations", LogisticsLocation),
            ("users", BusinessUser),
        ):
            with self.subTest(metric=metric):
                record = self.create(metric)
                record.is_active = False
                record.save(update_fields=["is_active"])
                count = get_business_usage_count(self.business, metric)
                self.limit(metric, count)
                record.is_active = True
                with self.assertRaises(QuotaError):
                    record.save(update_fields=["is_active"])
                self.limit(metric, count + 1)
                model.objects.filter(pk=record.pk).update(is_active=True)
                self.assertEqual(get_business_usage_count(self.business, metric), count + 1)

    def test_archived_client_status_and_partial_save_projection(self):
        self.limit("clients", 1)
        archived = Client.objects.create(
            business=self.business,
            first_name="Archived",
            last_name="Customer",
            client_status="ARCHIVED",
        )
        archived.client_status = "ACTIVE"
        archived.first_name = "Renamed"
        archived.save(update_fields=["first_name"])
        archived.refresh_from_db()
        self.assertEqual(archived.client_status, "ARCHIVED")
        with self.assertRaises(QuotaError):
            Client.objects.filter(pk=archived.pk).update(client_status="ACTIVE")
        self.customer.is_active = False
        self.customer.save(update_fields=["is_active"])
        Client.objects.filter(pk=archived.pk).update(client_status="ACTIVE")

    def test_bulk_create_rollback_and_same_object_retry(self):
        self.limit("clients", 2)
        rows = [
            Client(business=self.business, first_name="Bulk", last_name=str(i)) for i in range(2)
        ]
        with self.assertRaises(QuotaError):
            Client.objects.bulk_create(rows)
        self.assertEqual(Client.objects.filter(business=self.business).count(), 1)
        self.assertTrue(all(row.pk is None and row._state.adding for row in rows))
        self.limit("clients", 3)
        Client.objects.bulk_create(rows)
        self.assertEqual(get_business_usage_count(self.business, "clients"), 3)

    def test_bulk_reactivation_is_atomic_and_expression_bypass_is_rejected(self):
        rows = [
            Client.objects.create(
                business=self.business, first_name="Inactive", last_name=str(i), is_active=False
            )
            for i in range(2)
        ]
        self.limit("clients", 2)
        with self.assertRaises(QuotaError):
            Client.objects.filter(pk__in=[row.pk for row in rows]).update(is_active=True)
        self.assertFalse(
            Client.objects.filter(pk__in=[row.pk for row in rows], is_active=True).exists()
        )
        for row in rows:
            row.is_active = True
        with self.assertRaises(QuotaError):
            Client.objects.bulk_update(rows, ["is_active"])
        with self.assertRaises(QuotaError):
            Client.objects.filter(pk=self.customer.pk).update(is_active=F("is_active"))
        rows[0].is_active = F("is_active")
        with self.assertRaises(QuotaError):
            Client.objects.bulk_update(rows[:1], ["is_active"])

    def test_direct_invoice_bulk_is_atomic_metered_and_retryable(self):
        self.limit("invoices_per_month", 1)
        rows = [
            Invoice(business=self.business, client=self.customer, invoice_number=f"BULK-{i}")
            for i in range(2)
        ]
        with self.assertRaises(QuotaError):
            Invoice.objects.bulk_create(rows)
        self.assertFalse(Invoice.objects.filter(business=self.business).exists())
        self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 0)
        self.assertTrue(all(row.pk is None and row._state.adding for row in rows))
        self.limit("invoices_per_month", 2)
        Invoice.objects.bulk_create(rows)
        self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 2)
        with self.assertRaises(QuotaError):
            Invoice.objects.create(
                business=self.business, client=self.customer, invoice_number="OVER-CAPACITY"
            )
        with self.assertRaises(QuotaError):
            Client.objects.bulk_create(
                [Client(business=self.business, first_name="Conflict", last_name="Candidate")],
                ignore_conflicts=True,
            )

    def test_monthly_bootstrap_counts_current_month_then_never_recounts_history(self):
        # An explicit legacy-to-tier fixture represents a future reviewed move.
        legacy = ClarivoPlan.objects.get(slug="logistics")
        legacy.is_active = True
        legacy.save(update_fields=["is_active"])
        self.subscription.plan = legacy
        self.subscription.save(update_fields=["plan"])
        first = self.create("invoices_per_month")
        self.subscription.plan = self.plan
        self.subscription.save(update_fields=["plan"])
        self.limit("invoices_per_month", 2)
        second = self.create("invoices_per_month")
        self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 2)
        first.delete()
        second.delete()
        with self.assertRaises(QuotaError):
            self.create("invoices_per_month")

    def test_corrupt_monthly_meter_and_incomplete_tier_fail_closed(self):
        key = utc_month_bounds()[0].strftime("%Y-%m")
        for invalid in (
            [1],
            {key: []},
            {key: {"invoices_per_month": -1}},
            {key: {"invoices_per_month": True}},
            {key: {"invoices_per_month": None}},
        ):
            with self.subTest(invalid=invalid):
                BusinessSubscription.objects.filter(pk=self.subscription.pk).update(
                    logistics_monthly_usage=invalid
                )
                with self.assertRaises(QuotaError):
                    self.create("invoices_per_month")
        self.limit("clients", None)
        with self.assertRaises(QuotaError):
            self.create("clients")
        self.customer.first_name = "Retained"
        self.customer.save(update_fields=["first_name"])

    def test_tenant_moves_cannot_hide_capacity_consumption(self):
        other = Business.objects.create(name="Other", slug="other", vertical="SERVICE")
        with self.assertRaises(QuotaError):
            Client.objects.filter(pk=self.customer.pk).update(business=other)
        self.customer.business = other
        with self.assertRaises(QuotaError):
            self.customer.save(update_fields=["business"])
        BusinessSubscription.objects.create(business=other, plan=ClarivoPlan.objects.get(slug="starter"), status="active")
        outsider = Client.objects.create(business=other, first_name="Other", last_name="Tenant")
        with self.assertRaises(QuotaError):
            Client.objects.filter(pk=outsider.pk).update(business=self.business)
        outsider.business = self.business
        with self.assertRaises(QuotaError):
            Client.objects.bulk_update([outsider], ["business"])
        outsider.refresh_from_db()
        self.assertEqual(outsider.business_id, other.pk)

    def test_demo_management_command_has_no_quota_exemption_or_partial_records(self):
        self.limit("clients", 2)
        with self.assertRaisesMessage(CommandError, "allowance"):
            call_command(
                "seed_logistics_demo_data",
                business_id=self.business.pk,
                actor_id=self.user.pk,
                execute=True,
                stdout=StringIO(),
            )
        self.assertEqual(get_business_usage_count(self.business, "clients"), 1)
        self.assertFalse(DemoSeedRun.objects.filter(business=self.business).exists())
        self.assertFalse(Parcel.objects.filter(business=self.business).exists())

    def test_invitation_reserves_one_slot_acceptance_and_refresh_do_not_double_count(self):
        self.limit("users", 2)
        invitee = self.new_user()
        invitation, _ = create_or_refresh_business_invitation(
            business=self.business, email=invitee.email, role="staff", invited_by=self.user
        )
        same, created = create_or_refresh_business_invitation(
            business=self.business, email=invitee.email.upper(), role="staff", invited_by=self.user
        )
        self.assertFalse(created)
        self.assertEqual(same.pk, invitation.pk)
        self.assertEqual(
            get_business_usage_count(self.business, "users", include_pending_invitations=True), 2
        )
        with self.assertRaises(QuotaError):
            self.create("users")
        member, created, _ = accept_business_invitation_for_user(invitation, invitee)
        self.assertTrue(created)
        self.assertTrue(member.is_active)
        self.assertEqual(
            get_business_usage_count(self.business, "users", include_pending_invitations=True), 2
        )
        self.assertEqual(invitation.status, "accepted")

    def test_expired_invitation_reactivation_and_membership_acceptance(self):
        self.limit("users", 2)
        invitee = self.new_user()
        member = BusinessUser.objects.create(
            business=self.business, user=invitee, role="staff", is_active=False
        )
        invitation = BusinessInvitation.objects.create(
            business=self.business,
            email=invitee.email,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.create("users")
        with self.assertRaises(QuotaError):
            create_or_refresh_business_invitation(
                business=self.business, email=invitee.email, role="staff", invited_by=self.user
            )
        with self.assertRaises(QuotaError):
            BusinessUser.objects.filter(pk=member.pk).update(is_active=True)
        self.assertEqual(get_business_usage_count(self.business, "users"), 2)
        self.assertTrue(invitation.is_expired)

    def test_utc_month_boundary_ignores_business_timezone_and_deletion_never_refunds(self):
        self.limit("invoices_per_month", 1)
        last = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
        first = datetime(2027, 1, 1, tzinfo=UTC)
        with patch("django.utils.timezone.now", return_value=last):
            previous = self.create("invoices_per_month")
            previous.delete()
            self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 1)
            with self.assertRaises(QuotaError):
                self.create("invoices_per_month")
        with patch("django.utils.timezone.now", return_value=first):
            self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 0)
            current = self.create("invoices_per_month")
            self.assertEqual(current.created_at, first)
        self.subscription.refresh_from_db()
        self.assertEqual(
            self.subscription.logistics_monthly_usage["2026-12"]["invoices_per_month"], 1
        )
        self.assertEqual(
            self.subscription.logistics_monthly_usage["2027-01"]["invoices_per_month"], 1
        )
        self.assertEqual(utc_month_bounds(first)[0], first)

    def test_rollover_during_insert_is_metered_at_saved_creation_time(self):
        old = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
        new = datetime(2027, 1, 1, tzinfo=UTC)
        from . import usage_limits

        original = usage_limits.monthly_usage
        calls = []

        def rollover(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                with patch("django.utils.timezone.now", return_value=old):
                    return original(*args, **kwargs)
            return original(*args, **kwargs)

        with (
            patch("django.utils.timezone.now", return_value=new),
            patch.object(usage_limits, "monthly_usage", side_effect=rollover),
        ):
            invoice = self.create("invoices_per_month")
        self.subscription.refresh_from_db()
        self.assertEqual(invoice.created_at, new)
        self.assertNotIn("2026-12", self.subscription.logistics_monthly_usage)
        self.assertEqual(
            self.subscription.logistics_monthly_usage["2027-01"]["invoices_per_month"], 1
        )

    def test_counter_and_invoice_rollback_with_outer_failure_and_stale_subscription_save(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.create("invoices_per_month")
            raise RuntimeError("rollback fixture")
        self.assertEqual(Invoice.objects.filter(business=self.business).count(), 0)
        self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 0)
        self.create("invoices_per_month")
        self.subscription.save()
        self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 1)
        invoice = Invoice.objects.get(business=self.business)
        with self.assertRaises(QuotaError):
            Invoice.objects.filter(pk=invoice.pk).update(
                created_at=timezone.now() - timedelta(days=90)
            )

    def test_restricted_states_block_only_new_capacity(self):
        parcel = self.create("parcels_per_month")
        for status in ("past_due", "expired", "cancelled", "suspended"):
            with self.subTest(status=status):
                self.subscription.status = status
                self.subscription.save(update_fields=["status"])
                with self.assertRaises(QuotaError):
                    self.create("clients")
                self.customer.first_name = "Still retained"
                self.customer.save(update_fields=["first_name"])
                self.assertTrue(Parcel.objects.filter(pk=parcel.pk).exists())

    def test_legacy_unlimited_is_unchanged_and_services_use_their_own_guard(self):
        legacy = ClarivoPlan.objects.get(slug="logistics")
        legacy.is_active = True
        legacy.save(update_fields=["is_active"])
        self.subscription.plan = legacy
        self.subscription.save(update_fields=["plan"])
        for metric in HARD_LIMITS:
            self.create(metric)
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.logistics_monthly_usage)
        self.business.vertical = "SERVICE"
        self.business.save(update_fields=["vertical"])
        self.subscription.plan = ClarivoPlan.objects.get(slug="starter")
        self.subscription.save(update_fields=["plan"])
        rows = [
            Client(business=self.business, first_name="Service", last_name=str(i)) for i in range(3)
        ]
        Client.objects.bulk_create(rows)
        with self.assertRaises(QuotaError):
            Client.objects.filter(pk__in=[r.pk for r in rows]).update(is_active=F("is_active"))
        self.assertEqual(Client.objects.filter(pk__in=[r.pk for r in rows]).update(is_active=True), 3)

    def test_retry_scan_and_event_over_budget_never_consume_again_or_block_status(self):
        self.limit("parcels_per_month", 1)
        key = uuid.uuid4()
        parcel = register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            idempotency_key=key,
            **self.parcel_fields,
        )
        replay = register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            idempotency_key=key,
            **self.parcel_fields,
        )
        self.assertEqual(parcel.pk, replay.pk)
        self.limit("parcel_events_per_month", 1)
        for _ in range(3):
            self.assertEqual(
                resolve_scanned_parcel(
                    business=self.business, actor=self.user, code=parcel.tracking_code
                ).pk,
                parcel.pk,
            )
        change_parcel_status(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            status="RECEIVED",
            idempotency_key=uuid.uuid4(),
        )
        self.assertGreater(ParcelEvent.objects.filter(business=self.business).count(), 1)
        self.assertEqual(get_business_usage_count(self.business, "parcels_per_month"), 1)
        shipment_key = uuid.uuid4()
        self.limit("shipments_per_month", 1)
        shipment = create_shipment(
            business=self.business,
            actor=self.user,
            idempotency_key=shipment_key,
            origin="Miami",
            destination="Curacao",
        )
        self.assertEqual(
            create_shipment(
                business=self.business,
                actor=self.user,
                idempotency_key=shipment_key,
                origin="Miami",
                destination="Curacao",
            ).pk,
            shipment.pk,
        )
        self.assertEqual(
            generate_manifest(business=self.business, actor=self.user, shipment=shipment)[
                "parcel_count"
            ],
            0,
        )

    def test_charge_invoice_flow_replay_and_append_do_not_consume_new_invoice(self):
        parcel = self.create("parcels_per_month")
        charge = add_charge(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            idempotency_key=uuid.uuid4(),
            description="Freight",
            quantity="1",
            unit_price="10",
        )
        self.limit("invoices_per_month", 1)
        invoice = invoice_charges(business=self.business, actor=self.user, charge_ids=[charge.pk])
        self.assertEqual(
            invoice_charges(business=self.business, actor=self.user, charge_ids=[charge.pk]).pk,
            invoice.pk,
        )
        second = add_charge(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            idempotency_key=uuid.uuid4(),
            description="Handling",
            quantity="1",
            unit_price="2",
        )
        invoice_charges(
            business=self.business, actor=self.user, charge_ids=[second.pk], invoice=invoice
        )
        self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 1)
        third = add_charge(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            idempotency_key=uuid.uuid4(),
            description="Other",
            quantity="1",
            unit_price="3",
        )
        with self.assertRaises(QuotaError):
            invoice_charges(business=self.business, actor=self.user, charge_ids=[third.pk])
        self.assertEqual(Invoice.objects.filter(business=self.business).count(), 1)

    def test_http_reactivation_and_catalog_create_return_clear_capacity_error(self):
        self.login()
        self.limit("clients", 1)
        self.limit("services", 0)
        response = self.client.post(
            reverse("business_service_create"),
            {
                "name": "Over budget",
                "unit_price": "10",
                "is_active": "on",
                "new_category_name": "Rollback category",
            },
        )
        self.assertContains(response, "allowance", status_code=409)
        self.assertFalse(ServiceCategory.objects.filter(business=self.business).exists())
        response = self.client.post(
            reverse("business_service_create"),
            {"name": "API catalog", "unit_price": "10", "is_active": "on"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("allowance", response.json()["errors"]["__all__"][0])
        response = self.client.post(
            reverse("invoice_quick_create_client"),
            {**self.valid_row},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)  # existing friendly precheck
        self.assertIn("errors", response.json())


@override_settings(
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class LogisticsQuotaClientImportTests(QuotaFixture, TestCase):
    upload = ClientExecutionTestMixin.upload
    ready_job = ClientExecutionTestMixin.ready_job
    execute = ClientExecutionTestMixin.execute

    def test_core_csv_entire_batch_rechecks_capacity_and_replay_is_idempotent(self):
        self.limit("clients", 3)
        rows = [
            self.valid_row,
            {**self.valid_row, "email": "second@example.test", "phone": "+1 721 555 0200"},
        ]
        job = self.ready_job(rows)
        self.create("clients")
        self.assertEqual(self.execute(job).code, ClientImportExecutionCode.CAPACITY_CHANGED)
        self.assertEqual(get_business_usage_count(self.business, "clients"), 2)
        fresh = self.ready_job([self.valid_row])
        self.assertEqual(self.execute(fresh).code, ClientImportExecutionCode.COMPLETED)
        self.assertEqual(self.execute(fresh).code, ClientImportExecutionCode.ALREADY_COMPLETED)


@override_settings(
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class LogisticsQuotaServiceImportTests(QuotaFixture, TestCase):
    upload = ServiceExecutionTestMixin.upload
    job_for = ServiceExecutionTestMixin.job_for
    ready_job = ServiceExecutionTestMixin.ready_job

    def test_core_service_csv_rolls_back_categories_and_rows_on_capacity_failure(self):
        self.limit("services", 1)
        job = self.ready_job(
            [
                {"name": "First", "unit_price": "1", "category": "New category"},
                {"name": "Second", "unit_price": "2", "category": "New category"},
            ],
            headers=("name", "unit_price", "category"),
        )
        result = execute_service_import(job_id=job.pk, business=self.business, actor=self.user)
        self.assertEqual(result.code, ServiceImportExecutionCode.CAPACITY_CHANGED)
        self.assertFalse(BusinessService.objects.filter(business=self.business).exists())
        self.assertFalse(ServiceCategory.objects.filter(business=self.business).exists())


@skipUnless(connection.vendor == "postgresql", "Quota concurrency requires real PostgreSQL")
@override_settings(
    LOGISTICS_LOCAL_BILLING_BYPASS=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class LogisticsQuotaConcurrencyTests(QuotaFixture, TransactionTestCase):
    def race(self, actions):
        barrier = Barrier(len(actions))

        def worker(action):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                try:
                    action()
                    return "created"
                except QuotaError:
                    return "full"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            futures = [pool.submit(worker, action) for action in actions]
            return [future.result(timeout=40) for future in futures]

    def test_competing_writers_for_each_of_seven_last_slots(self):
        for metric in HARD_LIMITS:
            with self.subTest(metric=metric):
                self.limit(metric, 2)
                if get_business_usage_count(self.business, metric) == 0:
                    self.create(metric)
                self.assertCountEqual(
                    self.race([lambda metric=metric: self.create(metric)] * 2), ["created", "full"]
                )
                self.assertEqual(get_business_usage_count(self.business, metric), 2)

    def test_bulk_and_manual_clients_share_the_same_last_slot(self):
        self.limit("clients", 2)
        self.assertCountEqual(
            self.race(
                [
                    lambda: self.create("clients"),
                    lambda: Client.objects.bulk_create(
                        [Client(business=self.business, first_name="Bulk", last_name="Candidate")]
                    ),
                ]
            ),
            ["created", "full"],
        )
        self.assertEqual(get_business_usage_count(self.business, "clients"), 2)

    def test_concurrent_same_parcel_retry_consumes_once(self):
        self.limit("parcels_per_month", 1)
        key = uuid.uuid4()
        self.assertEqual(
            self.race(
                [
                    lambda: register_parcel(
                        business=self.business,
                        actor=self.user,
                        client=self.customer,
                        idempotency_key=key,
                        **self.parcel_fields,
                    )
                ]
                * 2
            ),
            ["created", "created"],
        )
        self.assertEqual(get_business_usage_count(self.business, "parcels_per_month"), 1)

    def test_invitation_and_membership_reactivation_compete_for_last_seat(self):
        member = BusinessUser.objects.create(
            business=self.business, user=self.new_user(), role="staff", is_active=False
        )
        self.limit("users", 2)
        self.assertCountEqual(
            self.race(
                [
                    lambda: BusinessUser.objects.filter(pk=member.pk).update(is_active=True),
                    lambda: create_or_refresh_business_invitation(
                        business=self.business,
                        email="pending@example.test",
                        role="staff",
                        invited_by=self.user,
                    ),
                ]
            ),
            ["created", "full"],
        )
        self.assertEqual(
            get_business_usage_count(self.business, "users", include_pending_invitations=True), 2
        )

    def test_location_reactivations_compete_for_last_active_location(self):
        rows = [
            LogisticsLocation.objects.create(
                business=self.business,
                code=f"INACTIVE-{i}",
                name=f"Inactive {i}",
                location_type="WAREHOUSE",
                country_code="SX",
                is_active=False,
            )
            for i in range(2)
        ]
        self.limit("locations", 1)
        self.assertCountEqual(
            self.race(
                [
                    lambda row=row: LogisticsLocation.objects.filter(pk=row.pk).update(
                        is_active=True
                    )
                    for row in rows
                ]
            ),
            ["created", "full"],
        )
        self.assertEqual(get_business_usage_count(self.business, "locations"), 1)

    def test_direct_invoice_bulk_and_service_creation_share_last_monthly_slot(self):
        self.limit("invoices_per_month", 1)
        self.assertCountEqual(
            self.race(
                [
                    lambda: self.create("invoices_per_month"),
                    lambda: Invoice.objects.bulk_create(
                        [
                            Invoice(
                                business=self.business,
                                client=self.customer,
                                invoice_number="RACE-BULK",
                            )
                        ]
                    ),
                ]
            ),
            ["created", "full"],
        )
        self.assertEqual(get_business_usage_count(self.business, "invoices_per_month"), 1)

    def test_concurrent_insert_cannot_enter_unguarded_bulk_reactivation_remainder(self):
        from .usage_limits import CapacityQuerySet

        old = Client.objects.create(
            business=self.business, first_name="Old", last_name="Inactive", is_active=False
        )
        self.limit("clients", 2)
        selected, inserted = Event(), Event()
        original = CapacityQuerySet._tier_ids
        late = []

        def pause_after_selection(query):
            ids = list(original(query))
            selected.set()
            if not inserted.wait(timeout=15):
                raise RuntimeError("Concurrent insertion did not finish")
            return ids

        def insert_late():
            if not selected.wait(timeout=15):
                raise RuntimeError("Bulk selection did not finish")
            late.append(
                Client.objects.create(
                    business=self.business, first_name="Late", last_name="Inactive", is_active=False
                ).pk
            )
            inserted.set()

        with patch.object(CapacityQuerySet, "_tier_ids", pause_after_selection):
            self.assertEqual(
                self.race(
                    [
                        lambda: Client.objects.filter(
                            business=self.business, is_active=False
                        ).update(is_active=True),
                        insert_late,
                    ]
                ),
                ["created", "created"],
            )
        old.refresh_from_db()
        self.assertTrue(old.is_active)
        self.assertFalse(Client.objects.get(pk=late[0]).is_active)
        self.assertEqual(get_business_usage_count(self.business, "clients"), 2)
