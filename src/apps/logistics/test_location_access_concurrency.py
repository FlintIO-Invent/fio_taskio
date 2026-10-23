from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless

from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessUser

from . import test_concurrency
from .location_access_services import (
    review_location_access,
    select_work_location,
    set_location_assignment,
)
from .models import LogisticsLocation, LogisticsLocationAssignment, Parcel, ParcelEvent
from .parcel_services import change_parcel_status


@skipUnless(connection.vendor == "postgresql", "Location serialization requires PostgreSQL")
class LocationAccessConcurrencyTests(TransactionTestCase):
    setUp_base = test_concurrency.LogisticsOperationConcurrencyTests.setUp
    parcel = test_concurrency.LogisticsOperationConcurrencyTests.parcel

    def setUp(self):
        self.setUp_base()
        self.site = LogisticsLocation.objects.create(
            business=self.business,
            name="Work site",
            code="WORK",
            location_type="HUB",
            country_code="US",
        )
        self.other_site = LogisticsLocation.objects.create(
            business=self.business,
            name="Second site",
            code="SECOND",
            location_type="HUB",
            country_code="US",
        )
        self.staff = TaskIOUser.objects.create_user(
            email="concurrent-worker@example.test", password="testpass123"
        )
        self.member = BusinessUser.objects.create(
            business=self.business, user=self.staff, role="staff"
        )
        for location in (self.site, self.other_site):
            set_location_assignment(
                business=self.business,
                actor=self.user,
                membership=self.member,
                location=location,
                can_operate=True,
            )
        review_location_access(business=self.business, actor=self.user)
        self.item = self.parcel(origin_location=self.site)

    def test_revocation_serializes_with_inflight_status_update(self):
        entered = Event()

        def worker():
            close_old_connections()
            entered.set()
            try:
                change_parcel_status(
                    business=self.business, actor=self.staff, parcel=self.item, status="RECEIVED"
                )
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
                    location=self.site,
                    revoke=True,
                )
            self.assertEqual(future.result(timeout=30), "denied")
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_status, Parcel.Status.REGISTERED)
        self.assertEqual(ParcelEvent.objects.filter(parcel=self.item).count(), 1)

    def test_competing_work_site_selections_keep_one_current_assignment(self):
        results = test_concurrency.race(
            [
                lambda: select_work_location(
                    business=self.business, actor=self.staff, location=self.site
                ).pk,
                lambda: select_work_location(
                    business=self.business, actor=self.staff, location=self.other_site
                ).pk,
            ]
        )
        self.assertTrue(all(result[0] == "ok" for result in results))
        self.assertEqual(
            LogisticsLocationAssignment.objects.filter(
                membership=self.member, is_current=True
            ).count(),
            1,
        )
