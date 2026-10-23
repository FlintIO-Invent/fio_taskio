from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CustomerPaymentMigrationTests(TransactionTestCase):
    def test_existing_paid_invoices_keep_status_and_amounts_without_receipts(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [
            ("billings", "0011_financial_coverage_snapshots"),
            ("logistics", "0021_backfill_financial_coverage"),
        ]
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            Business = apps.get_model("businesses", "Business")
            Client = apps.get_model("crm", "Client")
            Invoice = apps.get_model("billings", "Invoice")
            ids = []
            for vertical in ("SERVICE", "LOGISTICS"):
                business = Business.objects.create(
                    name=vertical, slug=f"legacy-payment-{vertical}", vertical=vertical
                )
                client = Client.objects.create(
                    business=business, first_name="Legacy", last_name="Client"
                )
                invoice = Invoice.objects.create(
                    business=business,
                    client=client,
                    invoice_number="HISTORY",
                    status="PAID",
                    subtotal="100",
                    tax="6.50",
                    total="106.50",
                )
                ids.append(invoice.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            Invoice, Payment = apps.get_model("billings", "Invoice"), apps.get_model(
                "billings", "InvoicePayment"
            )
            self.assertFalse(Payment.objects.exists())
            for invoice in Invoice.objects.filter(pk__in=ids):
                self.assertEqual(invoice.status, "PAID")
                self.assertEqual(str(invoice.total), "106.50")
                self.assertEqual(str(invoice.tax), "6.50")
        finally:
            MigrationExecutor(connection).migrate(latest)
