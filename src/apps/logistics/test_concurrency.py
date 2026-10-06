"""Real PostgreSQL transactions; SQLite cannot establish row-lock behavior."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from apps.accounts.models import TaskIOUser, TaskIOUserManager
from apps.businesses.business_data_purge import purge_business
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.crm.models import Client

from .enrollment import enroll_application, issue_enrollment_link
from .models import LogisticsApplication, Parcel, ParcelEvent, Shipment
from .parcel_services import change_parcel_status, edit_parcel, register_parcel
from .shipment_services import assign_parcel, change_shipment_status, create_shipment
from .test_enrollment import PASSWORD, approve, reviewer
from .tests import PILOT_POLICY, application_data


def race(actions):
    barrier = Barrier(len(actions))

    def worker(action):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                return "ok", action()
            except (ValidationError, PermissionDenied) as exc:
                return "rejected", type(exc).__name__
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        futures = [pool.submit(worker, action) for action in actions]
        return [future.result(timeout=30) for future in futures]


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency requires PostgreSQL")
@override_settings(LOGISTICS_ELIGIBILITY_POLICY=PILOT_POLICY)
class EnrollmentIdentityConcurrencyTests(TransactionTestCase):
    def setUp(self):
        ClarivoPlan.objects.get_or_create(
            slug="logistics",
            defaults={"name": "Logistics", "family": "LOGISTICS", "is_active": False},
        )
        self.actor = reviewer()

    def grant(self, name):
        application = LogisticsApplication.objects.create(**application_data(business_name=name))
        approve(application, self.actor)
        return issue_enrollment_link(application.pk, actor=self.actor, expected_revision=1)

    def test_anonymous_same_grant_race_creates_one_user_business_and_subscription(self):
        token = self.grant("One applicant")
        results = race([lambda: enroll_application(token, password=PASSWORD).business.pk] * 2)
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        self.assertEqual(
            TaskIOUser.objects.filter(email__iexact="applicant@example.com").count(), 1
        )
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessUser.objects.count(), 1)
        self.assertEqual(BusinessSubscription.objects.count(), 1)

    def test_two_applications_new_email_race_rolls_back_losing_conversion(self):
        tokens = [self.grant(name) for name in ("First applicant", "Second applicant")]
        insert_barrier = Barrier(2)
        original_create = TaskIOUserManager.create_user

        def simultaneous_insert(manager, *args, **kwargs):
            insert_barrier.wait(timeout=10)
            return original_create(manager, *args, **kwargs)

        with patch.object(TaskIOUserManager, "create_user", simultaneous_insert):
            results = race(
                [
                    lambda token=token: enroll_application(token, password=PASSWORD).business.pk
                    for token in tokens
                ]
            )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        self.assertEqual(
            TaskIOUser.objects.filter(email__iexact="applicant@example.com").count(), 1
        )
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessSubscription.objects.count(), 1)
        self.assertEqual(LogisticsApplication.objects.filter(converted_at__isnull=False).count(), 1)
        losing = LogisticsApplication.objects.get(converted_at__isnull=True)
        self.assertIsNone(losing.enrollment_tokens.get().used_at)


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency requires PostgreSQL")
class LogisticsOperationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        plan, _ = ClarivoPlan.objects.get_or_create(
            slug="logistics", defaults={"name": "Logistics", "family": "LOGISTICS"}
        )
        plan.is_active = True
        plan.save(update_fields=["is_active"])
        self.business = Business.objects.create(
            name="Courier", slug="concurrent-courier", vertical="LOGISTICS"
        )
        self.user = TaskIOUser.objects.create_user(
            email="concurrent@example.test", password=PASSWORD
        )
        BusinessUser.objects.create(business=self.business, user=self.user, role="owner")
        BusinessSubscription.objects.create(
            business=self.business, plan=plan, status="active", billing_interval="yearly"
        )
        self.customer = Client.objects.create(
            business=self.business, first_name="Pilot", last_name="Customer"
        )

    def parcel(self, **kwargs):
        return register_parcel(
            business=self.business,
            actor=self.user,
            client=self.customer,
            origin="Miami",
            destination="Sint Maarten",
            package_description="Books",
            **kwargs,
        )

    def shipment(self):
        return create_shipment(
            business=self.business, actor=self.user, origin="Miami", destination="Sint Maarten"
        )

    def test_registration_retry_race_creates_one_parcel_and_initial_event(self):
        key = uuid.uuid4()
        results = race([lambda: self.parcel(idempotency_key=key).pk] * 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(Parcel.objects.count(), 1)
        self.assertEqual(ParcelEvent.objects.count(), 1)

    def test_competing_metadata_edits_reject_the_stale_writer(self):
        parcel = self.parcel()
        expected = parcel.updated_at
        results = race(
            [
                lambda sender=sender: edit_parcel(
                    business=self.business,
                    actor=self.user,
                    parcel=parcel,
                    expected_updated_at=expected,
                    sender_name=sender,
                ).sender_name
                for sender in ("First sender", "Second sender")
            ]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        parcel.refresh_from_db()
        winner = next(value for status, value in results if status == "ok")
        self.assertEqual(parcel.sender_name, winner)
        self.assertEqual(parcel.events.count(), 2)

    def test_metadata_edit_and_status_change_preserve_both_changes(self):
        parcel = self.parcel()
        results = race(
            [
                lambda: edit_parcel(
                    business=self.business,
                    actor=self.user,
                    parcel=parcel,
                    sender_name="Edited sender",
                ).pk,
                lambda: change_parcel_status(
                    business=self.business,
                    actor=self.user,
                    parcel=parcel,
                    status="RECEIVED",
                    expected_status="REGISTERED",
                ).pk,
            ]
        )
        self.assertEqual([status for status, _ in results], ["ok", "ok"])
        parcel.refresh_from_db()
        self.assertEqual((parcel.sender_name, parcel.current_status), ("Edited sender", "RECEIVED"))
        self.assertEqual(parcel.events.count(), 3)

    def test_event_retry_race_appends_once_even_with_stale_expected_status(self):
        parcel = self.parcel()
        key = uuid.uuid4()
        results = race(
            [
                lambda: change_parcel_status(
                    business=self.business,
                    actor=self.user,
                    parcel=parcel,
                    status="RECEIVED",
                    expected_status="REGISTERED",
                    idempotency_key=key,
                ).pk
            ]
            * 2
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(ParcelEvent.objects.filter(parcel=parcel).count(), 2)
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "RECEIVED")

    def test_competing_shipments_cannot_both_assign_the_same_parcel(self):
        parcel = self.parcel()
        shipments = [self.shipment(), self.shipment()]
        results = race(
            [
                lambda shipment=shipment: assign_parcel(
                    business=self.business, actor=self.user, shipment=shipment, parcel=parcel
                ).shipment_id
                for shipment in shipments
            ]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        parcel.refresh_from_db()
        self.assertEqual(
            parcel.shipment_id, next(value for status, value in results if status == "ok")
        )

    def test_competing_departures_append_only_one_transition_per_parcel(self):
        parcel, shipment = self.parcel(), self.shipment()
        change_parcel_status(
            business=self.business, actor=self.user, parcel=parcel, status="RECEIVED"
        )
        assign_parcel(business=self.business, actor=self.user, parcel=parcel, shipment=shipment)
        change_shipment_status(
            business=self.business, actor=self.user, shipment=shipment, status="READY"
        )
        results = race(
            [
                lambda: change_shipment_status(
                    business=self.business,
                    actor=self.user,
                    shipment=shipment,
                    status="IN_TRANSIT",
                    expected_status="READY",
                ).pk
            ]
            * 2
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        self.assertEqual(ParcelEvent.objects.filter(parcel=parcel, status="IN_TRANSIT").count(), 1)
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, "IN_TRANSIT")

    def test_assignment_vs_departure_preserves_consistent_membership_and_status(self):
        first, second, shipment = self.parcel(), self.parcel(), self.shipment()
        for parcel in (first, second):
            change_parcel_status(
                business=self.business, actor=self.user, parcel=parcel, status="RECEIVED"
            )
        assign_parcel(business=self.business, actor=self.user, parcel=first, shipment=shipment)
        change_shipment_status(
            business=self.business, actor=self.user, shipment=shipment, status="READY"
        )
        results = race(
            [
                lambda: assign_parcel(
                    business=self.business, actor=self.user, parcel=second, shipment=shipment
                ).pk,
                lambda: change_shipment_status(
                    business=self.business, actor=self.user, shipment=shipment, status="IN_TRANSIT"
                ).pk,
            ]
        )
        self.assertEqual(results[1][0], "ok")
        self.assertFalse(
            Parcel.objects.filter(shipment=shipment).exclude(current_status="IN_TRANSIT").exists()
        )
        second.refresh_from_db()
        self.assertEqual(second.current_status, "IN_TRANSIT" if second.shipment_id else "RECEIVED")

    def test_purge_business_lock_prevents_an_inflight_event_from_leaving_orphans(self):
        parcel = self.parcel()
        locked, contender = Event(), Event()

        def closer():
            close_old_connections()
            try:
                with transaction.atomic():
                    business = Business.objects.select_for_update().get(pk=self.business.pk)
                    business.is_active = False
                    business.save(update_fields=["is_active"])
                    locked.set()
                    self.assertTrue(contender.wait(timeout=10))
                    return purge_business(business_id=business.pk, reason_reference="PG-QA").purged
            finally:
                connections.close_all()

        def writer():
            close_old_connections()
            try:
                self.assertTrue(locked.wait(timeout=10))
                contender.set()
                try:
                    change_parcel_status(
                        business=self.business, actor=self.user, parcel=parcel, status="RECEIVED"
                    )
                    return "written"
                except PermissionDenied:
                    return "denied"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            close_future = pool.submit(closer)
            write_future = pool.submit(writer)
            self.assertTrue(close_future.result(timeout=30))
            self.assertEqual(write_future.result(timeout=30), "denied")
        self.assertFalse(Parcel.objects.exists())
        self.assertFalse(ParcelEvent.objects.exists())
        self.assertFalse(Shipment.objects.exists())
