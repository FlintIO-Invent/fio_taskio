from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessUser
from apps.crm.models import ActivityLog, BusinessService, Client

from .models import Invoice, InvoiceLine


class BillingBusinessScopingTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Alpha Workspace",
            slug="alpha-workspace",
            currency="XCD",
            tax_rate=Decimal("6.50"),
            invoice_prefix="CLR",
            invoice_start_number=250,
        )
        self.other_business = Business.objects.create(
            name="Bravo Workspace",
            slug="bravo-workspace",
            currency="USD",
            tax_rate=Decimal("10.00"),
            invoice_prefix="BRV",
            invoice_start_number=100,
        )

        self.user = TaskIOUser.objects.create_user(
            email="owner@example.com",
            first_name="Owner",
            last_name="User",
            password="testpass123",
        )
        self.other_user = TaskIOUser.objects.create_user(
            email="other@example.com",
            first_name="Other",
            last_name="User",
            password="testpass123",
        )

        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        BusinessUser.objects.create(
            user=self.other_user,
            business=self.other_business,
            role=BusinessUser.Role.OWNER,
        )

        self.client_record = Client.objects.create(
            business=self.business,
            first_name="Alicia",
            last_name="Client",
            email="alicia@example.com",
            phone="+1 721 555 0001",
            company_name="Alpha Co",
            street_address="12 Main Street",
        )
        self.other_client_record = Client.objects.create(
            business=self.other_business,
            first_name="Boris",
            last_name="Client",
            email="boris@example.com",
            phone="+1 721 555 0002",
            company_name="Bravo Co",
            street_address="34 Side Street",
        )
        self.business_service = BusinessService.objects.create(
            business=self.business,
            name="Septic Pumping",
            description="Scheduled septic pumping service",
            unit_price=Decimal("125.00"),
            tax_rate=Decimal("6.50"),
        )
        self.other_business_service = BusinessService.objects.create(
            business=self.other_business,
            name="Roof Inspection",
            description="Roof inspection service",
            unit_price=Decimal("175.00"),
            tax_rate=Decimal("10.00"),
        )

        self.invoice = Invoice.objects.create(
            invoice_number="INV-ALPHA-001",
            business=self.business,
            client=self.client_record,
        )
        self.other_invoice = Invoice.objects.create(
            invoice_number="INV-BRAVO-001",
            business=self.other_business,
            client=self.other_client_record,
        )

    def test_invoice_list_only_shows_current_business_invoices(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("invoice_list"))

        self.assertEqual(response.status_code, 200)
        invoices = list(response.context["invoices"])
        self.assertEqual(invoices, [self.invoice])

    def test_invoice_detail_blocks_other_business_invoice(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("invoice_detail", args=[self.other_invoice.id]))

        self.assertEqual(response.status_code, 404)

    def test_invoice_create_from_client_sets_invoice_business(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("invoice_create_from_client", args=[self.client_record.id]))

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )
        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(created_invoice.business, self.business)
        self.assertEqual(created_invoice.client, self.client_record)
        self.assertEqual(created_invoice.invoice_number, "CLR-0250")
        self.assertEqual(created_invoice.tax, Decimal("0.00"))

    def test_invoice_create_page_only_lists_current_business_services(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("invoice_create_from_client", args=[self.client_record.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.business_service.name)
        self.assertNotContains(response, self.other_business_service.name)

    def test_invoice_create_from_client_uses_service_snapshot_values(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_client", args=[self.client_record.id]),
            data={
                "service_id": [str(self.business_service.id)],
                "description": [""],
                "quantity": [""],
                "unit_price": [""],
            },
        )

        created_invoice = Invoice.objects.get(
            business=self.business,
            invoice_number="CLR-0250",
        )
        line = created_invoice.lines.get()

        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(line.service, self.business_service)
        self.assertEqual(line.description, self.business_service.description)
        self.assertEqual(line.quantity, Decimal("1.00"))
        self.assertEqual(line.unit_price, Decimal("125.00"))
        self.assertEqual(line.line_total, Decimal("125.00"))
        self.assertEqual(created_invoice.subtotal, Decimal("125.00"))
        self.assertEqual(created_invoice.tax, Decimal("8.13"))
        self.assertEqual(created_invoice.total, Decimal("133.13"))

    def test_invoice_create_rejects_service_from_other_business(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_create_from_client", args=[self.client_record.id]),
            data={
                "service_id": [str(self.other_business_service.id)],
                "description": ["Tampered line"],
                "quantity": ["1"],
                "unit_price": ["999.00"],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "selected service is not available in this workspace")
        self.assertFalse(
            Invoice.objects.filter(
                business=self.business,
                invoice_number="CLR-0250",
            ).exists()
        )

    def test_invoice_status_change_logs_activity_for_current_business(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_change_status", args=[self.invoice.id]),
            data={"status": Invoice.Status.SENT},
        )

        self.invoice.refresh_from_db()
        activity_log = ActivityLog.objects.get(client=self.client_record, action_type=ActivityLog.ActionType.STATUS_CHANGED)

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertEqual(self.invoice.status, Invoice.Status.SENT)
        self.assertEqual(activity_log.business, self.business)

    def test_invoice_numbers_are_unique_per_business(self):
        Invoice.objects.create(
            invoice_number="SHARED-0001",
            business=self.business,
            client=self.client_record,
        )
        cross_business_invoice = Invoice.objects.create(
            invoice_number="SHARED-0001",
            business=self.other_business,
            client=self.other_client_record,
        )

        self.assertEqual(cross_business_invoice.business, self.other_business)

        with self.assertRaises(IntegrityError):
            Invoice.objects.create(
                invoice_number="SHARED-0001",
                business=self.business,
                client=self.client_record,
            )

    def test_invoice_edit_recalculates_tax_from_business_rate(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_edit", args=[self.invoice.id]),
            data={
                "notes": "Updated invoice",
                "new_description": ["Service call"],
                "new_quantity": ["2"],
                "new_unit_price": ["100.00"],
            },
        )

        self.invoice.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertEqual(self.invoice.subtotal, Decimal("200.00"))
        self.assertEqual(self.invoice.tax, Decimal("13.00"))
        self.assertEqual(self.invoice.total, Decimal("213.00"))

    def test_invoice_edit_uses_current_business_service_snapshot_values(self):
        line = InvoiceLine.objects.create(
            invoice=self.invoice,
            description="Old line",
            quantity=Decimal("1.00"),
            unit_price=Decimal("50.00"),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_edit", args=[self.invoice.id]),
            data={
                "notes": "Updated invoice",
                "line_id": [str(line.id)],
                "service_id": [str(self.business_service.id)],
                "description": ["Tampered description"],
                "quantity": ["2"],
                "unit_price": ["999.00"],
            },
        )

        self.invoice.refresh_from_db()
        line.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertEqual(line.service, self.business_service)
        self.assertEqual(line.description, self.business_service.description)
        self.assertEqual(line.quantity, Decimal("2.00"))
        self.assertEqual(line.unit_price, Decimal("125.00"))
        self.assertEqual(line.line_total, Decimal("250.00"))
        self.assertEqual(self.invoice.subtotal, Decimal("250.00"))
        self.assertEqual(self.invoice.tax, Decimal("16.25"))
        self.assertEqual(self.invoice.total, Decimal("266.25"))

    def test_invoice_edit_preserves_existing_service_snapshot_when_service_is_unchanged(self):
        line = InvoiceLine.objects.create(
            invoice=self.invoice,
            service=self.business_service,
            description="Quoted septic pumping service",
            quantity=Decimal("1.00"),
            unit_price=Decimal("110.00"),
        )
        self.business_service.description = "Updated service description"
        self.business_service.unit_price = Decimal("140.00")
        self.business_service.save()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("invoice_edit", args=[self.invoice.id]),
            data={
                "notes": "Keep the original quote",
                "line_id": [str(line.id)],
                "service_id": [str(self.business_service.id)],
                "description": ["Tampered description"],
                "quantity": ["2"],
                "unit_price": ["140.00"],
            },
        )

        self.invoice.refresh_from_db()
        line.refresh_from_db()

        self.assertRedirects(response, reverse("invoice_detail", args=[self.invoice.id]))
        self.assertEqual(line.service, self.business_service)
        self.assertEqual(line.description, "Quoted septic pumping service")
        self.assertEqual(line.unit_price, Decimal("110.00"))
        self.assertEqual(line.quantity, Decimal("2.00"))
        self.assertEqual(line.line_total, Decimal("220.00"))
        self.assertEqual(self.invoice.subtotal, Decimal("220.00"))
        self.assertEqual(self.invoice.tax, Decimal("14.30"))
        self.assertEqual(self.invoice.total, Decimal("234.30"))
