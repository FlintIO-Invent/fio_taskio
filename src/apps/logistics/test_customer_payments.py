import uuid

from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from apps.billings.models import InvoicePayment
from apps.billings.payment_services import (
    adjust_invoice_payment,
    invoice_settlement,
    record_invoice_payment,
)
from apps.businesses.models import BusinessUser

from . import test_financial_access as fixtures
from .financial_coverage import clearance_for_parcel


class LogisticsCustomerPaymentTests(TestCase):
    setUp = fixtures.LogisticsFinancialAccessTests.setUp
    setUp_base = fixtures.LogisticsFinancialAccessTests.setUp_base
    switch = fixtures.LogisticsFinancialAccessTests.switch
    parcel = fixtures.LogisticsFinancialAccessTests.parcel
    shipment = fixtures.LogisticsFinancialAccessTests.shipment
    grant = fixtures.LogisticsFinancialAccessTests.grant
    login_worker = fixtures.LogisticsFinancialAccessTests.login_worker
    charge = fixtures.LogisticsFinancialAccessTests.charge
    bill = fixtures.LogisticsFinancialAccessTests.bill

    def receipt(self, invoice, actor=None, amount=10):
        return record_invoice_payment(
            business=self.business,
            actor=actor or self.staff,
            invoice=invoice,
            amount=amount,
            currency="USD",
            method="CASH",
            reference=f"CASH-{uuid.uuid4()}",
            idempotency_key=uuid.uuid4(),
        )

    def issue(self, invoice):
        from apps.billings.services import change_invoice_status

        change_invoice_status(
            business=self.business, actor=self.user, invoice=invoice, status="SENT"
        )

    def test_staff_receipt_requires_full_invoice_access_active_site_and_can_operate(self):
        self.issue(self.ia)
        self.issue(self.ic)
        self.issue(self.mixed)
        receipt = self.receipt(self.ia)
        self.assertEqual(receipt.recorded_by, self.staff)
        for invoice in (self.ic, self.mixed):
            with self.assertRaises(PermissionDenied):
                self.receipt(invoice)
        self.grant(self.a, operate=False)
        with self.assertRaises(PermissionDenied):
            self.receipt(self.ia, amount=1)
        self.assertEqual(
            invoice_settlement(business=self.business, actor=self.staff, invoice=self.ia).net_paid,
            10,
        )

    def test_unassigned_and_stale_staff_context_cannot_record_or_read(self):
        self.issue(self.ia)
        self.grant(self.a, operate=False)
        self.grant(self.b, operate=True)
        from .location_access_services import select_work_location

        select_work_location(business=self.business, actor=self.staff, location=self.b)
        with self.assertRaises(PermissionDenied):
            self.receipt(self.ia)
        self.member.logistics_location_assignments.all().delete()
        with self.assertRaises(PermissionDenied):
            self.receipt(self.ia)

    def test_staff_cannot_refund_and_accounting_can_without_work_site(self):
        self.issue(self.ia)
        receipt = self.receipt(self.ia)
        fields = dict(
            business=self.business,
            invoice=self.ia,
            payment=receipt,
            kind="REFUND",
            amount=5,
            reference="REFUND-1",
            reason_reference="CASE-1",
            idempotency_key=uuid.uuid4(),
        )
        with self.assertRaises(PermissionDenied):
            adjust_invoice_payment(actor=self.staff, **fields)
        adjust_invoice_payment(actor=self.user, **fields)
        self.assertEqual(
            invoice_settlement(
                business=self.business, actor=self.staff, invoice=self.ia
            ).outstanding,
            20,
        )

    def test_admin_and_accountant_can_record_invoices_without_operational_assignments(self):
        self.issue(self.ic)
        membership = BusinessUser.objects.get(business=self.business, user=self.user)
        for role in ("admin", "accountant"):
            membership.role = role
            membership.save()
            self.receipt(self.ic, actor=self.user, amount=1)
        self.assertEqual(
            invoice_settlement(business=self.business, actor=self.user, invoice=self.ic).net_paid, 2
        )

    def test_owner_receipts_clear_shared_invoice_without_granting_staff_invoice_access(self):
        self.issue(self.mixed)
        self.issue(self.ia)
        self.ia.refresh_from_db()
        self.receipt(self.ia, actor=self.user, amount=self.ia.total)
        self.mixed.refresh_from_db()
        self.receipt(self.mixed, actor=self.user, amount=self.mixed.total)
        self.assertTrue(
            clearance_for_parcel(business=self.business, actor=self.staff, parcel=self.pa).cleared
        )
        self.assertEqual(
            self.client.get(reverse("invoice_detail", args=[self.mixed.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.post(
                reverse("invoice_payment_record", args=[self.mixed.pk]), {}
            ).status_code,
            404,
        )
        self.assertEqual(InvoicePayment.objects.count(), 2)
