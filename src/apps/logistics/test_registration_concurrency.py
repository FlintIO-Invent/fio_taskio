"""Exercise guided HTTP submissions against real PostgreSQL row locks."""

import uuid
from unittest import skipUnless

from django.db import connection
from django.test import Client, TransactionTestCase
from django.urls import reverse

from apps.billings.models import Invoice, InvoiceLine, InvoicePayment
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from . import test_billing_concurrency as fixtures
from .models import LogisticsCharge, Parcel
from .test_concurrency import race


@skipUnless(connection.vendor == "postgresql", "Guided retries require PostgreSQL row locks")
class ParcelRegistrationConcurrencyTests(TransactionTestCase):
    setUp = fixtures.LogisticsBillingConcurrencyTests.setUp
    parcel = fixtures.LogisticsBillingConcurrencyTests.parcel
    shipment = fixtures.LogisticsBillingConcurrencyTests.shipment
    charge = fixtures.LogisticsBillingConcurrencyTests.charge

    def clients(self):
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(self.user)
            session = client.session
            session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
            session.save()
        return clients

    def submit(self, url, payloads):
        clients = self.clients()
        return race(
            [
                lambda c=c, data=data: c.post(url, data).status_code
                for c, data in zip(clients, payloads, strict=True)
            ]
        )

    def test_concurrent_registration_and_fresh_charge_tokens(self):
        url = reverse("logistics_parcel_register")
        data = {
            "client": self.customer.pk,
            "origin": "A",
            "destination": "B",
            "package_description": "Books",
            "quantity": 1,
            "continue_registration": "1",
            "idempotency_key": uuid.uuid4(),
        }
        self.assertEqual(self.submit(url, [data, data]), [("ok", 302)] * 2)
        parcel = Parcel.objects.get()
        url = reverse("logistics_parcel_charge", args=[parcel.pk]) + "?registration=1"
        data = {"charge_type": "custom", "description": "Handling", "quantity": 1, "unit_price": 25}
        self.assertCountEqual(
            self.submit(url, [{**data, "idempotency_key": uuid.uuid4()} for _ in range(2)]),
            [("ok", 302), ("ok", 200)],
        )
        self.assertEqual(LogisticsCharge.objects.count(), 1)

    def test_concurrent_invoice_issue_and_identical_payment_receipt(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        url = reverse("logistics_parcel_invoice", args=[parcel.pk]) + "?registration=1"
        data = {"charges": [charge.pk], "invoice": ""}
        self.assertEqual(self.submit(url, [data, data]), [("ok", 302)] * 2)
        invoice = Invoice.objects.get()
        self.assertEqual(InvoiceLine.objects.count(), 1)
        url = reverse("logistics_parcel_registration", args=[parcel.pk])
        data = {"action": "issue", "invoice": invoice.pk}
        self.assertEqual(self.submit(url, [data, data]), [("ok", 302)] * 2)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "SENT")
        data = {
            "action": "payment",
            "invoice": invoice.pk,
            "amount": 25,
            "method": "CASH",
            "reference": "CONCURRENT-RECEIPT",
            "idempotency_key": uuid.uuid4(),
        }
        self.assertEqual(self.submit(url, [data, data]), [("ok", 302)] * 2)
        self.assertEqual(InvoicePayment.objects.count(), 1)

    def test_competing_full_payments_and_shipment_assignments(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.client.post(
            reverse("logistics_parcel_invoice", args=[parcel.pk]) + "?registration=1",
            {"charges": charge.pk},
        )
        invoice = Invoice.objects.get()
        url = reverse("logistics_parcel_registration", args=[parcel.pk])
        self.client.post(url, {"action": "issue", "invoice": invoice.pk})
        data = {"action": "payment", "invoice": invoice.pk, "amount": 25, "method": "BANK_TRANSFER"}
        result = self.submit(
            url,
            [
                {**data, "reference": f"BANK-{index}", "idempotency_key": uuid.uuid4()}
                for index in range(2)
            ],
        )
        self.assertCountEqual(result, [("ok", 302), ("ok", 200)])
        self.assertEqual(InvoicePayment.objects.count(), 1)
        ships = [self.shipment(), self.shipment()]
        result = self.submit(
            url,
            [
                {
                    "action": "assign",
                    "shipment": ship.pk,
                    "expected_revision": ship.revision,
                    "idempotency_key": uuid.uuid4(),
                }
                for ship in ships
            ],
        )
        self.assertCountEqual(result, [("ok", 302), ("ok", 200)])
        parcel.refresh_from_db()
        self.assertIn(parcel.shipment_id, [ship.pk for ship in ships])
