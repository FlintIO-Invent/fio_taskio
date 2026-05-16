from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan

from .forms import PrivateClientForm
from .models import Client, Lead


class CRMBusinessScopingTests(TestCase):
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

    def test_private_client_form_limits_assigned_to_choices_to_current_business(self):
        form = PrivateClientForm(business=self.business)

        self.assertEqual(
            list(form.fields["assigned_to"].queryset),
            [self.user],
        )

    def test_staff_client_detail_blocks_other_business_client(self):
        foreign_client = Client.objects.create(
            business=self.other_business,
            first_name="Chris",
            last_name="Client",
            email="client@example.com",
            phone="+1 721 555 0001",
            company_name="Bravo Co",
            street_address="123 Main Street",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("staff_client_detail", args=[foreign_client.id]))

        self.assertEqual(response.status_code, 404)

    def test_public_request_creates_business_scoped_lead_and_client(self):
        response = self.client.post(
            reverse("public_request", args=[self.business.slug]),
            data={
                "lead_type": Lead.LeadType.REQUEST,
                "first_name": "Jamie",
                "last_name": "Prospect",
                "company_name": "Alpha Customer",
                "email": "jamie@example.com",
                "phone": "+1 721 555 0002",
                "street_address": "45 Front Street",
                "district": "",
                "country": "Sint Maarten",
                "postal_code": "00000",
                "message": "Need a service visit this week.",
                "consent_to_contact": "on",
            },
        )

        self.assertRedirects(response, reverse("public_thank_you"))

        lead = Lead.objects.get(email="jamie@example.com")
        self.assertEqual(lead.business, self.business)
        self.assertTrue(
            Client.objects.filter(
                business=self.business,
                email="jamie@example.com",
            ).exists()
        )

    def test_agent_dashboard_scopes_metrics_to_current_business(self):
        current_client = Client.objects.create(
            business=self.business,
            first_name="Casey",
            last_name="Client",
            email="casey@example.com",
            phone="+1 721 555 0100",
            company_name="Alpha Co",
            street_address="11 Main Street",
        )
        other_client = Client.objects.create(
            business=self.other_business,
            first_name="Robin",
            last_name="Client",
            email="robin@example.com",
            phone="+1 721 555 0101",
            company_name="Bravo Co",
            street_address="12 Main Street",
        )

        current_request = Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            status=Lead.Status.NEW,
            first_name="Jamie",
            last_name="Requester",
            email="jamie-request@example.com",
            phone="+1 721 555 0102",
            company_name="Alpha Request",
        )
        Lead.objects.create(
            business=self.other_business,
            lead_type=Lead.LeadType.REQUEST,
            status=Lead.Status.CONTACTED,
            first_name="Morgan",
            last_name="Requester",
            email="morgan-request@example.com",
            phone="+1 721 555 0103",
            company_name="Bravo Request",
        )

        Invoice.objects.create(
            business=self.business,
            client=current_client,
            invoice_number="ALPHA-1000",
            status=Invoice.Status.PAID,
            total=Decimal("125.00"),
        )
        Invoice.objects.create(
            business=self.business,
            client=current_client,
            invoice_number="ALPHA-1001",
            status=Invoice.Status.SENT,
            total=Decimal("50.00"),
        )
        Invoice.objects.create(
            business=self.other_business,
            client=other_client,
            invoice_number="BRAVO-1000",
            status=Invoice.Status.PAID,
            total=Decimal("900.00"),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["client_count"], 1)
        self.assertEqual(response.context["service_request_count"], 1)
        self.assertEqual(response.context["open_service_request_count"], 1)
        self.assertEqual(response.context["new_service_request_count"], 1)
        self.assertEqual(response.context["invoice_count"], 2)
        self.assertEqual(response.context["unpaid_invoice_count"], 1)
        self.assertEqual(response.context["paid_invoice_count"], 1)
        self.assertEqual(response.context["paid_invoice_total"], Decimal("125"))
        self.assertEqual(list(response.context["recent_service_requests"]), [current_request])

    def test_dashboard_shows_invoicing_links_when_plan_allows_module(self):
        plan = ClarivoPlan.objects.create(
            name="Pro",
            slug="pro",
            allow_invoicing=True,
        )
        BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("invoice_list"))
        self.assertContains(response, "Open Invoices")
        self.assertContains(response, "Included")

    def test_dashboard_hides_invoicing_links_when_plan_disables_module(self):
        plan = ClarivoPlan.objects.create(
            name="Starter",
            slug="starter",
            allow_invoicing=False,
        )
        BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("invoice_list"))
        self.assertContains(response, "Invoices Locked")
        self.assertContains(response, "Billing Module")
        self.assertContains(response, "Locked")
