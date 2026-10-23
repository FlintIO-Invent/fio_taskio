"""Financial identity, frozen membership, reissue and correction on real row locks."""

import uuid
from unittest import skipUnless

from django.db import connection
from django.test import TransactionTestCase

from apps.billings.models import Invoice
from apps.billings.services import change_invoice_status

from . import test_billing_concurrency, test_concurrency
from .billing_services import add_charge, correct_charge, invoice_charges
from .models import LogisticsCharge
from .shipment_services import assign_parcel, remove_parcel


@skipUnless(connection.vendor == "postgresql", "Financial coverage races require PostgreSQL")
class FinancialCoverageConcurrencyTests(TransactionTestCase):
    setUp = test_billing_concurrency.LogisticsBillingConcurrencyTests.setUp
    parcel = test_billing_concurrency.LogisticsBillingConcurrencyTests.parcel
    shipment = test_billing_concurrency.LogisticsBillingConcurrencyTests.shipment

    def charge(self, parcel=None, shipment=None, **fields):
        return add_charge(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            shipment=shipment,
            description="Freight",
            unit_price=25,
            idempotency_key=uuid.uuid4(),
            **fields,
        )

    def bill(self, charge):
        return invoice_charges(business=self.business, actor=self.user, charge_ids=[charge.pk])

    def cancel(self, invoice):
        return change_invoice_status(
            business=self.business, actor=self.user, invoice=invoice, status="CANCELLED"
        )

    def test_fresh_token_race_creates_one_logical_charge(self):
        parcel = self.parcel()
        results = test_concurrency.race([lambda: self.charge(parcel=parcel).pk] * 2)
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        self.assertEqual(LogisticsCharge.objects.count(), 1)
        self.assertEqual(LogisticsCharge.objects.get().parcel_coverage.count(), 1)

    def test_parcel_and_shipment_freight_overlap_race_cannot_double_charge(self):
        shipment, parcel = self.shipment(), self.parcel()
        assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=parcel)
        results = test_concurrency.race(
            [lambda: self.charge(parcel=parcel).pk, lambda: self.charge(shipment=shipment).pk]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        self.assertEqual(LogisticsCharge.objects.count(), 1)

    def test_membership_change_racing_invoicing_preserves_saved_applicability(self):
        shipment, parcel = self.shipment(), self.parcel()
        assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=parcel)
        charge = self.charge(shipment=shipment)
        results = test_concurrency.race(
            [
                lambda: self.bill(charge).pk,
                lambda: remove_parcel(
                    business=self.business, actor=self.user, shipment=shipment, parcel=parcel
                ).pk,
            ]
        )
        self.assertEqual([status for status, _ in results], ["ok", "ok"])
        self.assertEqual(
            set(charge.parcel_coverage.values_list("parcel_id", flat=True)), {parcel.pk}
        )
        self.assertEqual(charge.invoice_lines.count(), 1)

    def test_membership_change_racing_charge_creation_records_one_exact_membership(self):
        shipment, a, b = self.shipment(), self.parcel(), self.parcel()
        assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=a)
        results = test_concurrency.race(
            [
                lambda: self.charge(shipment=shipment).pk,
                lambda: assign_parcel(
                    business=self.business, actor=self.user, shipment=shipment, parcel=b
                ).pk,
            ]
        )
        self.assertEqual([status for status, _ in results], ["ok", "ok"])
        ids = set(LogisticsCharge.objects.get().parcel_coverage.values_list("parcel_id", flat=True))
        self.assertIn(ids, ({a.pk}, {a.pk, b.pk}))

    def test_cancelled_invoice_reissue_race_creates_one_replacement_invoice(self):
        charge = self.charge(parcel=self.parcel())
        invoice = self.bill(charge)
        self.cancel(invoice)
        results = test_concurrency.race([lambda: self.bill(charge).pk] * 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(Invoice.objects.count(), 2)
        self.assertEqual(charge.invoice_lines.count(), 2)
        self.assertEqual(charge.invoice_lines.exclude(invoice__status="CANCELLED").count(), 1)

    def test_competing_corrections_create_one_successor_and_retain_original(self):
        charge = self.charge(parcel=self.parcel())
        original = self.bill(charge)
        self.cancel(original)
        results = test_concurrency.race(
            [
                lambda: correct_charge(
                    business=self.business,
                    actor=self.user,
                    charge=charge,
                    reason_reference="CASE-1",
                    idempotency_key=uuid.uuid4(),
                    unit_price=30,
                ).pk,
                lambda: correct_charge(
                    business=self.business,
                    actor=self.user,
                    charge=charge,
                    reason_reference="CASE-1",
                    idempotency_key=uuid.uuid4(),
                    unit_price=40,
                ).pk,
            ]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        self.assertEqual(LogisticsCharge.objects.count(), 2)
        self.assertEqual(LogisticsCharge.objects.filter(supersedes=charge).count(), 1)
        self.assertTrue(Invoice.objects.filter(pk=original.pk).exists())
