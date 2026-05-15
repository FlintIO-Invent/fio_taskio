from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessUser
from apps.crm.models import ActivityLog, Client

from .models import Invoice


class BillingBusinessScopingTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Alpha Workspace", slug="alpha-workspace")
        self.other_business = Business.objects.create(name="Bravo Workspace", slug="bravo-workspace")

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

        created_invoice = Invoice.objects.exclude(pk=self.invoice.pk).get()
        self.assertRedirects(response, reverse("invoice_detail", args=[created_invoice.id]))
        self.assertEqual(created_invoice.business, self.business)
        self.assertEqual(created_invoice.client, self.client_record)

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
