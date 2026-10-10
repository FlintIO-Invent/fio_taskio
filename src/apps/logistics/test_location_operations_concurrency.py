"""Real PostgreSQL verification for status receipts, site revocation and cargo locks."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessUser

from . import parcel_services, test_concurrency
from .location_access_services import (
    enable_location_operations,
    review_location_access,
    select_work_location,
    set_location_assignment,
)
from .models import LogisticsLocation, Parcel, ParcelEvent
from .parcel_services import change_parcel_status, register_parcel
from .shipment_services import assign_parcel, change_shipment_status, create_shipment


@skipUnless(connection.vendor == "postgresql", "Verified operations require PostgreSQL row locks")
class VerifiedOperationConcurrencyTests(TransactionTestCase):
    setUp_base = test_concurrency.LogisticsOperationConcurrencyTests.setUp

    def setUp(self):
        self.setUp_base()
        self.a, self.b = [
            LogisticsLocation.objects.create(
                business=self.business, name=name, code=name, location_type="HUB", country_code="US"
            )
            for name in ("ORIGIN", "DESTINATION")
        ]
        self.staff = TaskIOUser.objects.create_user(email="verified-concurrent@example.test")
        self.member = BusinessUser.objects.create(
            business=self.business, user=self.staff, role="staff"
        )
        for site in (self.a, self.b):
            set_location_assignment(
                business=self.business,
                actor=self.user,
                membership=self.member,
                location=site,
                can_operate=True,
            )
        review_location_access(business=self.business, actor=self.user)
        select_work_location(business=self.business, actor=self.user, location=self.a)
        enable_location_operations(business=self.business, actor=self.user)
        self.item = register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            origin="Miami",
            destination="Sint Maarten",
            package_description="Books",
            origin_location=self.a,
            destination_location=self.b,
        )

    def act(self, status, **kwargs):
        return change_parcel_status(
            business=self.business, actor=self.staff, parcel=self.item, status=status, **kwargs
        )

    def ship(self):
        item = create_shipment(
            business=self.business,
            actor=self.user,
            origin="Miami",
            destination="Sint Maarten",
            origin_location=self.a,
            destination_location=self.b,
        )
        assign_parcel(business=self.business, actor=self.staff, parcel=self.item, shipment=item)
        self.act("RECEIVED")
        return change_shipment_status(
            business=self.business, actor=self.staff, shipment=item, status="READY"
        )

    def test_same_status_retry_race_creates_one_site_audited_event(self):
        key = uuid.uuid4()
        results = test_concurrency.race(
            [lambda: self.act("RECEIVED", expected_status="REGISTERED", idempotency_key=key).pk] * 2
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.item.events.count(), 2)
        self.assertEqual(self.item.events.latest("pk").operational_location_id, self.a.pk)

    def test_competing_new_status_writes_reject_stale_state(self):
        results = test_concurrency.race(
            [
                lambda status=status: self.act(status, expected_status="REGISTERED").pk
                for status in ("RECEIVED", "HOLD")
            ]
        )
        self.assertCountEqual([result[0] for result in results], ["ok", "rejected"])
        self.assertEqual(self.item.events.count(), 2)

    def test_shipment_departure_race_propagates_once_with_one_audit_entry(self):
        shipment = self.ship()
        key = uuid.uuid4()
        results = test_concurrency.race(
            [
                lambda: change_shipment_status(
                    business=self.business,
                    actor=self.staff,
                    shipment=shipment,
                    status="IN_TRANSIT",
                    expected_status="READY",
                    expected_revision=shipment.revision,
                    idempotency_key=key,
                ).pk
            ]
            * 2
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.item.events.filter(status="IN_TRANSIT").count(), 1)
        shipment.refresh_from_db()
        self.assertEqual(
            sum(entry["new_state"] == "IN_TRANSIT" for entry in shipment.operation_history), 1
        )

    def test_location_revocation_before_waiting_write_leaves_no_success_event(self):
        entered = Event()

        def worker():
            close_old_connections()
            entered.set()
            try:
                self.act("RECEIVED")
                return "updated"
            except PermissionDenied:
                return "denied"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Business.objects.select_for_update().get(pk=self.business.pk)
                future = pool.submit(worker)
                self.assertTrue(entered.wait(timeout=10))
                self.assertFalse(future.done())
                set_location_assignment(
                    business=self.business,
                    actor=self.user,
                    membership=self.member,
                    location=self.a,
                    revoke=True,
                )
            self.assertEqual(future.result(timeout=30), "denied")
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_status, Parcel.Status.REGISTERED)
        self.assertEqual(self.item.events.count(), 1)

    def test_ship_revision_rejects_concurrent_stale_departure_without_extra_events(self):
        shipment = self.ship()
        results = test_concurrency.race(
            [
                lambda: change_shipment_status(
                    business=self.business,
                    actor=self.staff,
                    shipment=shipment,
                    status="IN_TRANSIT",
                    expected_revision=shipment.revision,
                ).pk
            ]
            * 2
        )
        self.assertCountEqual([result[0] for result in results], ["ok", "rejected"])
        self.assertEqual(
            ParcelEvent.objects.filter(parcel=self.item, status="IN_TRANSIT").count(), 1
        )

    def test_team_deactivation_waits_for_authorized_write_then_blocks_next_action(self):
        entered, release, revoke_entered = Event(), Event(), Event()
        original = parcel_services.validate_transition_location

        def paused_validation(*args, **kwargs):
            result = original(*args, **kwargs)
            entered.set()
            if not release.wait(timeout=10):
                raise RuntimeError("Timed out waiting for membership race verification.")
            return result

        def operate():
            close_old_connections()
            try:
                return self.act("RECEIVED").pk
            finally:
                connections.close_all()

        def deactivate():
            close_old_connections()
            try:
                revoke_entered.set()
                # Same row update as existing shared team deactivation, no Business lock.
                return BusinessUser.objects.filter(pk=self.member.pk).update(is_active=False)
            finally:
                connections.close_all()

        with patch.object(parcel_services, "validate_transition_location", paused_validation):
            with ThreadPoolExecutor(max_workers=2) as pool:
                operation = pool.submit(operate)
                self.assertTrue(entered.wait(timeout=10))
                revocation = pool.submit(deactivate)
                self.assertTrue(revoke_entered.wait(timeout=10))
                try:
                    with self.assertRaises(TimeoutError):
                        revocation.result(timeout=0.2)
                finally:
                    release.set()
                self.assertIsNotNone(operation.result(timeout=30))
                self.assertEqual(revocation.result(timeout=30), 1)
        with self.assertRaises(PermissionDenied):
            self.act("IN_TRANSIT")
        self.assertEqual(self.item.events.count(), 2)
