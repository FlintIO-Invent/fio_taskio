"""Saved applicability, logical identity, retained history and currency/tax snapshots."""

import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.billings.models import Invoice, InvoiceLine
from apps.billings.payment_services import adjust_invoice_payment, record_invoice_payment
from apps.billings.pdf import render_invoice_pdf, render_invoice_pdf_html
from apps.billings.services import (
    change_invoice_status,
    create_invoice_for_client,
    recalculate_invoice_totals,
)
from apps.businesses.business_data_inventory import build_business_data_inventory
from apps.businesses.demo_seed_reset import DemoSeedResetError, _validate_no_genuine_dependents
from apps.crm.models import Client

from . import test_billing
from .billing_forms import ChargeInvoiceForm
from .billing_services import (
    add_charge,
    confirm_legacy_charge_currency,
    confirm_legacy_invoice_snapshot,
    correct_charge,
    invoice_charges,
    void_charge,
)
from .financial_coverage import (
    clearance_for_parcel,
    coverage_for_parcel,
    coverage_for_parcels,
    coverage_for_shipment,
    record_legacy_charge_coverage,
)
from .models import LogisticsCharge, LogisticsChargeParcel
from .parcel_services import register_parcel
from .shipment_services import assign_parcel, remove_parcel


class FinancialCoverageTests(TestCase):
    setUp = test_billing.LogisticsBillingTests.setUp
    parcel = test_billing.LogisticsBillingTests.parcel
    shipment = test_billing.LogisticsBillingTests.shipment
    saved_service = test_billing.LogisticsBillingTests.saved_service

    def charge(self, parcel=None, shipment=None, **fields):
        return add_charge(
            business=self.business,
            actor=self.user,
            parcel=parcel,
            shipment=shipment,
            description=fields.pop("description", "Handling"),
            unit_price=fields.pop("unit_price", 25),
            idempotency_key=fields.pop("idempotency_key", uuid.uuid4()),
            **fields,
        )

    def bill(self, *charges, invoice=None):
        return invoice_charges(
            business=self.business,
            actor=self.user,
            charge_ids=[item.pk for item in charges],
            invoice=invoice,
        )

    def change(self, invoice, status):
        return change_invoice_status(
            business=self.business, actor=self.user, invoice=invoice, status=status
        )

    def cargo(self, shipment, *parcels):
        for parcel in parcels:
            assign_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=parcel)

    def coverage(self, parcel):
        return coverage_for_parcel(business=self.business, actor=self.user, parcel=parcel)

    def settle(self, invoice):
        invoice.refresh_from_db()
        return record_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            amount=invoice.total,
            currency=invoice.currency_code,
            method="CASH",
            reference=f"RECEIPT-{uuid.uuid4()}",
            idempotency_key=uuid.uuid4(),
        )

    def test_direct_charge_is_resolved_once_through_direct_and_snapshot_relationships(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        result = self.coverage(parcel)
        self.assertEqual([row.charge_id for row in result.charges], [charge.pk])
        self.assertEqual(result.totals_by_currency, {"USD": Decimal("25")})
        self.assertTrue(result.complete)
        self.assertFalse(result.cleared)
        invoice = self.bill(charge)
        self.change(invoice, "SENT")
        self.change(invoice, "PAID")
        self.assertFalse(self.coverage(parcel).cleared)
        receipt = self.settle(invoice)
        self.assertTrue(self.coverage(parcel).cleared)
        adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            payment=receipt,
            kind="REFUND",
            amount=5,
            reference="PARCEL-REFUND",
            reason_reference="CASE-REFUND",
            idempotency_key=uuid.uuid4(),
        )
        self.assertFalse(self.coverage(parcel).cleared)

    def test_empty_finances_never_imply_payment_or_clearance(self):
        result = self.coverage(self.parcel())
        self.assertFalse(result.complete)
        self.assertFalse(result.cleared)
        self.assertTrue(result.uncovered_parcel_ids)

    def test_unlinked_parcel_and_unproven_shipment_lines_never_imply_clearance(self):
        parcel, shipment = self.parcel(), self.shipment()
        charge = self.charge(parcel=parcel)
        paid = self.bill(charge)
        self.change(paid, "SENT")
        self.change(paid, "PAID")
        self.settle(paid)
        self.assertTrue(self.coverage(parcel).cleared)
        self.cargo(shipment, parcel)
        for target in ({"parcel": parcel}, {"shipment": shipment}):
            historical = create_invoice_for_client(actor=self.user, client=self.customer)
            InvoiceLine.objects.create(
                invoice=historical, description="Historical extra freight", unit_price=10, **target
            )
            recalculate_invoice_totals(historical, actor=self.user)
            self.change(historical, "SENT")
            result = self.coverage(parcel)
            self.assertFalse(result.complete)
            self.assertFalse(result.cleared)
            self.assertIn(
                "Unlinked financial history requires accounting coverage review.", result.issues
            )
            self.assertFalse(
                clearance_for_parcel(business=self.business, actor=self.user, parcel=parcel).cleared
            )
            self.change(historical, "CANCELLED")
            self.assertTrue(self.coverage(parcel).cleared)

    def test_direct_and_shared_freight_bulk_resolution_counts_each_charge_once(self):
        shipment, a, b = self.shipment(), self.parcel(), self.parcel()
        self.cargo(shipment, a, b)
        freight = self.charge(shipment=shipment, description="Freight", unit_price=150)
        handling = self.charge(parcel=a)
        invoice = self.bill(freight, handling)
        result = coverage_for_parcels(
            business=self.business, actor=self.user, parcel_ids=[a.pk, b.pk, a.pk]
        )
        self.assertEqual({row.charge_id for row in result.charges}, {freight.pk, handling.pk})
        self.assertEqual(result.totals_by_currency, {"USD": Decimal("175")})
        self.assertEqual(next(row for row in result.charges if row.shared).parcel_ids, (a.pk, b.pk))
        self.assertEqual(self.coverage(b).totals_by_currency, {"USD": Decimal("150")})
        self.assertEqual(
            coverage_for_shipment(
                business=self.business, actor=self.user, shipment=shipment
            ).totals_by_currency,
            result.totals_by_currency,
        )
        self.change(invoice, "SENT")
        self.change(invoice, "PAID")
        self.settle(invoice)
        self.assertTrue(self.coverage(a).cleared)

    def test_multiple_parcels_per_invoice_and_multiple_invoices_per_parcel(self):
        a, b = self.parcel(), self.parcel()
        first = self.bill(self.charge(parcel=a), self.charge(parcel=b))
        second = self.bill(self.charge(parcel=a, description="Insurance"))
        self.change(first, "SENT")
        self.change(first, "PAID")
        self.settle(first)
        self.assertFalse(self.coverage(a).cleared)
        self.assertTrue(self.coverage(b).cleared)
        self.change(second, "SENT")
        self.change(second, "PAID")
        self.settle(second)
        result = self.coverage(a)
        self.assertTrue(result.cleared)
        self.assertEqual(
            {pk for row in result.charges for pk in row.invoice_ids}, {first.pk, second.pk}
        )
        self.assertEqual(result.totals_by_currency, {"USD": Decimal("50")})

    def test_membership_is_frozen_at_charge_creation_before_and_after_billing(self):
        old, new, a, b = self.shipment(), self.shipment(), self.parcel(), self.parcel()
        self.cargo(old, a)
        freight = self.charge(shipment=old, description="Freight", unit_price=150)
        remove_parcel(business=self.business, actor=self.user, shipment=old, parcel=a)
        self.cargo(new, a)
        self.cargo(old, b)
        invoice = self.bill(freight)
        self.assertEqual(self.coverage(a).charges[0].charge_id, freight.pk)
        self.assertFalse(self.coverage(b).complete)
        self.assertEqual(set(freight.parcel_coverage.values_list("parcel_id", flat=True)), {a.pk})
        self.assertIn(
            b.pk,
            coverage_for_shipment(
                business=self.business, actor=self.user, shipment=old
            ).uncovered_parcel_ids,
        )
        self.change(invoice, "SENT")
        self.change(invoice, "CANCELLED")
        reissue = self.bill(freight)
        self.assertEqual(reissue.lines.get().charge_source_id, freight.pk)
        self.assertEqual(self.coverage(a).charges[0].parcel_ids, (a.pk,))

    def test_mixed_client_and_empty_shipments_cannot_create_freight(self):
        shipment = self.shipment()
        with self.assertRaises(ValidationError):
            self.charge(shipment=shipment)
        other = Client.objects.create(
            business=self.business, first_name="Other", last_name="Client"
        )
        first = self.parcel()
        second = register_parcel(
            business=self.business,
            actor=self.user,
            client=other,
            origin="A",
            destination="B",
            package_description="Other",
        )
        self.cargo(shipment, first, second)
        with self.assertRaises(ValidationError):
            self.charge(shipment=shipment)
        with self.assertRaises(ValidationError):
            coverage_for_shipment(business=self.business, actor=self.user, shipment=shipment)

    def test_fresh_retry_tokens_and_price_quantity_changes_do_not_create_logical_duplicates(self):
        parcel = self.parcel()
        first = self.charge(parcel=parcel, description=" Freight ")
        for fields in ({"description": "freight"}, {"unit_price": 50}, {"quantity": 2}):
            with self.assertRaises(ValidationError):
                self.charge(
                    parcel=parcel, description=fields.pop("description", "Freight"), **fields
                )
        self.assertEqual(LogisticsCharge.objects.count(), 1)
        second = self.charge(parcel=parcel, description="Freight", occurrence_reference="Leg-2")
        self.assertNotEqual(first.logical_key, second.logical_key)

    def test_retry_token_replay_keeps_original_membership(self):
        shipment, a, b, key = self.shipment(), self.parcel(), self.parcel(), uuid.uuid4()
        self.cargo(shipment, a)
        first = self.charge(shipment=shipment, idempotency_key=key)
        self.cargo(shipment, b)
        replay = self.charge(shipment=shipment, idempotency_key=key)
        self.assertEqual(replay.pk, first.pk)
        self.assertEqual(set(replay.parcel_coverage.values_list("parcel_id", flat=True)), {a.pk})

    def test_same_purpose_cannot_overlap_direct_and_shipment_coverage(self):
        shipment, parcel = self.shipment(), self.parcel()
        self.cargo(shipment, parcel)
        self.charge(shipment=shipment, description="Freight")
        with self.assertRaises(ValidationError):
            self.charge(parcel=parcel, description="freight")
        self.assertEqual(LogisticsCharge.objects.count(), 1)

    def test_saved_service_identity_does_not_depend_on_current_price_or_description(self):
        parcel, service = self.parcel(), self.saved_service()
        self.charge(parcel=parcel, service=service)
        service.unit_price = 500
        service.save()
        with self.assertRaises(ValidationError):
            self.charge(
                parcel=parcel, service=service, description="Different label", unit_price=500
            )

    def test_cancel_and_reissue_preserve_original_lines_and_one_active_binding(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        first = self.bill(charge)
        charge.refresh_from_db()
        original_line = charge.invoice_line_id
        self.change(first, "SENT")
        before = list(first.lines.values())
        self.change(first, "CANCELLED")
        self.assertEqual(self.coverage(parcel).charges[0].state, "UNINVOICED")
        second = self.bill(charge)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(self.bill(charge).pk, second.pk)
        charge.refresh_from_db()
        self.assertEqual(charge.invoice_line_id, original_line)
        self.assertEqual(list(first.lines.values()), before)
        self.assertEqual(charge.invoice_lines.count(), 2)
        self.assertEqual(charge.invoice_lines.exclude(invoice__status="CANCELLED").count(), 1)
        self.assertEqual(self.coverage(parcel).totals_by_currency, {"USD": Decimal("25")})
        form = ChargeInvoiceForm(
            business=self.business, actor=self.user, target=parcel, client=self.customer
        )
        self.assertFalse(form.fields["charges"].queryset.exists())
        for obj in (second, second.lines.get()):
            with self.assertRaises(ProtectedError):
                obj.delete()
        line = second.lines.get()
        line.charge_source = None
        with self.assertRaises(ValidationError):
            line.save()

    def test_cancelled_charge_can_be_selected_in_normal_invoice_form(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        first = self.bill(charge)
        self.change(first, "CANCELLED")
        self.business.currency = "EUR"
        self.business.save()
        form = ChargeInvoiceForm(
            business=self.business, actor=self.user, target=parcel, client=self.customer
        )
        self.assertEqual(list(form.fields["charges"].queryset), [charge])
        self.assertIn("$25.00", form.fields["charges"].label_from_instance(charge))
        response = self.client.get(reverse("logistics_parcel_invoice", args=[parcel.pk]))
        self.assertContains(response, "$25.00")
        self.assertNotContains(response, "€")
        response = self.client.post(
            reverse("logistics_parcel_invoice", args=[parcel.pk]), {"charges": [charge.pk]}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(charge.invoice_lines.count(), 2)

    def test_void_and_correction_require_cancelled_bindings_and_preserve_lineage(self):
        parcel, key = self.parcel(), uuid.uuid4()
        charge = self.charge(parcel=parcel)
        invoice = self.bill(charge)
        with self.assertRaises(ValidationError):
            correct_charge(
                business=self.business,
                actor=self.user,
                charge=charge,
                reason_reference="CASE-1",
                idempotency_key=key,
                unit_price=30,
            )
        self.change(invoice, "CANCELLED")
        corrected = correct_charge(
            business=self.business,
            actor=self.user,
            charge=charge,
            reason_reference="CASE-1",
            idempotency_key=key,
            unit_price=30,
        )
        self.assertEqual(corrected.supersedes_id, charge.pk)
        self.assertEqual(corrected.logical_key, charge.logical_key)
        charge.refresh_from_db()
        self.assertIsNotNone(charge.voided_at)
        self.assertEqual(
            correct_charge(
                business=self.business,
                actor=self.user,
                charge=charge,
                reason_reference="CASE-1",
                idempotency_key=key,
                unit_price=30,
            ).pk,
            corrected.pk,
        )
        reissue = self.bill(corrected)
        self.assertEqual(reissue.subtotal, Decimal("30"))
        self.assertEqual(self.coverage(parcel).totals_by_currency, {"USD": Decimal("30")})
        with self.assertRaises(ValidationError):
            self.bill(charge)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_invalid_correction_rolls_back_void_and_requires_reason(self):
        charge = self.charge(parcel=self.parcel())
        for price, reason in ((-1, "CASE-1"), (30, "")):
            with self.assertRaises(ValidationError):
                correct_charge(
                    business=self.business,
                    actor=self.user,
                    charge=charge,
                    reason_reference=reason,
                    idempotency_key=uuid.uuid4(),
                    unit_price=price,
                )
            charge.refresh_from_db()
            self.assertIsNone(charge.voided_at)
        self.assertEqual(LogisticsCharge.objects.count(), 1)

    def test_paid_invoice_cannot_be_cancelled_or_corrected_by_services(self):
        charge = self.charge(parcel=self.parcel())
        invoice = self.bill(charge)
        self.change(invoice, "SENT")
        self.change(invoice, "PAID")
        with self.assertRaises(ValidationError):
            self.change(invoice, "CANCELLED")
        with self.assertRaises(ValidationError):
            void_charge(
                business=self.business, actor=self.user, charge=charge, reason_reference="CASE-1"
            )

    def test_issued_currency_tax_totals_and_pdf_remain_stable_after_workspace_changes(self):
        self.business.tax_rate = Decimal("10")
        self.business.save()
        parcel = self.parcel()
        charge = self.charge(parcel=parcel, unit_price=100)
        invoice = self.bill(charge)
        self.change(invoice, "SENT")
        invoice.refresh_from_db()
        saved = (invoice.subtotal, invoice.tax, invoice.total)
        self.business.currency = "EUR"
        self.business.tax_rate = 20
        self.business.save()
        invoice = Invoice.objects.get(pk=invoice.pk)
        self.assertEqual(invoice.currency_code, "USD")
        self.assertEqual(invoice.tax_rate_percentage, Decimal("10"))
        self.assertEqual((invoice.subtotal, invoice.tax, invoice.total), saved)
        html = render_invoice_pdf_html(invoice, actor=self.user)
        self.assertIn("$110.00", html)
        self.assertNotIn("€", html)
        self.assertIn(b"USD", render_invoice_pdf(invoice, actor=self.user))
        self.assertContains(
            self.client.get(reverse("invoice_detail", args=[invoice.pk])), "$110.00"
        )
        with self.assertRaises(ValidationError):
            recalculate_invoice_totals(invoice, actor=self.user)
        invoice.total = 1
        with self.assertRaises(ValidationError):
            invoice.save()

    def test_reissue_retains_saved_currency_and_tax_and_rejects_mixed_currency_append(self):
        self.business.tax_rate = 10
        self.business.save()
        parcel = self.parcel()
        charge = self.charge(parcel=parcel, unit_price=100)
        invoice = self.bill(charge)
        self.change(invoice, "SENT")
        self.change(invoice, "CANCELLED")
        self.business.currency, self.business.tax_rate = "EUR", 20
        self.business.save()
        reissue = self.bill(charge)
        self.assertEqual(
            (reissue.currency_code, reissue.tax_rate_percentage, reissue.tax, reissue.total),
            ("USD", Decimal("10"), Decimal("10"), Decimal("110")),
        )
        later = self.charge(parcel=parcel, description="Insurance")
        with self.assertRaises(ValidationError):
            self.bill(later, invoice=reissue)
        self.assertEqual(
            self.coverage(parcel).totals_by_currency, {"USD": Decimal("100"), "EUR": Decimal("25")}
        )

    def test_cross_tenant_client_snapshot_and_source_relationships_are_rejected(self):
        charge = self.charge(parcel=self.parcel())
        foreign = register_parcel(
            business=self.other,
            actor=self.other_user,
            client=self.other_customer,
            origin="A",
            destination="B",
            package_description="Other",
        )
        with self.assertRaises(PermissionDenied):
            coverage_for_parcel(business=self.business, actor=self.user, parcel=foreign)
        with self.assertRaises(ValidationError):
            LogisticsChargeParcel(charge=charge, parcel=foreign)._domain_save()
        invoice = Invoice.objects.create(
            business=self.other, client=self.other_customer, invoice_number="FOREIGN"
        )
        with self.assertRaises(ValidationError):
            InvoiceLine.objects.create(
                invoice=invoice,
                charge_source=charge,
                parcel=charge.parcel,
                description=charge.invoice_description,
                quantity=charge.quantity,
                unit_price=charge.unit_price,
            )

    def test_snapshot_membership_cannot_expand_or_change(self):
        charge = self.charge(parcel=self.parcel())
        another = self.parcel()
        with self.assertRaises(ValidationError):
            LogisticsChargeParcel(charge=charge, parcel=another)._domain_save()
        edge = charge.parcel_coverage.get()
        edge.parcel = another
        with self.assertRaises(ValidationError):
            edge._domain_save()
        with self.assertRaises(ValidationError):
            charge.parcel_coverage.all().delete()

    def test_inventory_and_reset_detect_source_and_snapshot_dependents(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        invoice = self.bill(charge)
        inventory = build_business_data_inventory(business=self.business)
        self.assertEqual(inventory.summary.cross_tenant_integrity_blocker_count, 0)
        self.assertEqual(
            next(
                row for row in inventory.records if row.key == "logistics_charge_parcels"
            ).total_count,
            1,
        )
        with self.assertRaises(DemoSeedResetError):
            _validate_no_genuine_dependents(object_pks={"logistics.Parcel": (parcel.pk,)})
        with self.assertRaises(DemoSeedResetError):
            _validate_no_genuine_dependents(object_pks={"logistics.LogisticsCharge": (charge.pk,)})
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())

    def test_unproven_legacy_shipment_cargo_needs_explicit_attestation(self):
        shipment, a, b = self.shipment(), self.parcel(), self.parcel()
        self.cargo(shipment, a, b)
        charge = self.charge(shipment=shipment)
        # Simulate the intentionally unknown pre-migration Shipment membership.
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM logistics_logisticschargeparcel WHERE charge_id = %s", [charge.pk]
            )
            cursor.execute(
                "UPDATE logistics_logisticscharge SET coverage_recorded_at = NULL WHERE id = %s",
                [charge.pk],
            )
        charge.refresh_from_db()
        self.assertFalse(self.coverage(a).complete)
        with self.assertRaises(ValidationError):
            self.bill(charge)
        record_legacy_charge_coverage(
            business=self.business,
            actor=self.user,
            charge=charge,
            parcel_ids=[a.pk, b.pk],
            reason_reference="MANIFEST-1",
        )
        self.assertTrue(self.coverage(a).complete)
        with self.assertRaises(ValidationError):
            record_legacy_charge_coverage(
                business=self.business,
                actor=self.user,
                charge=charge,
                parcel_ids=[a.pk],
                reason_reference="MANIFEST-2",
            )

    def test_correction_requires_accounting_role_even_for_accessible_parcel(self):
        from apps.accounts.models import TaskIOUser
        from apps.businesses.models import BusinessUser

        from .location_test_support import approve_test_site

        staff = TaskIOUser.objects.create_user(email="coverage-worker@example.test")
        membership = BusinessUser.objects.create(business=self.business, user=staff, role="staff")
        parcel = self.parcel()
        approve_test_site(business=self.business, membership=membership, parcel=parcel)
        charge = self.charge(parcel=parcel)
        with self.assertRaises(PermissionDenied):
            correct_charge(
                business=self.business,
                actor=staff,
                charge=charge,
                reason_reference="CASE-1",
                idempotency_key=uuid.uuid4(),
                unit_price=30,
            )
        with self.assertRaises(PermissionDenied):
            add_charge(
                business=self.business,
                actor=staff,
                parcel=parcel,
                description="Other",
                unit_price=30,
                idempotency_key=uuid.uuid4(),
                _currency_snapshot="EUR",
            )

    def test_legacy_confirmations_require_evidence_and_preserve_all_money(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        invoice = self.bill(charge)
        self.change(invoice, "SENT")
        self.change(invoice, "CANCELLED")
        charge.refresh_from_db()
        charge.currency_is_legacy = True
        charge._domain_save(update_fields=["currency_is_legacy"])
        invoice.refresh_from_db()
        invoice.snapshot_is_legacy = True
        invoice.save(update_fields=["snapshot_is_legacy"])
        money = (
            invoice.subtotal,
            invoice.tax,
            invoice.total,
            invoice.currency_code,
            invoice.tax_rate_percentage,
        )
        with self.assertRaises(ValidationError):
            self.bill(charge)
        with self.assertRaises(ValidationError):
            confirm_legacy_charge_currency(
                business=self.business,
                actor=self.user,
                charge=charge,
                currency="EUR",
                reason_reference="DOC-1",
            )
        confirm_legacy_charge_currency(
            business=self.business,
            actor=self.user,
            charge=charge,
            currency="USD",
            reason_reference="DOC-1",
        )
        with self.assertRaises(ValidationError):
            self.bill(charge)
        confirm_legacy_invoice_snapshot(
            business=self.business,
            actor=self.user,
            invoice=invoice,
            currency="USD",
            tax_rate=invoice.tax_rate_percentage,
            reason_reference="DOC-1",
        )
        invoice.refresh_from_db()
        self.assertEqual(
            (
                invoice.subtotal,
                invoice.tax,
                invoice.total,
                invoice.currency_code,
                invoice.tax_rate_percentage,
            ),
            money,
        )
        reissue = self.bill(charge)
        self.assertEqual(reissue.total, invoice.total)
        self.assertTrue(self.coverage(parcel).complete)

    def test_cross_tenant_locations_are_rejected_by_charge_and_coverage_services(self):
        from .models import LogisticsLocation

        parcel = self.parcel()
        foreign = LogisticsLocation.objects.create(
            business=self.other,
            name="Foreign",
            code="FOREIGN",
            location_type="HUB",
            country_code="US",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE logistics_parcel SET origin_location_id = %s WHERE id = %s",
                [foreign.pk, parcel.pk],
            )
        with self.assertRaises(ValidationError):
            self.charge(parcel=parcel)
        with self.assertRaises(ValidationError):
            self.coverage(parcel)
        self.assertFalse(LogisticsCharge.objects.exists())

    def test_corrupt_cross_tenant_source_is_hidden_and_not_financially_clear(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        invoice = self.bill(charge)
        foreign_parcel = register_parcel(
            business=self.other,
            actor=self.other_user,
            client=self.other_customer,
            origin="A",
            destination="B",
            package_description="Foreign",
        )
        foreign = add_charge(
            business=self.other,
            actor=self.other_user,
            parcel=foreign_parcel,
            description="Foreign",
            unit_price=25,
            idempotency_key=uuid.uuid4(),
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE billings_invoiceline SET charge_source_id = %s WHERE invoice_id = %s",
                [foreign.pk, invoice.pk],
            )
        self.assertEqual(
            self.client.get(reverse("invoice_detail", args=[invoice.pk])).status_code, 404
        )
        self.assertFalse(self.coverage(parcel).complete)
        self.assertGreater(
            build_business_data_inventory(
                business=self.business
            ).summary.cross_tenant_integrity_blocker_count,
            0,
        )

    def test_void_history_requires_explicit_correction_and_cannot_reactivate(self):
        parcel = self.parcel()
        charge = self.charge(parcel=parcel)
        void_charge(
            business=self.business, actor=self.user, charge=charge, reason_reference="VOID-1"
        )
        with self.assertRaises(ValidationError):
            self.charge(parcel=parcel)
        charge.refresh_from_db()
        charge.voided_at = None
        with self.assertRaises(ValidationError):
            charge._domain_save(update_fields=["voided_at"])

    def test_dashboard_does_not_add_or_relabel_invoices_in_different_currencies(self):
        parcel = self.parcel()
        old = self.bill(self.charge(parcel=parcel, unit_price=100))
        self.change(old, "SENT")
        self.business.currency = "EUR"
        self.business.save()
        self.bill(self.charge(parcel=parcel, description="Insurance"))
        response = self.client.get(reverse("agent_dashboard"))
        self.assertEqual(response.context["outstanding_invoice_total"], Decimal("0"))
        self.assertEqual(response.context["draft_invoice_total"], Decimal("25"))
        bucket = response.context["other_currency_invoice_totals"][0]
        self.assertEqual(bucket["currency"], "USD")
        self.assertEqual(bucket["outstanding_invoice_total"], Decimal("100"))
        self.assertContains(response, "Saved Invoice currency: USD")
        self.assertContains(response, "$100.00")
        receipt = record_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=old,
            amount=40,
            currency="USD",
            method="CASH",
            reference="DASHBOARD-RECEIPT",
            idempotency_key=uuid.uuid4(),
        )
        response = self.client.get(reverse("agent_dashboard"))
        bucket = response.context["other_currency_invoice_totals"][0]
        self.assertEqual(
            (bucket["outstanding_invoice_total"], bucket["paid_invoice_total"]), (60, 40)
        )
        adjust_invoice_payment(
            business=self.business,
            actor=self.user,
            invoice=old,
            payment=receipt,
            kind="REFUND",
            amount=20,
            reference="DASHBOARD-REFUND",
            reason_reference="CASE-DASHBOARD",
            idempotency_key=uuid.uuid4(),
        )
        response = self.client.get(reverse("agent_dashboard"))
        bucket = response.context["other_currency_invoice_totals"][0]
        self.assertEqual(
            (bucket["outstanding_invoice_total"], bucket["paid_invoice_total"]), (80, 20)
        )

    def test_staff_clearance_for_shared_freight_exposes_no_invoice_or_other_cargo_data(self):
        from apps.accounts.models import TaskIOUser
        from apps.businesses.models import BusinessUser

        from .location_test_support import approve_test_site

        staff = TaskIOUser.objects.create_user(email="clearance-worker@example.test")
        membership = BusinessUser.objects.create(business=self.business, user=staff, role="staff")
        a, b, shipment = self.parcel(), self.parcel(), self.shipment()
        approve_test_site(business=self.business, membership=membership, parcel=a)
        self.cargo(shipment, a, b)
        freight = self.charge(shipment=shipment, unit_price=150)
        remove_parcel(business=self.business, actor=self.user, shipment=shipment, parcel=b)
        invoice = self.bill(freight)
        self.change(invoice, "SENT")
        before = clearance_for_parcel(business=self.business, actor=staff, parcel=a)
        self.assertTrue(before.complete)
        self.assertFalse(before.cleared)
        self.change(invoice, "PAID")
        self.settle(invoice)
        result = clearance_for_parcel(business=self.business, actor=staff, parcel=a)
        self.assertTrue(result.cleared)
        self.assertEqual(set(vars(result)), {"parcel_id", "complete", "cleared", "issues"})
        self.assertFalse(
            coverage_for_parcel(business=self.business, actor=staff, parcel=a).complete
        )
        with self.assertRaises(PermissionDenied):
            change_invoice_status(
                business=self.business, actor=staff, invoice=invoice, status="CANCELLED"
            )
        self.client.force_login(staff)
        self.assertEqual(
            self.client.get(reverse("invoice_detail", args=[invoice.pk])).status_code, 404
        )
        with self.assertRaises(PermissionDenied):
            clearance_for_parcel(business=self.business, actor=staff, parcel=b)

    def test_service_calls_reject_nonfinite_and_overprecise_charge_amounts(self):
        for price in ("NaN", "Infinity", "-1", "1.234"):
            with self.assertRaises(ValidationError):
                self.charge(parcel=self.parcel(), unit_price=price)
        self.assertFalse(LogisticsCharge.objects.exists())

    def test_trusted_purge_graph_clears_correction_and_reissue_edges_without_cycles(self):
        charge = self.charge(parcel=self.parcel())
        first = self.bill(charge)
        self.change(first, "CANCELLED")
        corrected = correct_charge(
            business=self.business,
            actor=self.user,
            charge=charge,
            reason_reference="CASE-1",
            idempotency_key=uuid.uuid4(),
            unit_price=30,
        )
        second = self.bill(corrected)
        self.change(second, "CANCELLED")
        third = self.bill(corrected)
        self.assertEqual(Invoice.objects.count(), 3)
        with self.assertRaises(ValidationError):
            LogisticsCharge.objects.all().delete()
        # Only trusted, separately gated purge/reset paths use this internal helper.
        LogisticsCharge.objects.filter(business=self.business)._purge_delete()
        self.assertFalse(LogisticsChargeParcel.objects.exists())
        self.assertFalse(InvoiceLine.objects.filter(charge_source__isnull=False).exists())
        Invoice.objects.filter(pk__in=[first.pk, second.pk, third.pk]).delete()
        self.assertFalse(Invoice.objects.exists())
