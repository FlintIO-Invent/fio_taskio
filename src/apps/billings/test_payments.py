"""Shared customer receipt accounting; SaaS subscriptions are untouched."""

import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.business_data_inventory import build_business_data_inventory
from apps.businesses.business_data_purge import plan_business_purge
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.models import ActivityLog, Client

from .models import Invoice, InvoiceLine, InvoicePayment
from .payment_services import (
    adjust_invoice_payment,
    correct_invoice_payment,
    invoice_settlement,
    record_invoice_payment,
)
from .services import change_invoice_status, recalculate_invoice_totals


class CustomerPaymentTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Service", slug="receipt-service")
        self.other = Business.objects.create(name="Other", slug="receipt-other")
        self.plan = ClarivoPlan.objects.create(
            name="Receipts", slug="receipt-plan", allow_invoicing=True
        )
        for business in (self.business, self.other):
            BusinessSubscription.objects.create(business=business, plan=self.plan, status="active")
        self.user = TaskIOUser.objects.create_user(
            email="receipts@example.com", password="testpass123"
        )
        self.other_user = TaskIOUser.objects.create_user(
            email="other-receipts@example.com", password="testpass123"
        )
        self.membership = BusinessUser.objects.create(
            business=self.business, user=self.user, role="owner"
        )
        BusinessUser.objects.create(business=self.other, user=self.other_user, role="owner")
        self.customer = Client.objects.create(
            business=self.business, first_name="Receipt", last_name="Client"
        )
        self.other_customer = Client.objects.create(
            business=self.other, first_name="Other", last_name="Client"
        )
        self.invoice = self.make_invoice()
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    def make_invoice(self, business=None, client=None, total=100, status="SENT"):
        invoice = Invoice.objects.create(
            business=business or self.business,
            client=client or self.customer,
            invoice_number=f"R-{uuid.uuid4()}",
            status=status,
            subtotal=Decimal(total),
            total=Decimal(total),
        )
        InvoiceLine.objects.create(
            invoice=invoice, description="Service", unit_price=Decimal(total)
        )
        return invoice

    def receipt(self, amount=100, **fields):
        return record_invoice_payment(
            **{
                "business": self.business,
                "actor": self.user,
                "invoice": self.invoice,
                "amount": amount,
                "currency": "USD",
                "method": "CASH",
                "reference": f"CASH-{uuid.uuid4()}",
                "idempotency_key": uuid.uuid4(),
                **fields,
            }
        )

    def balance(self, invoice=None):
        return invoice_settlement(
            business=self.business, actor=self.user, invoice=invoice or self.invoice
        )

    def adjustment(self, payment, amount, **fields):
        return adjust_invoice_payment(
            **{
                "business": self.business,
                "actor": self.user,
                "invoice": self.invoice,
                "payment": payment,
                "kind": "REFUND",
                "amount": Decimal(str(amount)),
                "reference": f"REFUND-{uuid.uuid4()}",
                "reason_reference": "CASE-1",
                "idempotency_key": uuid.uuid4(),
                **fields,
            }
        )

    def test_cash_bank_partial_and_full_settlement_do_not_change_service_status(self):
        cash = self.receipt(35)
        partial = self.balance()
        self.assertEqual(
            (partial.net_paid, partial.outstanding, partial.state),
            (Decimal("35"), Decimal("65"), "PARTIAL"),
        )
        self.assertFalse(partial.settled)
        bank = self.receipt(65, method="BANK_TRANSFER", reference="bank-100")
        full = self.balance()
        self.assertTrue(full.settled)
        self.assertEqual((full.outstanding, full.state), (Decimal("0"), "SETTLED"))
        self.assertEqual((cash.recorded_by, bank.currency), (self.user, "USD"))
        self.assertIsNotNone(cash.recorded_at)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "SENT")
        self.assertEqual(
            ActivityLog.objects.filter(summary__contains="Customer payment").count(), 2
        )

    def test_decimal_rounding_nonfinite_float_and_unsupported_currency(self):
        first = self.receipt(amount=Decimal("0.005"))
        self.assertEqual(first.amount, Decimal("0.01"))
        for amount in (
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("-1"),
            Decimal("0.004"),
            0.1,
            True,
        ):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.receipt(amount=amount)
        with self.assertRaises(ValidationError):
            self.receipt(1, currency="JPY")
        for code in Business.Currency.values:
            self.business.currency = code
            self.business.save()
            invoice = self.make_invoice(total=1)
            receipt = self.receipt(Decimal("0.015"), invoice=invoice, currency=code)
            self.assertEqual(receipt.amount, Decimal("0.02"))

    def test_overpayment_wrong_currency_draft_and_cancelled_invoice_rejected(self):
        self.receipt(60)
        for amount, fields in ((41, {}), (10, {"currency": "EUR"})):
            with self.assertRaises(ValidationError):
                self.receipt(amount, **fields)
        for status in ("DRAFT", "CANCELLED"):
            with self.assertRaises(ValidationError):
                self.receipt(1, invoice=self.make_invoice(status=status))
        self.assertEqual(self.invoice.payments.count(), 1)

    def test_idempotency_and_fresh_token_reference_duplicates_across_invoices(self):
        key = uuid.uuid4()
        receipt = self.receipt(40, reference="cash  1", idempotency_key=key)
        self.assertEqual(self.receipt(40, reference=" CASH 1 ", idempotency_key=key).pk, receipt.pk)
        with self.assertRaises(ValidationError):
            self.receipt(41, reference="CASH 1", idempotency_key=key)
        with self.assertRaises(ValidationError):
            self.receipt(40, reference="cash 1")
        with self.assertRaises(ValidationError):
            self.receipt(40, reference="cash 1", method="BANK_TRANSFER")
        with self.assertRaises(ValidationError):
            self.receipt(40, invoice=self.make_invoice(), reference="cash 1")
        self.adjustment(receipt, 40)
        with self.assertRaises(ValidationError):
            self.receipt(40, reference="CASH 1")
        self.assertEqual(self.invoice.payments.count(), 2)

    def test_partial_refund_full_reversal_and_adjustment_retry_recalculate_balances(self):
        receipt = self.receipt()
        key = uuid.uuid4()
        adjustment = self.adjustment(receipt, 25, reference="REF-1", idempotency_key=key)
        self.assertEqual(
            self.adjustment(receipt, 25, reference="REF-1", idempotency_key=key).pk, adjustment.pk
        )
        self.assertEqual(
            (self.balance().net_paid, self.balance().outstanding), (Decimal("75"), Decimal("25"))
        )
        with self.assertRaises(ValidationError):
            self.adjustment(receipt, 76)
        with self.assertRaises(ValidationError):
            self.adjustment(receipt, 25, reference="REF-1")
        self.adjustment(receipt, 75, kind="REVERSAL")
        self.assertEqual(
            (self.balance().net_paid, self.balance().outstanding), (Decimal("0"), Decimal("100"))
        )
        self.assertFalse(self.balance().settled)
        self.assertEqual(self.invoice.payments.count(), 3)

    def test_atomic_correction_preserves_original_and_one_successor(self):
        receipt = self.receipt()

        def correct(amount, key, payment=receipt, **fields):
            return correct_invoice_payment(
                business=self.business,
                actor=self.user,
                invoice=self.invoice,
                payment=payment,
                amount=Decimal(str(amount)),
                method="BANK_TRANSFER",
                reference="BANK-CORRECTED",
                reason_reference="CASE-2",
                idempotency_key=key,
                **fields,
            )

        with self.assertRaises(ValidationError):
            correct(101, uuid.uuid4())
        self.assertEqual(self.invoice.payments.count(), 1)
        self.assertTrue(self.balance().settled)
        key = uuid.uuid4()
        replacement = correct(70, key)
        self.assertEqual(replacement.original_id, receipt.pk)
        self.assertEqual(correct(70, key).pk, replacement.pk)
        self.assertEqual(self.invoice.payments.count(), 3)
        self.assertEqual(self.balance().outstanding, Decimal("30"))
        with self.assertRaises(ValidationError):
            correct(71, uuid.uuid4())
        corrected_again = correct(80, uuid.uuid4(), payment=replacement)
        self.assertEqual(corrected_again.original_id, replacement.pk)
        self.assertEqual(self.balance().net_paid, Decimal("80"))

    def test_online_receipt_requires_accounting_role_and_external_evidence(self):
        with self.assertRaises(ValidationError):
            self.receipt(method="VERIFIED_ONLINE", reference="EXT-1")
        self.membership.role = "staff"
        self.membership.save()
        with self.assertRaises(PermissionDenied):
            self.receipt(
                method="VERIFIED_ONLINE", reference="EXT-1", verification_reference="BANK-PORTAL-1"
            )
        self.membership.role = "accountant"
        self.membership.save()
        receipt = self.receipt(
            method="VERIFIED_ONLINE", reference="EXT-1", verification_reference="BANK-PORTAL-1"
        )
        self.assertEqual(receipt.verification_reference, "BANK-PORTAL-1")
        self.assertTrue(self.balance().settled)

    def test_correction_of_partially_refunded_receipt_requires_reconciliation(self):
        receipt = self.receipt(100)
        self.adjustment(receipt, 25)
        with self.assertRaises(ValidationError):
            correct_invoice_payment(
                business=self.business,
                actor=self.user,
                invoice=self.invoice,
                payment=receipt,
                amount=80,
                method="CASH",
                reference="CORRECT-PARTIAL",
                reason_reference="CASE-3",
                idempotency_key=uuid.uuid4(),
            )
        self.assertEqual((self.invoice.payments.count(), self.balance().net_paid), (2, 75))

    def test_legacy_manually_paid_status_never_fabricates_receipts(self):
        self.invoice.status = "PAID"
        self.invoice.save()
        balance = self.balance()
        self.assertTrue(balance.legacy_paid_unverified)
        self.assertFalse(balance.settled)
        self.assertEqual((balance.outstanding, balance.net_paid), (Decimal("100"), Decimal("0")))
        self.assertFalse(self.invoice.payments.exists())
        response = self.client.get(reverse("invoice_detail", args=[self.invoice.pk]))
        self.assertContains(response, "Legacy manually marked PAID")
        self.receipt(40)
        self.assertEqual(self.balance().state, "PARTIAL")
        self.assertFalse(self.balance().settled)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "PAID")

    def test_roles_and_persisted_membership_subscription_guards(self):
        for role in ("owner", "admin", "accountant", "staff"):
            self.membership.role = role
            self.membership.save()
            self.receipt(1)
        receipt = self.invoice.payments.first()
        with self.assertRaises(PermissionDenied):
            self.adjustment(receipt, 1)
        self.membership.role = "viewer"
        self.membership.save()
        self.assertEqual(self.balance().net_paid, Decimal("4"))
        with self.assertRaises(PermissionDenied):
            self.receipt(1)
        self.membership.role = "owner"
        self.membership.is_active = False
        self.membership.save()
        with self.assertRaises(PermissionDenied):
            self.receipt(1)
        self.membership.is_active = True
        self.membership.save()
        subscription = self.business.subscription
        subscription.status = "past_due"
        subscription.save()
        with self.assertRaises(PermissionDenied):
            self.receipt(1)

    def test_tenant_reads_writes_and_adjustment_targets_fail_closed(self):
        other = self.make_invoice(business=self.other, client=self.other_customer)
        with self.assertRaises(PermissionDenied):
            self.receipt(invoice=other)
        with self.assertRaises(PermissionDenied):
            invoice_settlement(business=self.other, actor=self.user, invoice=other)
        self.assertEqual(
            self.client.get(reverse("invoice_payment_record", args=[other.pk])).status_code, 404
        )
        original = self.receipt(40)
        with self.assertRaises(ValidationError):
            self.adjustment(original, 10, invoice=self.make_invoice())

    def test_append_only_history_and_invoice_basis_protection(self):
        receipt = self.receipt(40)
        receipt.amount = 41
        with self.assertRaises(ValidationError):
            receipt.save()
        with self.assertRaises(ValidationError):
            InvoicePayment.objects.filter(pk=receipt.pk).update(amount=41)
        with self.assertRaises(ProtectedError):
            receipt.delete()
        with self.assertRaises(ProtectedError):
            self.invoice.delete()
        with self.assertRaises(ProtectedError):
            Invoice.objects.filter(pk=self.invoice.pk).delete()
        self.invoice.total = 101
        with self.assertRaises(ValidationError):
            self.invoice.save()
        with self.assertRaises(ValidationError):
            recalculate_invoice_totals(self.invoice, actor=self.user)
        line = self.invoice.lines.get()
        with self.assertRaises(ProtectedError):
            line.delete()
        line.invoice = self.make_invoice()
        with self.assertRaises(ValidationError):
            line.save()

    def test_corrupt_foreign_receipt_is_not_exposed_or_used_as_an_invoice_basis(self):
        other = self.make_invoice(business=self.other, client=self.other_customer, total=500)
        foreign = self.receipt(
            500,
            business=self.other,
            actor=self.other_user,
            invoice=other,
            reference="FOREIGN-SECRET",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE billings_invoicepayment SET invoice_id = %s WHERE id = %s",
                [self.invoice.pk, foreign.pk],
            )
        balance = self.balance()
        self.assertEqual((balance.total, balance.outstanding), (100, 100))
        self.assertFalse(balance.settled)
        self.assertTrue(balance.issues)
        response = self.client.get(reverse("invoice_detail", args=[self.invoice.pk]))
        self.assertNotContains(response, "FOREIGN-SECRET")
        with self.assertRaises(ValidationError):
            self.receipt(1)

    def test_cancellation_requires_reduced_receipts_and_keeps_service_transition_graph(self):
        receipt = self.receipt(40)
        with self.assertRaises(ValidationError):
            change_invoice_status(
                business=self.business, actor=self.user, invoice=self.invoice, status="CANCELLED"
            )
        response = self.client.post(
            reverse("invoice_change_status", args=[self.invoice.pk]), {"status": "CANCELLED"}
        )
        self.assertEqual(response.status_code, 302)
        self.adjustment(receipt, 40)
        change_invoice_status(
            business=self.business, actor=self.user, invoice=self.invoice, status="CANCELLED"
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "CANCELLED")
        self.assertEqual((self.balance().outstanding, self.balance().state), (0, "CANCELLED"))
        self.assertFalse(self.balance().settled)
        self.assertEqual(self.invoice.payments.count(), 2)
        legacy = self.make_invoice(status="PAID")
        change_invoice_status(
            business=self.business, actor=self.user, invoice=legacy, status="CANCELLED"
        )
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, "PAID")

    def test_receipt_currency_basis_survives_service_workspace_default_change(self):
        self.receipt(40)
        self.business.currency = "EUR"
        self.business.save()
        self.receipt(60)
        self.assertEqual(
            (self.balance().currency, self.balance().outstanding), ("USD", Decimal("0"))
        )
        self.invoice.refresh_from_db()
        self.assertEqual(
            self.invoice.currency_code, "EUR"
        )  # Existing SERVICE presentation behavior.

    def test_normal_ui_receipt_retry_refund_and_viewer_balance(self):
        url = reverse("invoice_payment_record", args=[self.invoice.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        fields = {
            "amount": "40",
            "method": "CASH",
            "reference": "CASH-UI-1",
            "idempotency_key": str(uuid.uuid4()),
        }
        self.assertEqual(self.client.post(url, fields).status_code, 302)
        self.assertEqual(self.client.post(url, fields).status_code, 302)
        receipt = self.invoice.payments.get()
        response = self.client.post(
            url,
            {
                **fields,
                "amount": "70",
                "reference": "OVER-UI",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        self.assertContains(response, "exceed")
        response = self.client.post(
            reverse("invoice_payment_adjust", args=[self.invoice.pk, receipt.pk]),
            {
                "action": "REFUND",
                "amount": "10",
                "method": "CASH",
                "reference": "REF-UI-1",
                "reason_reference": "CASE-UI-1",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.membership.role = "viewer"
        self.membership.save()
        response = self.client.get(reverse("invoice_detail", args=[self.invoice.pk]))
        self.assertContains(response, "USD 70.00")
        self.assertNotContains(response, "Record customer payment")
        self.assertNotContains(response, "Adjust receipt")

    def test_real_payment_history_blocks_inventory_purge_even_after_refund(self):
        receipt = self.receipt()
        self.adjustment(receipt, 100)
        self.business.is_active = False
        self.business.save()
        inventory = build_business_data_inventory(self.business)
        self.assertEqual(
            next(row.total_count for row in inventory.records if row.key == "customer_payments"), 2
        )
        plan = plan_business_purge(business_id=self.business.pk, confirm_test_financial_data=True)
        self.assertIn("customer_payment_history_protected", plan.blocking_error_codes)
