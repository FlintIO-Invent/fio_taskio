"""Expansion/backfill retains amounts and does not infer historical Shipment cargo."""

import uuid
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class FinancialCoverageMigrationTests(TransactionTestCase):
    def test_backfill_preserves_history_unknown_cargo_duplicates_and_service_rows(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old = [
            ("billings", "0010_invoiceline_parcel_invoiceline_shipment"),
            ("logistics", "0019_logistics_test_lab_audit"),
        ]
        executor.migrate(old)
        state = executor.loader.project_state(old).apps
        try:
            Business = state.get_model("businesses", "Business")
            Client = state.get_model("crm", "Client")
            Parcel = state.get_model("logistics", "Parcel")
            Shipment = state.get_model("logistics", "Shipment")
            Invoice = state.get_model("billings", "Invoice")
            Line = state.get_model("billings", "InvoiceLine")
            Charge = state.get_model("logistics", "LogisticsCharge")
            business = Business.objects.create(
                name="Historical",
                slug="historical-finance",
                vertical="LOGISTICS",
                currency="EUR",
                tax_rate=20,
            )
            service = Business.objects.create(
                name="Service", slug="historical-service", currency="USD", tax_rate=12
            )
            customer = Client.objects.create(business=business, first_name="Historical")
            service_customer = Client.objects.create(business=service, first_name="Service")
            shipment = Shipment.objects.create(
                business=business, reference="SHIP-OLD", origin="A", destination="B"
            )
            parcel = Parcel.objects.create(
                business=business,
                client=customer,
                shipment=shipment,
                tracking_code="OLD-PARCEL",
                origin="A",
                destination="B",
                package_description="Box",
            )
            invoice = Invoice.objects.create(
                business=business,
                client=customer,
                invoice_number="OLD-1",
                status="SENT",
                subtotal=25,
                tax=Decimal("2.50"),
                total=Decimal("27.50"),
            )
            line = Line.objects.create(
                invoice=invoice,
                parcel=parcel,
                description="Handling — Parcel OLD-PARCEL",
                quantity=1,
                unit_price=25,
                line_total=25,
            )
            first = Charge.objects.create(
                business=business,
                client=customer,
                parcel=parcel,
                target_reference="OLD-PARCEL",
                description="Handling",
                quantity=1,
                unit_price=25,
                invoice_line=line,
                idempotency_key=uuid.uuid4(),
            )
            second = Charge.objects.create(
                business=business,
                client=customer,
                parcel=parcel,
                target_reference="OLD-PARCEL",
                description="Handling",
                quantity=1,
                unit_price=25,
                idempotency_key=uuid.uuid4(),
            )
            freight = Charge.objects.create(
                business=business,
                client=customer,
                shipment=shipment,
                target_reference="SHIP-OLD",
                description="Freight",
                quantity=1,
                unit_price=150,
                idempotency_key=uuid.uuid4(),
            )
            service_invoice = Invoice.objects.create(
                business=service,
                client=service_customer,
                invoice_number="SERVICE-1",
                status="PAID",
                subtotal=10,
                tax=Decimal("1.20"),
                total=Decimal("11.20"),
            )
            before_lines = list(
                Line.objects.values(
                    "id",
                    "invoice_id",
                    "description",
                    "quantity",
                    "unit_price",
                    "line_total",
                    "parcel_id",
                    "shipment_id",
                )
            )
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            Invoice = apps.get_model("billings", "Invoice")
            Charge = apps.get_model("logistics", "LogisticsCharge")
            Coverage = apps.get_model("logistics", "LogisticsChargeParcel")
            Line = apps.get_model("billings", "InvoiceLine")
            migrated = Invoice.objects.get(pk=invoice.pk)
            self.assertEqual(
                (migrated.currency_snapshot, migrated.tax_rate_snapshot), ("EUR", Decimal("10"))
            )
            self.assertEqual(
                (migrated.subtotal, migrated.tax, migrated.total, migrated.status),
                (Decimal("25"), Decimal("2.50"), Decimal("27.50"), "SENT"),
            )
            self.assertTrue(migrated.snapshot_is_legacy)
            self.assertIsNotNone(migrated.financial_snapshot_at)
            self.assertEqual(Line.objects.get(pk=line.pk).charge_source_id, first.pk)
            self.assertEqual(
                list(
                    Line.objects.values(
                        "id",
                        "invoice_id",
                        "description",
                        "quantity",
                        "unit_price",
                        "line_total",
                        "parcel_id",
                        "shipment_id",
                    )
                ),
                before_lines,
            )
            self.assertEqual(Charge.objects.count(), 3)
            self.assertIsNone(Charge.objects.get(pk=first.pk).logical_key)
            self.assertIsNone(Charge.objects.get(pk=second.pk).logical_key)
            self.assertEqual(Coverage.objects.count(), 2)
            self.assertIsNone(Charge.objects.get(pk=freight.pk).coverage_recorded_at)
            self.assertFalse(Coverage.objects.filter(charge_id=freight.pk).exists())
            unchanged = Invoice.objects.get(pk=service_invoice.pk)
            self.assertIsNone(unchanged.currency_snapshot)
            self.assertIsNone(unchanged.tax_rate_snapshot)
            self.assertIsNone(unchanged.financial_snapshot_at)
            self.assertFalse(unchanged.snapshot_is_legacy)
            self.assertEqual(
                (unchanged.subtotal, unchanged.tax, unchanged.total),
                (Decimal("10"), Decimal("1.20"), Decimal("11.20")),
            )
        finally:
            MigrationExecutor(connection).migrate(latest)
