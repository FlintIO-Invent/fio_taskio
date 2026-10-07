import uuid
from unittest import skipUnless

from django.db import connection
from django.test import TransactionTestCase

from apps.billings.models import Invoice, InvoiceLine
from apps.billings.services import create_invoice_for_client
from apps.crm.models import Client

from . import test_concurrency as fixtures
from .billing_services import add_charge, invoice_charges
from .models import LogisticsCharge
from .parcel_services import register_parcel
from .shipment_services import assign_parcel
from .test_concurrency import race


@skipUnless(connection.vendor == "postgresql", "Row-lock concurrency requires PostgreSQL")
class LogisticsBillingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        fixtures.LogisticsOperationConcurrencyTests.setUp(self)
        plan = self.business.subscription.plan
        plan.allow_invoicing = True
        plan.save(update_fields=["allow_invoicing"])

    parcel = fixtures.LogisticsOperationConcurrencyTests.parcel
    shipment = fixtures.LogisticsOperationConcurrencyTests.shipment

    def charge(self, parcel=None, **fields):
        return add_charge(
            business=self.business,
            actor=self.user,
            parcel=parcel or self.parcel(),
            description="Handling",
            unit_price=25,
            idempotency_key=uuid.uuid4(),
            **fields,
        )

    def bill(self, charge, **fields):
        return invoice_charges(
            business=self.business, actor=self.user, charge_ids=[charge.pk], **fields
        ).pk

    def test_same_charge_invoice_race_creates_one_line_and_invoice(self):
        charge = self.charge()
        results = race([lambda: self.bill(charge)] * 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(InvoiceLine.objects.count(), 1)

    def test_retry_charge_race_creates_one_charge(self):
        parcel, key = self.parcel(), uuid.uuid4()
        results = race(
            [
                lambda: add_charge(
                    business=self.business,
                    actor=self.user,
                    parcel=parcel,
                    description="Handling",
                    unit_price=25,
                    idempotency_key=key,
                ).pk
            ]
            * 2
        )
        self.assertEqual(results[0], results[1])
        self.assertEqual(LogisticsCharge.objects.count(), 1)

    def test_distinct_charges_added_to_one_draft_preserve_both_and_totals(self):
        charges = [self.charge(), self.charge()]
        invoice = create_invoice_for_client(actor=self.user, client=self.customer)
        results = race(
            [lambda charge=charge: self.bill(charge, invoice=invoice) for charge in charges]
        )
        self.assertEqual([status for status, _ in results], ["ok", "ok"])
        invoice.refresh_from_db()
        self.assertEqual(invoice.lines.count(), 2)
        self.assertEqual(invoice.subtotal, 50)

    def test_concurrent_invoice_creation_preserves_number_uniqueness(self):
        charge = self.charge()
        results = race(
            [
                lambda: self.bill(charge),
                lambda: create_invoice_for_client(actor=self.user, client=self.customer).pk,
            ]
        )
        self.assertEqual([status for status, _ in results], ["ok", "ok"])
        self.assertEqual(len(set(Invoice.objects.values_list("invoice_number", flat=True))), 2)

    def test_shipment_charge_racing_other_client_assignment_never_mixes_billing(self):
        shipment = self.shipment()
        first = self.parcel()
        assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=first)
        customer = Client.objects.create(
            business=self.business, first_name="Other", last_name="Client"
        )
        other = register_parcel(
            business=self.business,
            actor=self.user,
            client=customer,
            origin="A",
            destination="B",
            package_description="Box",
        )
        results = race(
            [
                lambda: add_charge(
                    business=self.business,
                    actor=self.user,
                    shipment=shipment,
                    description="Freight",
                    unit_price=150,
                    idempotency_key=uuid.uuid4(),
                ).pk,
                lambda: assign_parcel(
                    business=self.business, actor=self.user, shipment=shipment, parcel=other
                ).pk,
            ]
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
