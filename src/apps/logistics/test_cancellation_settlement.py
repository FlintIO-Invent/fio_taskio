"""Cancellation credits, explicit allocations and completed manual refunds."""

import uuid
from unittest import skipUnless

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.billings.cancellation_services import confirm_cancellation, review_cancellation
from apps.billings.models import (
    InvoiceCancellationCredit,
    InvoiceObligationShare,
    InvoicePayment,
    ParcelCancellationSettlement,
)
from apps.billings.payment_services import (
    adjust_invoice_payment,
    invoice_settlement,
    record_invoice_payment,
)
from apps.billings.services import change_invoice_status

from . import test_workflow_summary as fixtures
from .billing_services import add_charge, invoice_charges
from .parcel_services import change_parcel_status
from .shipment_services import assign_parcel, change_shipment_status
from .workflow_summary import resolve_parcel_workflow


class CancellationSettlementTests(TestCase):
    setUp = fixtures.ParcelWorkflowSummaryTests.setUp
    parcel = fixtures.ParcelWorkflowSummaryTests.parcel
    shipment = fixtures.ParcelWorkflowSummaryTests.shipment
    charge = fixtures.ParcelWorkflowSummaryTests.charge
    bill = fixtures.ParcelWorkflowSummaryTests.bill
    issue = fixtures.ParcelWorkflowSummaryTests.issue
    receipt = fixtures.ParcelWorkflowSummaryTests.receipt
    cargo = fixtures.ParcelWorkflowSummaryTests.cargo

    def prepare(self, collected=100, paid=False):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel, unit_price=100)
        invoice = self.bill(charge)
        self.issue(invoice)
        receipt = self.receipt(invoice, collected) if collected else None
        if paid:
            change_invoice_status(
                business=self.business, actor=self.user, invoice=invoice, status="PAID"
            )
        change_parcel_status(
            business=self.business, actor=self.user, parcel=parcel, status="CANCELLED"
        )
        parcel.refresh_from_db()
        return parcel, charge, invoice, receipt

    def settle(self, parcel, choices=None, key=None):
        plan = review_cancellation(
            business=self.business, actor=self.user, parcel=parcel, choices=choices
        )
        return confirm_cancellation(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            choices=choices or {},
            fingerprint=plan["fingerprint"],
            idempotency_key=key or uuid.uuid4(),
            reason_reference="CANCEL-1",
        )

    def balance(self, invoice):
        return invoice_settlement(business=self.business, actor=self.user, invoice=invoice)

    def refund(self, invoice, receipt, credit, amount, key=None, reference="RETURN-1"):
        return adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            payment=receipt,
            kind="REFUND",
            amount=amount,
            reference=reference,
            reason_reference="CANCEL-1",
            idempotency_key=key or uuid.uuid4(),
            cancellation_credit=credit,
        )

    def test_example_retained_fee_paid_lifecycle_and_completed_refund(self):
        parcel, charge, invoice, receipt = self.prepare(paid=True)
        original_lines = list(invoice.lines.values())
        case = self.settle(parcel, {"retained": {str(charge.pk): "20"}})
        credit = case.credits.get()
        balance = self.balance(invoice)
        self.assertEqual((balance.total, balance.credits, balance.adjusted_total), (100, 80, 20))
        self.assertEqual((balance.net_paid, balance.outstanding, balance.refund_due), (100, 0, 80))
        self.assertFalse(balance.settled)
        self.assertEqual(balance.state, "REFUND_DUE")
        with self.assertRaises(ValidationError):
            change_invoice_status(
                business=self.business, actor=self.user, invoice=invoice, status="CANCELLED"
            )
        key = uuid.uuid4()
        refund = self.refund(invoice, receipt, credit, 80, key)
        self.assertEqual(self.refund(invoice, receipt, credit, 80, key).pk, refund.pk)
        balance = self.balance(invoice)
        self.assertEqual((balance.net_paid, balance.outstanding, balance.refund_due), (20, 0, 0))
        self.assertTrue(balance.settled)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "PAID")
        self.assertEqual(list(invoice.lines.values()), original_lines)
        self.assertEqual(invoice.payments.get(pk=receipt.pk).amount, 100)
        with self.assertRaises(ValidationError):
            self.refund(invoice, receipt, credit, 1, reference="RETURN-2")
        with self.assertRaises(ValidationError):
            self.refund(invoice, receipt, credit, 79, key)
        with self.assertRaises(ValidationError):
            credit.save()

    def test_unpaid_partial_payment_and_payment_after_credit(self):
        for collected, refund_due, debt in ((0, 0, 20), (10, 0, 10), (40, 20, 0)):
            with self.subTest(collected=collected):
                parcel, charge, invoice, receipt = self.prepare(collected)
                case = self.settle(parcel, {"retained": {str(charge.pk): "20"}})
                balance = self.balance(invoice)
                self.assertEqual((balance.outstanding, balance.refund_due), (debt, refund_due))
                if debt:
                    record_invoice_payment(
                        business=self.business,
                        actor=self.user,
                        invoice=invoice,
                        amount=debt,
                        currency=invoice.currency_code,
                        method="CASH",
                        idempotency_key=uuid.uuid4(),
                    )
                if refund_due:
                    self.refund(
                        invoice,
                        receipt,
                        case.credits.get(),
                        refund_due,
                        reference=f"RETURN-{collected}",
                    )
                self.assertTrue(self.balance(invoice).settled)

    def test_uninvoiced_void_retry_and_no_reinvoicing(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        change_parcel_status(
            business=self.business, actor=self.user, parcel=parcel, status="CANCELLED"
        )
        parcel.refresh_from_db()
        plan = review_cancellation(business=self.business, actor=self.user, parcel=parcel)
        key = uuid.uuid4()
        fields = dict(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            choices={},
            fingerprint=plan["fingerprint"],
            idempotency_key=key,
            reason_reference="CANCEL-1",
        )
        case = confirm_cancellation(**fields)
        self.assertEqual(confirm_cancellation(**fields).pk, case.pk)
        charge.refresh_from_db()
        self.assertIsNotNone(charge.voided_at)
        with self.assertRaises(ValidationError):
            invoice_charges(business=self.business, actor=self.user, charge_ids=[charge.pk])
        with self.assertRaises(ValidationError):
            add_charge(
                business=self.business,
                actor=self.user,
                parcel=parcel,
                description="New charge",
                unit_price=10,
                idempotency_key=uuid.uuid4(),
            )
        with self.assertRaises(ValidationError):
            confirm_cancellation(**{**fields, "reason_reference": "CHANGED"})

    def test_shared_invoice_requires_allocation_and_preserves_sibling_clearance(self):
        a, b = self.parcel(), self.parcel()
        ca, cb = self.charge(parcel=a, unit_price=60), self.charge(parcel=b, unit_price=40)
        invoice = self.bill(ca, cb)
        self.issue(invoice)
        receipt = self.receipt(invoice, 100)
        change_parcel_status(business=self.business, actor=self.user, parcel=a, status="CANCELLED")
        a.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.settle(a)
        la, lb = invoice.lines.get(charge_source=ca), invoice.lines.get(charge_source=cb)
        choices = {
            "retained": {str(ca.pk): "20"},
            "invoices": {
                str(invoice.pk): {
                    "receipts": {
                        str(receipt.pk): {f"{la.pk}:{a.pk}": "60", f"{lb.pk}:{b.pk}": "40"}
                    }
                }
            },
        }
        case = self.settle(a, choices)
        self.assertEqual(
            (self.balance(invoice).outstanding, self.balance(invoice).refund_due), (0, 40)
        )
        sibling = resolve_parcel_workflow(business=self.business, actor=self.user, parcel=b)
        self.assertTrue(sibling.financial["clearance"]["cleared"])
        change_parcel_status(business=self.business, actor=self.user, parcel=b, status="RECEIVED")
        change_parcel_status(business=self.business, actor=self.user, parcel=b, status="IN_TRANSIT")
        self.refund(invoice, receipt, case.credits.get(), 40)
        self.assertTrue(self.balance(invoice).settled)
        self.assertEqual(invoice.lines.get(pk=lb.pk).line_total, 40)

    def test_shared_freight_requires_explicit_valid_basis(self):
        ship, a, b = self.shipment(), self.parcel(), self.parcel()
        self.cargo(ship, a, b)
        freight = self.charge(shipment=ship, unit_price=100)
        invoice = self.bill(freight)
        self.issue(invoice)
        change_parcel_status(business=self.business, actor=self.user, parcel=a, status="CANCELLED")
        a.refresh_from_db()
        with self.assertRaises(ValidationError):
            self.settle(a)
        line = invoice.lines.get()
        choices = {
            "invoices": {
                str(invoice.pk): {
                    "obligations": {f"{line.pk}:{a.pk}": "30", f"{line.pk}:{b.pk}": "70"}
                }
            }
        }
        self.settle(a, choices)
        self.assertEqual(self.balance(invoice).adjusted_total, 70)
        self.assertEqual(InvoiceObligationShare.objects.get(line=line, parcel=b).total, 70)

    def test_stale_preview_permissions_and_tenant_denial(self):
        parcel, charge, invoice, receipt = self.prepare(collected=40)
        plan = review_cancellation(business=self.business, actor=self.user, parcel=parcel)
        self.receipt(invoice, 10)
        with self.assertRaises(ValidationError):
            confirm_cancellation(
                business=self.business,
                actor=self.user,
                parcel=parcel,
                choices={},
                fingerprint=plan["fingerprint"],
                idempotency_key=uuid.uuid4(),
                reason_reference="CANCEL-1",
            )
        self.assertFalse(ParcelCancellationSettlement.objects.exists())
        self.membership.role = "staff"
        self.membership.save(update_fields=["role"])
        with self.assertRaises(PermissionDenied):
            review_cancellation(business=self.business, actor=self.user, parcel=parcel)
        response = self.client.get(
            reverse("logistics_parcel_cancellation_settlement", args=[parcel.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.membership.role = "owner"
        self.membership.save(update_fields=["role"])
        with self.assertRaises(PermissionDenied):
            review_cancellation(business=self.other, actor=self.user, parcel=parcel)

    def test_shipment_cancel_preserves_finances_and_allows_reassignment(self):
        ship, parcel = self.shipment(), self.parcel()
        self.cargo(ship, parcel)
        charge = self.charge(shipment=ship, unit_price=100)
        invoice = self.bill(charge)
        self.issue(invoice)
        self.receipt(invoice)
        change_shipment_status(
            business=self.business, actor=self.user, shipment=ship, status="CANCELLED"
        )
        parcel.refresh_from_db()
        self.assertEqual(parcel.current_status, "REGISTERED")
        self.assertIsNone(parcel.shipment_id)
        assign_parcel(
            business=self.business, actor=self.user, shipment=self.shipment(), parcel=parcel
        )
        self.assertEqual(invoice.payments.count(), 1)
        self.assertTrue(self.balance(invoice).settled)
        self.assertFalse(InvoiceCancellationCredit.objects.exists())
        self.assertEqual(
            set(charge.parcel_coverage.values_list("parcel_id", flat=True)), {parcel.pk}
        )

    def test_ui_preview_confirm_and_manual_refund(self):
        parcel, charge, invoice, receipt = self.prepare()
        url = reverse("logistics_parcel_cancellation_settlement", args=[parcel.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            url,
            {
                "reason_reference": "CANCEL-1",
                "idempotency_key": uuid.uuid4(),
                f"retained_{charge.pk}": "20",
            },
        )
        self.assertContains(response, "Confirm cancellation settlement")
        self.assertFalse(ParcelCancellationSettlement.objects.exists())
        token = response.context["confirmation"]
        self.assertRedirects(self.client.post(url, {"confirmation": token}), url)
        self.assertRedirects(self.client.post(url, {"confirmation": token}), url)
        case = ParcelCancellationSettlement.objects.get()
        credit = case.credits.get()
        self.assertContains(self.client.get(url), "Record completed refund")
        adjust_url = reverse("invoice_payment_adjust", args=[invoice.pk, receipt.pk])
        response = self.client.post(
            adjust_url,
            {
                "action": "REFUND",
                "amount": "80",
                "reference": "RETURN-UI",
                "reason_reference": "CANCEL-1",
                "idempotency_key": uuid.uuid4(),
                "cancellation_credit": credit.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.balance(invoice).settled)
        self.assertEqual(InvoicePayment.objects.filter(kind="REFUND").count(), 1)

    def test_shared_invoice_payment_after_credit_requires_exact_allocation(self):
        a, b = self.parcel(), self.parcel()
        ca, cb = self.charge(parcel=a, unit_price=60), self.charge(parcel=b, unit_price=40)
        invoice = self.bill(ca, cb)
        self.issue(invoice)
        receipt = self.receipt(invoice, 30)
        change_parcel_status(business=self.business, actor=self.user, parcel=a, status="CANCELLED")
        a.refresh_from_db()
        la, lb = invoice.lines.get(charge_source=ca), invoice.lines.get(charge_source=cb)
        choices = {
            "retained": {str(ca.pk): "20"},
            "invoices": {
                str(invoice.pk): {
                    "receipts": {
                        str(receipt.pk): {f"{la.pk}:{a.pk}": "10", f"{lb.pk}:{b.pk}": "20"}
                    }
                }
            },
        }
        self.settle(a, choices)
        self.assertEqual(
            (self.balance(invoice).outstanding, self.balance(invoice).refund_due), (30, 0)
        )
        fields = dict(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            amount=30,
            currency="USD",
            method="CASH",
            idempotency_key=uuid.uuid4(),
        )
        with self.assertRaises(ValidationError):
            record_invoice_payment(**fields)
        self.assertEqual(invoice.payments.count(), 1)
        shares = {
            s.parcel_id: s for s in InvoiceObligationShare.objects.filter(line__invoice=invoice)
        }
        response = self.client.post(
            reverse("invoice_payment_record", args=[invoice.pk]),
            {
                "amount": "30",
                "method": "CASH",
                "idempotency_key": fields["idempotency_key"],
                f"allocation_{shares[a.pk].pk}": "10",
                f"allocation_{shares[b.pk].pk}": "20",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.balance(invoice).settled)
        with self.assertRaises(ValidationError):
            record_invoice_payment(**fields, receipt_allocations={str(shares[a.pk].pk): "30"})

    def test_tax_and_shared_receipt_allocation_rounding(self):
        from decimal import Decimal

        self.business.tax_rate = Decimal("7.5")
        self.business.save(update_fields=["tax_rate"])
        a, b = self.parcel(), self.parcel()
        ca, cb = self.charge(parcel=a, unit_price=Decimal("43.33")), self.charge(
            parcel=b, unit_price=Decimal("56.67")
        )
        invoice = self.bill(ca, cb)
        self.issue(invoice)
        receipt = self.receipt(invoice)
        change_parcel_status(business=self.business, actor=self.user, parcel=a, status="CANCELLED")
        a.refresh_from_db()
        la, lb = invoice.lines.get(charge_source=ca), invoice.lines.get(charge_source=cb)
        choices = {
            "retained": {str(ca.pk): "2.22"},
            "invoices": {
                str(invoice.pk): {
                    "receipts": {
                        str(receipt.pk): {f"{la.pk}:{a.pk}": "46.58", f"{lb.pk}:{b.pk}": "60.92"}
                    }
                }
            },
        }
        credit = self.settle(a, choices).credits.get()
        self.assertEqual(credit.total, Decimal("44.19"))
        self.assertEqual(self.balance(invoice).adjusted_total, Decimal("63.31"))
        self.refund(invoice, receipt, credit, "44.19")
        self.assertTrue(self.balance(invoice).settled)
        self.assertEqual(invoice.total, Decimal("107.50"))

    def test_invalid_allocations_refund_target_and_history_retention(self):
        from apps.businesses.business_data_inventory import build_business_data_inventory
        from apps.businesses.business_data_purge import plan_business_purge

        a, b = self.parcel(), self.parcel()
        ca, cb = self.charge(parcel=a, unit_price=60), self.charge(parcel=b, unit_price=40)
        invoice = self.bill(ca, cb)
        self.issue(invoice)
        receipt = self.receipt(invoice)
        change_parcel_status(business=self.business, actor=self.user, parcel=a, status="CANCELLED")
        a.refresh_from_db()
        la, lb = invoice.lines.get(charge_source=ca), invoice.lines.get(charge_source=cb)
        for amount_a, amount_b in (("80", "20"), ("60", "30"), ("-1", "101")):
            with self.assertRaises(ValidationError):
                self.settle(
                    a,
                    {
                        "invoices": {
                            str(invoice.pk): {
                                "receipts": {
                                    str(receipt.pk): {
                                        f"{la.pk}:{a.pk}": amount_a,
                                        f"{lb.pk}:{b.pk}": amount_b,
                                    }
                                }
                            }
                        }
                    },
                )
        self.assertFalse(ParcelCancellationSettlement.objects.exists())
        case = self.settle(
            a,
            {
                "invoices": {
                    str(invoice.pk): {
                        "receipts": {
                            str(receipt.pk): {f"{la.pk}:{a.pk}": "60", f"{lb.pk}:{b.pk}": "40"}
                        }
                    }
                }
            },
        )
        other_parcel, other_charge, other_invoice, other_receipt = self.prepare()
        other_case = self.settle(other_parcel)
        with self.assertRaises(ValidationError):
            self.refund(invoice, receipt, other_case.credits.get(), 10)
        with self.assertRaises(ValidationError):
            self.refund(invoice, other_receipt, case.credits.get(), 10)
        inventory = build_business_data_inventory(self.business)
        self.assertTrue(
            any(
                r.key == "customer_cancellation_credits" and r.total_count
                for r in inventory.records
            )
        )
        self.assertIn(
            "customer_payment_history_protected", plan_business_purge(self.business.pk).blockers
        )

    def test_accountant_can_settle_and_staff_operational_cancellation_needs_accounting(self):
        from .location_test_support import approve_test_site

        parcel = self.parcel()
        self.charge(parcel=parcel)
        self.membership.role = "staff"
        self.membership.save(update_fields=["role"])
        approve_test_site(business=self.business, membership=self.membership, parcel=parcel)
        change_parcel_status(
            business=self.business, actor=self.user, parcel=parcel, status="CANCELLED"
        )
        parcel.refresh_from_db()
        response = self.client.get(reverse("logistics_parcel_detail", args=[parcel.pk]))
        self.assertContains(response, "Accounting must review cancellation settlement")
        self.assertNotContains(response, "Review cancellation settlement</a>")
        with self.assertRaises(PermissionDenied):
            self.settle(parcel)
        self.membership.role = "accountant"
        self.membership.save(update_fields=["role"])
        self.settle(parcel)
        self.assertEqual(ParcelCancellationSettlement.objects.get().recorded_by, self.user)


@skipUnless(connection.vendor == "postgresql", "Cancellation races require PostgreSQL row locks")
class CancellationSettlementConcurrencyTests(TransactionTestCase):
    setUp = CancellationSettlementTests.setUp
    parcel = CancellationSettlementTests.parcel
    shipment = CancellationSettlementTests.shipment
    charge = CancellationSettlementTests.charge
    bill = CancellationSettlementTests.bill
    issue = CancellationSettlementTests.issue
    receipt = CancellationSettlementTests.receipt
    prepare = CancellationSettlementTests.prepare
    settle = CancellationSettlementTests.settle
    balance = CancellationSettlementTests.balance
    refund = CancellationSettlementTests.refund

    def test_exact_confirmation_race_is_one_append_only_settlement(self):
        from .test_concurrency import race

        parcel, charge, invoice, receipt = self.prepare()
        choices = {"retained": {str(charge.pk): "20"}}
        plan = review_cancellation(
            business=self.business, actor=self.user, parcel=parcel, choices=choices
        )
        fields = dict(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            choices=choices,
            fingerprint=plan["fingerprint"],
            idempotency_key=uuid.uuid4(),
            reason_reference="CANCEL-1",
        )
        result = race([lambda: confirm_cancellation(**fields).pk] * 2)
        self.assertEqual(result[0], result[1])
        self.assertEqual(ParcelCancellationSettlement.objects.count(), 1)
        self.assertEqual(InvoiceCancellationCredit.objects.count(), 1)

    def test_competing_refunds_cannot_exceed_allocated_refund_due(self):
        from .test_concurrency import race

        parcel, charge, invoice, receipt = self.prepare()
        credit = self.settle(parcel, {"retained": {str(charge.pk): "20"}}).credits.get()
        results = race(
            [
                lambda: self.refund(
                    invoice, receipt, credit, 60, reference=f"RETURN-{uuid.uuid4()}"
                ).pk
            ]
            * 2
        )
        self.assertCountEqual([status for status, _ in results], ["ok", "rejected"])
        self.assertEqual(self.balance(invoice).refund_due, 20)
        self.assertEqual(invoice.payments.filter(kind="REFUND").count(), 1)

    def test_confirmation_racing_new_receipt_cannot_accept_stale_preview(self):
        from .test_concurrency import race

        parcel, charge, invoice, receipt = self.prepare(collected=40)
        plan = review_cancellation(business=self.business, actor=self.user, parcel=parcel)
        result = race(
            [
                lambda: confirm_cancellation(
                    business=self.business,
                    actor=self.user,
                    parcel=parcel,
                    choices={},
                    fingerprint=plan["fingerprint"],
                    idempotency_key=uuid.uuid4(),
                    reason_reference="CANCEL-1",
                ).pk,
                lambda: self.receipt(invoice, 10).pk,
            ]
        )
        self.assertCountEqual([status for status, _ in result], ["ok", "rejected"])
        balance = self.balance(invoice)
        self.assertFalse(balance.issues)
        self.assertIn((balance.net_paid, balance.refund_due), [(40, 40), (50, 0)])
