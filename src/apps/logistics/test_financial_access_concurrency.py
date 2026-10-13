"""Real PostgreSQL serialization of finance against grants and draft changes."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless

from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice
from apps.billings.services import change_invoice_status
from apps.businesses.models import Business, BusinessUser

from . import test_billing_concurrency, test_concurrency
from .billing_services import add_charge, invoice_charges
from .location_access_services import review_location_access, set_location_assignment
from .models import LogisticsCharge, LogisticsLocation


@skipUnless(connection.vendor == "postgresql", "Financial serialization requires PostgreSQL")
class FinancialAccessConcurrencyTests(TransactionTestCase):
    parcel = test_billing_concurrency.LogisticsBillingConcurrencyTests.parcel

    def setUp(self):
        test_billing_concurrency.LogisticsBillingConcurrencyTests.setUp(self)
        self.site = LogisticsLocation.objects.create(
            business=self.business,
            name="Work site",
            code="WORK",
            location_type="HUB",
            country_code="US",
        )
        self.restricted = LogisticsLocation.objects.create(
            business=self.business,
            name="Restricted site",
            code="OTHER",
            location_type="HUB",
            country_code="US",
        )
        self.staff = TaskIOUser.objects.create_user(
            email="finance-worker@example.test", password="testpass123"
        )
        self.member = BusinessUser.objects.create(
            business=self.business, user=self.staff, role="staff"
        )
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=self.member,
            location=self.site,
            can_operate=True,
        )
        review_location_access(business=self.business, actor=self.user)
        self.item = self.parcel(origin_location=self.site)
        self.first = self.charge()
        self.invoice = self.bill(self.first)

    def charge(self, actor=None, parcel=None):
        return add_charge(
            business=self.business,
            actor=actor or self.user,
            parcel=parcel or self.item,
            description="Handling",
            unit_price=25,
            idempotency_key=uuid.uuid4(),
        )

    def bill(self, charge, actor=None, invoice=None):
        return invoice_charges(
            business=self.business,
            actor=actor or self.user,
            charge_ids=[charge.pk],
            invoice=invoice,
        )

    def queued_write(self, action, mutation):
        """Hold the serialization lock until the access/content change has committed."""
        entered = Event()

        def worker():
            close_old_connections()
            entered.set()
            try:
                action()
                return "written"
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
                mutation()
            return future.result(timeout=30)

    def revoke(self):
        set_location_assignment(
            business=self.business,
            actor=self.user,
            membership=self.member,
            location=self.site,
            revoke=True,
        )

    def test_charge_creation_waits_for_revocation_and_denies(self):
        self.assertEqual(
            self.queued_write(lambda: self.charge(actor=self.staff), self.revoke), "denied"
        )
        self.assertEqual(LogisticsCharge.objects.count(), 1)

    def test_invoice_generation_waits_for_revocation_and_denies(self):
        pending = self.charge()
        self.assertEqual(
            self.queued_write(lambda: self.bill(pending, actor=self.staff), self.revoke), "denied"
        )
        self.assertEqual(Invoice.objects.count(), 1)
        pending.refresh_from_db()
        self.assertIsNone(pending.invoice_line_id)

    def test_issuance_waits_for_revocation_and_denies(self):
        self.assertEqual(
            self.queued_write(
                lambda: change_invoice_status(
                    business=self.business, actor=self.staff, invoice=self.invoice, status="SENT"
                ),
                self.revoke,
            ),
            "denied",
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "DRAFT")

    def test_append_rechecks_whole_draft_after_owner_adds_restricted_parcel(self):
        pending = self.charge()
        restricted = self.charge(parcel=self.parcel(origin_location=self.restricted))
        self.assertEqual(
            self.queued_write(
                lambda: self.bill(pending, actor=self.staff, invoice=self.invoice),
                lambda: self.bill(restricted, invoice=self.invoice),
            ),
            "denied",
        )
        self.assertEqual(self.invoice.lines.count(), 2)
        pending.refresh_from_db()
        self.assertIsNone(pending.invoice_line_id)

    def test_membership_deactivation_is_rechecked_after_waiting(self):
        def deactivate():
            BusinessUser.objects.filter(pk=self.member.pk).update(is_active=False)

        self.assertEqual(
            self.queued_write(lambda: self.charge(actor=self.staff), deactivate), "denied"
        )
        self.assertEqual(LogisticsCharge.objects.count(), 1)

    def test_draft_append_racing_issuance_never_changes_a_sent_invoice(self):
        pending = self.charge()
        results = test_concurrency.race(
            [
                lambda: self.bill(pending, actor=self.staff, invoice=self.invoice).pk,
                lambda: change_invoice_status(
                    business=self.business, actor=self.staff, invoice=self.invoice, status="SENT"
                ).pk,
            ]
        )
        self.assertEqual(results[1][0], "ok")
        self.invoice.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(self.invoice.status, "SENT")
        appended = results[0][0] == "ok"
        self.assertEqual(bool(pending.invoice_line_id), appended)
        self.assertEqual(self.invoice.lines.count(), 1 + appended)
        self.assertEqual(self.invoice.subtotal, 25 * (1 + appended))
