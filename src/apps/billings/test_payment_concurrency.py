"""Receipt and adjustment accounting on actual PostgreSQL row locks."""

import uuid
from unittest import skipUnless

from django.db import connection, transaction
from django.test import TransactionTestCase

from apps.businesses.models import Business, BusinessUser
from apps.logistics.test_concurrency import race

from . import test_payments as fixtures
from .models import InvoicePayment
from .payment_services import correct_invoice_payment


@skipUnless(connection.vendor == "postgresql", "Customer receipt races require PostgreSQL")
class CustomerPaymentConcurrencyTests(TransactionTestCase):
    setUp = fixtures.CustomerPaymentTests.setUp
    make_invoice = fixtures.CustomerPaymentTests.make_invoice
    receipt = fixtures.CustomerPaymentTests.receipt
    balance = fixtures.CustomerPaymentTests.balance
    adjustment = fixtures.CustomerPaymentTests.adjustment

    def test_competing_partial_receipts_cannot_overpay(self):
        result = race([lambda: self.receipt(60).pk] * 2)
        self.assertCountEqual([status for status, _ in result], ["ok", "rejected"])
        self.assertEqual(self.invoice.payments.count(), 1)
        self.assertEqual(self.balance().outstanding, 40)

    def test_exact_token_retry_race_returns_one_receipt(self):
        key = uuid.uuid4()
        result = race(
            [lambda: self.receipt(100, reference="CASH-RACE", idempotency_key=key).pk] * 2
        )
        self.assertEqual(result[0], result[1])
        self.assertEqual(self.invoice.payments.count(), 1)
        self.assertTrue(self.balance().settled)

    def test_fresh_token_same_reference_race_rejects_duplicate(self):
        result = race(
            [lambda: self.receipt(40, reference="BANK-RACE", method="BANK_TRANSFER").pk] * 2
        )
        self.assertCountEqual([status for status, _ in result], ["ok", "rejected"])
        self.assertEqual(self.invoice.payments.count(), 1)

    def test_two_legitimate_partial_receipts_sum_to_full_settlement(self):
        result = race([lambda: self.receipt(40).pk, lambda: self.receipt(60).pk])
        self.assertEqual([status for status, _ in result], ["ok", "ok"])
        self.assertTrue(self.balance().settled)

    def test_refunds_cannot_reduce_the_same_receipt_twice(self):
        receipt = self.receipt(100)
        result = race([lambda: self.adjustment(receipt, 60).pk] * 2)
        self.assertCountEqual([status for status, _ in result], ["ok", "rejected"])
        self.assertEqual(self.balance().net_paid, 40)

    def test_competing_corrections_create_one_successor(self):
        receipt = self.receipt()

        def correct(amount):
            return correct_invoice_payment(
                business=self.business,
                actor=self.user,
                invoice=self.invoice,
                payment=receipt,
                amount=amount,
                method="CASH",
                reference="CORRECT-RACE",
                reason_reference="CASE-RACE",
                idempotency_key=uuid.uuid4(),
            ).pk

        result = race([lambda: correct(70), lambda: correct(80)])
        self.assertCountEqual([status for status, _ in result], ["ok", "rejected"])
        self.assertEqual(InvoicePayment.objects.count(), 3)
        self.assertEqual(receipt.adjustments.filter(kind="RECEIPT").count(), 1)

    def test_membership_deactivation_is_rechecked_after_business_lock_wait(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        from django.core.exceptions import PermissionDenied
        from django.db import close_old_connections, connections

        entered = Event()

        def payment():
            close_old_connections()
            try:
                entered.set()
                try:
                    return self.receipt(40).pk
                except PermissionDenied:
                    return "denied"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Business.objects.select_for_update().get(pk=self.business.pk)
                future = pool.submit(payment)
                self.assertTrue(entered.wait(timeout=5))
                BusinessUser.objects.filter(pk=self.membership.pk).update(is_active=False)
            self.assertEqual(future.result(timeout=20), "denied")
        self.assertFalse(self.invoice.payments.exists())
