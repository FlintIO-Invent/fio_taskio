from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessUser

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
