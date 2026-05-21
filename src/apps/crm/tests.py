from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import TaskIOUser
from apps.billings.models import Invoice
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .forms import PrivateClientForm, PrivateLeadForm
from .models import BusinessService, Client, Lead, ServiceCategory


class CRMBusinessScopingTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Alpha Workspace",
            slug="alpha-workspace",
            tax_rate=Decimal("6.50"),
        )
        self.other_business = Business.objects.create(
            name="Bravo Workspace",
            slug="bravo-workspace",
            tax_rate=Decimal("8.00"),
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

    def test_private_lead_form_limits_categories_to_current_business(self):
        current_category = ServiceCategory.objects.create(
            business=self.business,
            name="Tank Pumping",
        )
        ServiceCategory.objects.create(
            business=self.other_business,
            name="Roof Repair",
        )
        legacy_category = ServiceCategory.objects.create(
            name="Legacy Global Category",
            code="legacy_global_category",
        )
        lead = Lead.objects.create(
            business=self.business,
            category=legacy_category,
            lead_type=Lead.LeadType.REQUEST,
            status=Lead.Status.NEW,
            first_name="Jamie",
            last_name="Requester",
            email="legacy-request@example.com",
            phone="+1 721 555 7777",
            company_name="Legacy Request",
        )

        create_form = PrivateLeadForm(business=self.business)
        update_form = PrivateLeadForm(instance=lead, business=self.business)

        self.assertEqual(
            list(create_form.fields["category"].queryset),
            [current_category],
        )
        self.assertEqual(
            list(update_form.fields["category"].queryset),
            [legacy_category, current_category],
        )

    def test_public_request_only_shows_and_accepts_categories_for_target_business(self):
        current_category = ServiceCategory.objects.create(
            business=self.business,
            name="Tank Pumping",
        )
        foreign_category = ServiceCategory.objects.create(
            business=self.other_business,
            name="Roof Repair",
        )

        response = self.client.get(reverse("public_request", args=[self.business.slug]))

        self.assertContains(response, current_category.name)
        self.assertNotContains(response, foreign_category.name)

        invalid_response = self.client.post(
            reverse("public_request", args=[self.business.slug]),
            data={
                "lead_type": Lead.LeadType.REQUEST,
                "category": foreign_category.id,
                "first_name": "Jamie",
                "last_name": "Prospect",
                "company_name": "Alpha Customer",
                "email": "blocked@example.com",
                "phone": "+1 721 555 0003",
                "street_address": "45 Front Street",
                "district": "",
                "country": "Sint Maarten",
                "postal_code": "00000",
                "message": "Need a service visit this week.",
                "consent_to_contact": "on",
            },
        )

        self.assertEqual(invalid_response.status_code, 200)
        self.assertContains(invalid_response, "Select a valid choice")
        self.assertFalse(Lead.objects.filter(email="blocked@example.com").exists())

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

    def test_business_service_category_management_is_scoped_and_archives_instead_of_deleting(self):
        own_category = ServiceCategory.objects.create(
            business=self.business,
            name="Tank Pumping",
        )
        ServiceCategory.objects.create(
            business=self.other_business,
            name="Foreign Category",
        )

        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()

        list_response = self.client.get(reverse("business_service_category_list"))

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, own_category.name)
        self.assertNotContains(list_response, "Foreign Category")

        create_response = self.client.post(
            reverse("business_service_category_create"),
            {
                "name": "Emergency Callout",
                "code": "",
                "is_active": "on",
            },
            follow=True,
        )

        created_category = ServiceCategory.objects.get(name="Emergency Callout")

        self.assertRedirects(create_response, reverse("business_service_category_list"))
        self.assertEqual(created_category.business, self.business)
        self.assertEqual(created_category.code, "emergency_callout")

        update_response = self.client.post(
            reverse("business_service_category_update", args=[created_category.id]),
            {
                "name": "Emergency Dispatch",
                "code": "dispatch-priority",
                "is_active": "on",
            },
            follow=True,
        )

        created_category.refresh_from_db()

        self.assertRedirects(update_response, reverse("business_service_category_list"))
        self.assertEqual(created_category.name, "Emergency Dispatch")
        self.assertEqual(created_category.code, "dispatch_priority")

        archive_response = self.client.post(
            reverse("business_service_category_archive", args=[created_category.id]),
            follow=True,
        )

        created_category.refresh_from_db()

        self.assertRedirects(archive_response, reverse("business_service_category_list"))
        self.assertFalse(created_category.is_active)
        self.assertTrue(
            ServiceCategory.objects.filter(pk=created_category.pk).exists()
        )

    def test_business_service_rejects_category_from_another_business(self):
        foreign_category = ServiceCategory.objects.create(
            business=self.other_business,
            name="Foreign Category",
        )

        service = BusinessService(
            business=self.business,
            category=foreign_category,
            name="Cross-tenant service",
            unit_price=Decimal("25.00"),
            tax_rate=Decimal("6.50"),
        )

        with self.assertRaises(ValidationError):
            service.save()

    def test_business_service_management_is_scoped_and_archives_instead_of_deleting(self):
        current_category = ServiceCategory.objects.create(
            business=self.business,
            name="Diagnostics",
        )
        own_service = BusinessService.objects.create(
            business=self.business,
            category=current_category,
            name="Leak Inspection",
            unit_price=Decimal("75.00"),
            tax_rate=Decimal("6.50"),
        )
        BusinessService.objects.create(
            business=self.other_business,
            name="Foreign Service",
            unit_price=Decimal("99.00"),
            tax_rate=Decimal("8.00"),
        )

        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()

        list_response = self.client.get(reverse("business_service_list"))

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, own_service.name)
        self.assertNotContains(list_response, "Foreign Service")

        create_response = self.client.post(
            reverse("business_service_create"),
            {
                "category": current_category.id,
                "name": "Emergency Dispatch",
                "external_code": "EMERGENCY-001",
                "description": "Priority after-hours response",
                "unit_price": "125.00",
                "tax_rate": "",
                "is_active": "on",
            },
            follow=True,
        )

        created_service = BusinessService.objects.get(external_code="EMERGENCY-001")

        self.assertRedirects(create_response, reverse("business_service_list"))
        self.assertEqual(created_service.business, self.business)
        self.assertEqual(created_service.category, current_category)
        self.assertEqual(created_service.tax_rate, self.business.tax_rate)

        update_response = self.client.post(
            reverse("business_service_update", args=[created_service.id]),
            {
                "category": "",
                "name": "Emergency Dispatch Premium",
                "external_code": "EMERGENCY-001",
                "description": "Priority after-hours response with dispatch notes",
                "unit_price": "145.00",
                "tax_rate": "7.25",
                "is_active": "on",
            },
            follow=True,
        )

        created_service.refresh_from_db()

        self.assertRedirects(update_response, reverse("business_service_list"))
        self.assertEqual(created_service.name, "Emergency Dispatch Premium")
        self.assertIsNone(created_service.category)
        self.assertEqual(created_service.unit_price, Decimal("145.00"))
        self.assertEqual(created_service.tax_rate, Decimal("7.25"))

        archive_response = self.client.post(
            reverse("business_service_archive", args=[created_service.id]),
            follow=True,
        )

        created_service.refresh_from_db()

        self.assertRedirects(archive_response, reverse("business_service_list"))
        self.assertFalse(created_service.is_active)
        self.assertTrue(
            BusinessService.objects.filter(pk=created_service.pk).exists()
        )

    def test_business_service_csv_import_uses_current_business_scope_and_defaults(self):
        existing_category = ServiceCategory.objects.create(
            business=self.business,
            name="Maintenance",
        )
        foreign_category = ServiceCategory.objects.create(
            business=self.other_business,
            name="Diagnostics",
        )
        existing_service = BusinessService.objects.create(
            business=self.business,
            category=existing_category,
            name="Pipe Inspection",
            external_code="PIPE-001",
            unit_price=Decimal("60.00"),
            tax_rate=Decimal("3.00"),
        )

        csv_content = "\n".join(
            [
                "name,unit_price,description,tax_rate,category,is_active,external_code",
                "Pipe Inspection,95.00,Updated inspection package,,Maintenance,true,PIPE-001",
                "Drain Cleaning,120.00,Deep clean service,,Diagnostics,false,",
            ]
        )

        upload = SimpleUploadedFile(
            "services.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )

        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()

        response = self.client.post(
            reverse("business_service_import"),
            {"csv_file": upload},
            follow=True,
        )

        self.assertRedirects(response, reverse("business_service_list"))

        existing_service.refresh_from_db()
        imported_service = BusinessService.objects.get(name="Drain Cleaning")
        created_category = ServiceCategory.objects.get(
            business=self.business,
            name="Diagnostics",
        )

        self.assertEqual(existing_service.unit_price, Decimal("95.00"))
        self.assertEqual(existing_service.tax_rate, self.business.tax_rate)
        self.assertEqual(existing_service.category, existing_category)

        self.assertEqual(imported_service.business, self.business)
        self.assertEqual(imported_service.category, created_category)
        self.assertNotEqual(imported_service.category, foreign_category)
        self.assertEqual(imported_service.tax_rate, self.business.tax_rate)
        self.assertFalse(imported_service.is_active)

    def test_business_service_sample_csv_downloads_template(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()

        response = self.client.get(reverse("business_service_sample_csv"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        self.assertIn("name,unit_price,description,tax_rate,category,is_active,external_code", response.content.decode("utf-8"))

    def test_dashboard_shows_invoicing_links_when_plan_allows_module(self):
        plan = ClarivoPlan.objects.create(
            name="Pro",
            slug="pro-crm-test",
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
            slug="starter-crm-test",
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
