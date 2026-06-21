from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .forms import PrivateClientForm, PrivateLeadForm
from .models import BusinessService, Client, Lead, ServiceCategory
from .services import sync_client_from_lead


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
        self.public_request_plan = ClarivoPlan.objects.create(
            name="Requests Enabled",
            slug="requests-enabled-tests",
            allow_public_request_form=True,
        )
        BusinessSubscription.objects.create(
            business=self.business,
            plan=self.public_request_plan,
            status=BusinessSubscription.Status.ACTIVE,
        )
        BusinessSubscription.objects.create(
            business=self.other_business,
            plan=self.public_request_plan,
            status=BusinessSubscription.Status.ACTIVE,
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
        self.staff_user = TaskIOUser.objects.create_user(
            email="staff@example.com",
            first_name="Staff",
            last_name="User",
            password="testpass123",
        )
        self.accountant_user = TaskIOUser.objects.create_user(
            email="accountant@example.com",
            first_name="Accountant",
            last_name="User",
            password="testpass123",
        )
        self.viewer_user = TaskIOUser.objects.create_user(
            email="viewer@example.com",
            first_name="Viewer",
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
        BusinessUser.objects.create(
            user=self.staff_user,
            business=self.business,
            role=BusinessUser.Role.STAFF,
        )
        BusinessUser.objects.create(
            user=self.accountant_user,
            business=self.business,
            role=BusinessUser.Role.ACCOUNTANT,
        )
        BusinessUser.objects.create(
            user=self.viewer_user,
            business=self.business,
            role=BusinessUser.Role.VIEWER,
        )

    def _enable_invoicing_for_business(self):
        invoicing_plan = ClarivoPlan.objects.create(
            name="Requests and Billing",
            slug="requests-and-billing-tests",
            allow_public_request_form=True,
            allow_invoicing=True,
        )
        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = invoicing_plan
        subscription.save(update_fields=["plan", "updated_at"])

    def _enable_appointments_for_business(self):
        appointments_plan = ClarivoPlan.objects.create(
            name="Requests and Appointments",
            slug="requests-and-appointments-tests",
            allow_public_request_form=True,
            allow_appointments=True,
        )
        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = appointments_plan
        subscription.save(update_fields=["plan", "updated_at"])

    def _build_request_lead(self, **overrides):
        lead_data = {
            "business": self.business,
            "lead_type": Lead.LeadType.REQUEST,
            "status": Lead.Status.NEW,
            "first_name": "Jamie",
            "last_name": "Requester",
            "email": "jamie-request@example.com",
            "phone": "+1 721 555 4444",
            "company_name": "Alpha Request Co",
            "street_address": "45 Front Street",
            "message": "Need service this week.",
        }
        lead_data.update(overrides)
        return Lead.objects.create(**lead_data)

    def test_private_client_form_limits_assigned_to_choices_to_current_business(self):
        form = PrivateClientForm(business=self.business)

        self.assertEqual(
            list(form.fields["assigned_to"].queryset),
            [self.accountant_user, self.user, self.staff_user],
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

    def test_client_detail_shows_only_that_clients_current_business_appointments(self):
        self._enable_appointments_for_business()
        target_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="jamie-client@example.com",
            phone="+1 721 555 1010",
            company_name="Target Client Co",
            street_address="12 Main Street",
        )
        other_current_business_client = Client.objects.create(
            business=self.business,
            first_name="Robin",
            last_name="Client",
            email="robin-client@example.com",
            phone="+1 721 555 2020",
            company_name="Other Current Co",
            street_address="14 Main Street",
        )
        other_business_client = Client.objects.create(
            business=self.other_business,
            first_name="Taylor",
            last_name="Client",
            email="taylor-client@example.com",
            phone="+1 721 555 3030",
            company_name="Other Business Co",
            street_address="99 Foreign Street",
        )
        start_time = timezone.now().replace(second=0, microsecond=0)
        upcoming_appointment = Appointment.objects.create(
            business=self.business,
            client=target_client,
            title="Target upcoming visit",
            start_time=start_time + timedelta(days=1),
            end_time=start_time + timedelta(days=1, hours=1),
            status=Appointment.Status.SCHEDULED,
        )
        completed_appointment = Appointment.objects.create(
            business=self.business,
            client=target_client,
            title="Target completed visit",
            start_time=start_time - timedelta(days=2),
            end_time=start_time - timedelta(days=2) + timedelta(hours=1),
            status=Appointment.Status.COMPLETED,
        )
        Appointment.objects.create(
            business=self.business,
            client=other_current_business_client,
            title="Other client visit",
            start_time=start_time + timedelta(days=3),
            end_time=start_time + timedelta(days=3, hours=1),
            status=Appointment.Status.SCHEDULED,
        )
        Appointment.objects.create(
            business=self.other_business,
            client=other_business_client,
            title="Foreign client visit",
            start_time=start_time + timedelta(days=4),
            end_time=start_time + timedelta(days=4, hours=1),
            status=Appointment.Status.SCHEDULED,
        )

        self.client.force_login(self.user)

        response = self.client.get(reverse("staff_client_detail", args=[target_client.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("appointment_detail", args=[upcoming_appointment.id]))
        self.assertContains(response, reverse("appointment_detail", args=[completed_appointment.id]))
        self.assertContains(response, "Target upcoming visit")
        self.assertContains(response, "Target completed visit")
        self.assertNotContains(response, "Other client visit")
        self.assertNotContains(response, "Foreign client visit")

    def test_client_detail_shows_schedule_appointment_button_only_for_manage_roles(self):
        self._enable_appointments_for_business()
        client_record = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="schedule-client@example.com",
            phone="+1 721 555 4040",
            company_name="Schedule Client Co",
            street_address="22 Main Street",
        )
        schedule_url = f"{reverse('appointment_create')}?client_id={client_record.id}"

        self.client.force_login(self.staff_user)
        staff_response = self.client.get(reverse("staff_client_detail", args=[client_record.id]))
        self.assertContains(staff_response, schedule_url)

        self.client.logout()
        self.client.force_login(self.accountant_user)
        accountant_response = self.client.get(reverse("staff_client_detail", args=[client_record.id]))
        self.assertNotContains(accountant_response, schedule_url)

        self.client.logout()
        self.client.force_login(self.viewer_user)
        viewer_response = self.client.get(reverse("staff_client_detail", args=[client_record.id]))
        self.assertNotContains(viewer_response, schedule_url)

    def test_public_request_creates_business_scoped_lead_and_client(self):
        foreign_client = Client.objects.create(
            business=self.other_business,
            first_name="Jamie",
            last_name="Foreign",
            email="jamie@example.com",
            phone="+1 721 555 9998",
            company_name="Bravo Customer",
            street_address="99 Foreign Street",
        )

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
        client = Client.objects.get(business=self.business, email="jamie@example.com")

        self.assertEqual(lead.business, self.business)
        self.assertEqual(client.client_type, Client.ClientType.BUSINESS)
        self.assertEqual(client.client_status, Client.ClientStatus.LEAD)
        self.assertEqual(client.lead_source, Client.LeadSource.WEBSITE)
        self.assertEqual(client.priority, Client.Priority.MEDIUM)
        self.assertTrue(client.consent_to_contact)
        self.assertTrue(client.is_active)
        self.assertIn("Public request #", client.communication_notes)
        self.assertIn("Need a service visit this week.", client.communication_notes)
        self.assertEqual(foreign_client.business, self.other_business)
        self.assertEqual(
            Client.objects.filter(email="jamie@example.com").count(),
            2,
        )

    def test_public_request_updates_empty_fields_on_existing_client(self):
        category = ServiceCategory.objects.create(
            business=self.business,
            name="Tank Pumping",
        )
        existing_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Prospect",
            email="jamie-existing@example.com",
            phone="",
            company_name="",
            street_address="",
            district="",
            country="",
            postal_code="",
            message="",
            communication_notes="Existing relationship note.",
            lead_source="",
        )

        response = self.client.post(
            reverse("public_request", args=[self.business.slug]),
            data={
                "lead_type": Lead.LeadType.REQUEST,
                "category": category.id,
                "first_name": "Jamie",
                "last_name": "Prospect",
                "company_name": "Alpha Customer",
                "email": "jamie-existing@example.com",
                "phone": "+1 721 555 0002",
                "street_address": "45 Front Street",
                "district": Lead.DistrictChoices.PHILIPSBURG,
                "country": "Sint Maarten",
                "postal_code": "00000",
                "message": "Need a service visit this week.",
                "consent_to_contact": "on",
            },
        )

        existing_client.refresh_from_db()

        self.assertRedirects(response, reverse("public_thank_you"))
        self.assertEqual(existing_client.phone, "+1 721 555 0002")
        self.assertEqual(existing_client.company_name, "Alpha Customer")
        self.assertEqual(existing_client.street_address, "45 Front Street")
        self.assertEqual(existing_client.district, Lead.DistrictChoices.PHILIPSBURG)
        self.assertEqual(existing_client.country, "Sint Maarten")
        self.assertEqual(existing_client.postal_code, "00000")
        self.assertEqual(existing_client.message, "Need a service visit this week.")
        self.assertEqual(existing_client.lead_source, Client.LeadSource.WEBSITE)
        self.assertIn("Existing relationship note.", existing_client.communication_notes)
        self.assertIn("Public request #", existing_client.communication_notes)
        self.assertIn("Category: Tank Pumping", existing_client.communication_notes)
        self.assertIn("Need a service visit this week.", existing_client.communication_notes)

    def test_public_request_does_not_overwrite_richer_existing_client_data(self):
        category = ServiceCategory.objects.create(
            business=self.business,
            name="Emergency Callout",
        )
        existing_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Prospect",
            email="jamie-protected@example.com",
            phone="+1 721 555 1234",
            company_name="Trusted Client",
            business_legal_name="Trusted Client N.V.",
            trade_name="Trusted",
            industry="Hospitality",
            business_description="Long-term account",
            website="https://trusted.example.com",
            registration_number="REG-123",
            client_status=Client.ClientStatus.ACTIVE,
            lead_source=Client.LeadSource.REFERRAL,
            priority=Client.Priority.HIGH,
            assigned_to=self.user,
            street_address="Stored Address",
            district=Client.DistrictChoices.MAHO,
            country="Curacao",
            postal_code="1111",
            message="Existing internal summary.",
            communication_notes="Prior call logged.",
            notes="VIP account notes.",
            consent_to_contact=True,
        )

        response = self.client.post(
            reverse("public_request", args=[self.business.slug]),
            data={
                "lead_type": Lead.LeadType.REQUEST,
                "category": category.id,
                "first_name": "Jamie",
                "last_name": "Prospect",
                "company_name": "New Public Name",
                "email": "jamie-protected@example.com",
                "phone": "+1 721 555 9999",
                "street_address": "45 Front Street",
                "district": Lead.DistrictChoices.PHILIPSBURG,
                "country": "Sint Maarten",
                "postal_code": "00000",
                "message": "Urgent dispatch needed.",
                "consent_to_contact": "on",
            },
        )

        existing_client.refresh_from_db()

        self.assertRedirects(response, reverse("public_thank_you"))
        self.assertEqual(existing_client.company_name, "Trusted Client")
        self.assertEqual(existing_client.phone, "+1 721 555 1234")
        self.assertEqual(existing_client.business_legal_name, "Trusted Client N.V.")
        self.assertEqual(existing_client.trade_name, "Trusted")
        self.assertEqual(existing_client.industry, "Hospitality")
        self.assertEqual(existing_client.business_description, "Long-term account")
        self.assertEqual(existing_client.website, "https://trusted.example.com")
        self.assertEqual(existing_client.registration_number, "REG-123")
        self.assertEqual(existing_client.client_status, Client.ClientStatus.ACTIVE)
        self.assertEqual(existing_client.lead_source, Client.LeadSource.REFERRAL)
        self.assertEqual(existing_client.priority, Client.Priority.HIGH)
        self.assertEqual(existing_client.assigned_to, self.user)
        self.assertEqual(existing_client.street_address, "Stored Address")
        self.assertEqual(existing_client.district, Client.DistrictChoices.MAHO)
        self.assertEqual(existing_client.country, "Curacao")
        self.assertEqual(existing_client.postal_code, "1111")
        self.assertEqual(existing_client.message, "Existing internal summary.")
        self.assertEqual(existing_client.notes, "VIP account notes.")
        self.assertIn("Prior call logged.", existing_client.communication_notes)
        self.assertIn("Public request #", existing_client.communication_notes)
        self.assertIn("Category: Emergency Callout", existing_client.communication_notes)
        self.assertIn("Urgent dispatch needed.", existing_client.communication_notes)

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

    def test_public_request_returns_unavailable_page_when_plan_disables_form(self):
        locked_plan = ClarivoPlan.objects.create(
            name="No Public Requests",
            slug="no-public-requests-tests",
            allow_public_request_form=False,
        )
        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = locked_plan
        subscription.save(update_fields=["plan", "updated_at"])

        response = self.client.post(
            reverse("public_request", args=[self.business.slug]),
            data={
                "lead_type": Lead.LeadType.REQUEST,
                "first_name": "Blocked",
                "last_name": "Requester",
                "company_name": "Blocked Co",
                "email": "blocked-plan@example.com",
                "phone": "+1 721 555 9999",
                "street_address": "45 Front Street",
                "district": "",
                "country": "Sint Maarten",
                "postal_code": "00000",
                "message": "Need a service visit this week.",
                "consent_to_contact": "on",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Request Form Unavailable", status_code=403)
        self.assertContains(
            response,
            "Public Request Form is not included in the current workspace plan",
            status_code=403,
        )
        self.assertFalse(Lead.objects.filter(email="blocked-plan@example.com").exists())

    def test_sync_client_from_lead_can_fall_back_to_same_business_phone_when_email_missing(self):
        existing_client = Client.objects.create(
            business=self.business,
            first_name="Phone",
            last_name="Match",
            email="stored@example.com",
            phone="+1 721 555 0109",
            company_name="Phone Match Co",
            street_address="12 Main Street",
        )
        lead = Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            status=Lead.Status.NEW,
            first_name="Jamie",
            last_name="Requester",
            email="",
            phone="+1 (721) 555-0109",
            company_name="Alpha Customer",
            street_address="45 Front Street",
            message="Need a service visit this week.",
        )

        client, created = sync_client_from_lead(lead)
        existing_client.refresh_from_db()

        self.assertFalse(created)
        self.assertEqual(client.pk, existing_client.pk)
        self.assertIn("Public request #", existing_client.communication_notes)

    def test_staff_can_convert_request_to_new_client(self):
        lead = self._build_request_lead(email="convert-new@example.com")

        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse("staff_lead_convert_to_client", args=[lead.id]),
            data={
                "first_name": lead.first_name,
                "last_name": lead.last_name,
                "company_name": lead.company_name,
                "email": lead.email,
                "phone": lead.phone,
                "street_address": lead.street_address,
                "district": lead.district,
                "country": lead.country,
                "postal_code": lead.postal_code,
                "message": lead.message,
                "consent_to_contact": "on",
            },
        )

        created_client = Client.objects.get(business=self.business, email="convert-new@example.com")

        self.assertRedirects(response, reverse("staff_client_detail", args=[created_client.id]))
        self.assertEqual(created_client.first_name, lead.first_name)
        self.assertEqual(created_client.street_address, lead.street_address)
        self.assertIn("Public request #", created_client.communication_notes)

    def test_convert_request_reuses_existing_client_in_same_business(self):
        existing_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Matched",
            email="existing-match@example.com",
            phone="+1 721 555 7777",
            company_name="Existing Match Co",
            street_address="Stored Address",
        )
        lead = self._build_request_lead(
            email="",
            phone="+1 721 555 8888",
            company_name="Lead Company",
        )

        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse("staff_lead_convert_to_client", args=[lead.id]),
            data={
                "first_name": "Jamie",
                "last_name": "Requester",
                "company_name": "Lead Company",
                "email": existing_client.email,
                "phone": lead.phone,
                "street_address": lead.street_address,
                "district": lead.district,
                "country": lead.country,
                "postal_code": lead.postal_code,
                "message": lead.message,
                "consent_to_contact": "on",
            },
        )

        existing_client.refresh_from_db()
        lead.refresh_from_db()

        self.assertRedirects(response, reverse("staff_client_detail", args=[existing_client.id]))
        self.assertEqual(Client.objects.filter(business=self.business, email=existing_client.email).count(), 1)
        self.assertEqual(lead.email, existing_client.email)
        self.assertIn("Public request #", existing_client.communication_notes)

    def test_missing_required_fields_show_conversion_form(self):
        lead = self._build_request_lead(
            email="missing-required@example.com",
            company_name="",
            street_address="",
        )

        self.client.force_login(self.staff_user)

        get_response = self.client.get(reverse("staff_lead_convert_to_client", args=[lead.id]))
        post_response = self.client.post(
            reverse("staff_lead_convert_to_client", args=[lead.id]),
            data={
                "first_name": lead.first_name,
                "last_name": lead.last_name,
                "company_name": "",
                "email": lead.email,
                "phone": lead.phone,
                "street_address": "",
                "district": lead.district,
                "country": lead.country,
                "postal_code": lead.postal_code,
                "message": lead.message,
            },
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Company name")
        self.assertContains(get_response, "Street address")
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "This field is required.")
        self.assertFalse(Client.objects.filter(business=self.business, email="missing-required@example.com").exists())

    def test_other_business_cannot_convert_request(self):
        foreign_lead = Lead.objects.create(
            business=self.other_business,
            lead_type=Lead.LeadType.REQUEST,
            status=Lead.Status.NEW,
            first_name="Morgan",
            last_name="Foreign",
            email="foreign-request@example.com",
            phone="+1 721 555 0099",
            company_name="Bravo Request",
            street_address="99 Foreign Street",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("staff_lead_convert_to_client", args=[foreign_lead.id]))

        self.assertEqual(response.status_code, 404)

    def test_viewer_cannot_convert_request(self):
        lead = self._build_request_lead(email="viewer-blocked@example.com")

        self.client.force_login(self.viewer_user)

        response = self.client.get(
            reverse("staff_lead_convert_to_client", args=[lead.id]),
            follow=True,
        )

        self.assertRedirects(response, reverse("staff_lead_list"))
        self.assertContains(
            response,
            "You do not have permission to convert service requests into clients.",
        )

    def test_accountant_can_start_invoice_from_request_but_cannot_edit_request(self):
        self._enable_invoicing_for_business()
        matched_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="accountant-request@example.com",
            phone="+1 721 555 2233",
            company_name="Matched Client Co",
            street_address="12 Main Street",
        )
        lead = self._build_request_lead(
            email=matched_client.email,
            phone=matched_client.phone,
        )

        self.client.force_login(self.accountant_user)

        invoice_response = self.client.get(reverse("staff_lead_create_invoice", args=[lead.id]))
        edit_response = self.client.get(
            reverse("staff_lead_update", args=[lead.id]),
            follow=True,
        )

        self.assertRedirects(
            invoice_response,
            reverse("invoice_create_from_client", args=[matched_client.id]),
            fetch_redirect_response=False,
        )
        self.assertRedirects(edit_response, reverse("staff_lead_list"))
        self.assertContains(edit_response, "You do not have permission to create or edit service requests.")

    def test_create_invoice_from_request_requires_client(self):
        self._enable_invoicing_for_business()
        lead = self._build_request_lead(
            email="invoice-needs-client@example.com",
            company_name="",
            street_address="",
        )

        self.client.force_login(self.user)

        response = self.client.get(
            reverse("staff_lead_create_invoice", args=[lead.id]),
            follow=True,
        )

        self.assertRedirects(response, reverse("staff_lead_convert_to_client", args=[lead.id]))
        self.assertContains(response, "Convert Service Request to Client")

    def test_service_request_detail_shows_matched_client_and_invoice_action(self):
        self._enable_invoicing_for_business()
        matched_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="detail-match@example.com",
            phone="+1 721 555 3233",
            company_name="Matched Detail Co",
            street_address="12 Main Street",
        )
        lead = self._build_request_lead(
            email=matched_client.email,
            phone=matched_client.phone,
        )

        self.client.force_login(self.accountant_user)

        response = self.client.get(reverse("staff_lead_detail", args=[lead.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("staff_client_detail", args=[matched_client.id]))
        self.assertContains(response, reverse("staff_lead_create_invoice", args=[lead.id]))

    def test_service_request_detail_shows_schedule_appointment_action_for_manage_roles(self):
        self._enable_appointments_for_business()
        matched_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="appointment-match@example.com",
            phone="+1 721 555 5252",
            company_name="Matched Appointment Co",
            street_address="12 Main Street",
        )
        lead = self._build_request_lead(
            email=matched_client.email,
            phone=matched_client.phone,
        )

        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("staff_lead_detail", args=[lead.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("appointment_create_from_request", args=[lead.id]))

    def test_service_request_detail_hides_schedule_appointment_action_for_accountant(self):
        self._enable_appointments_for_business()
        matched_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="accountant-appointment@example.com",
            phone="+1 721 555 5454",
            company_name="Accountant Match Co",
            street_address="12 Main Street",
        )
        lead = self._build_request_lead(
            email=matched_client.email,
            phone=matched_client.phone,
        )

        self.client.force_login(self.accountant_user)

        response = self.client.get(reverse("staff_lead_detail", args=[lead.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("appointment_create_from_request", args=[lead.id]))

    def test_service_request_detail_shows_linked_appointment_context(self):
        self._enable_appointments_for_business()
        matched_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="linked-appointment@example.com",
            phone="+1 721 555 5656",
            company_name="Linked Appointment Co",
            street_address="12 Main Street",
        )
        lead = self._build_request_lead(
            email=matched_client.email,
            phone=matched_client.phone,
        )
        start_time = timezone.now().replace(second=0, microsecond=0)
        appointment = Appointment.objects.create(
            business=self.business,
            client=matched_client,
            source_lead=lead,
            title="Linked request visit",
            start_time=start_time,
            end_time=start_time + timedelta(hours=1),
        )

        self.client.force_login(self.viewer_user)

        response = self.client.get(reverse("staff_lead_detail", args=[lead.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("appointment_detail", args=[appointment.id]))
        self.assertContains(response, "Latest linked appointment")

    def test_service_request_detail_hides_duplicate_schedule_button_when_appointment_exists(self):
        self._enable_appointments_for_business()
        matched_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="linked-no-duplicate@example.com",
            phone="+1 721 555 5757",
            company_name="Linked Request Co",
            street_address="12 Main Street",
        )
        lead = self._build_request_lead(
            email=matched_client.email,
            phone=matched_client.phone,
        )
        start_time = timezone.now().replace(second=0, microsecond=0)
        appointment = Appointment.objects.create(
            business=self.business,
            client=matched_client,
            source_lead=lead,
            title="Already scheduled visit",
            start_time=start_time,
            end_time=start_time + timedelta(hours=1),
        )

        self.client.force_login(self.user)

        response = self.client.get(reverse("staff_lead_detail", args=[lead.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("appointment_detail", args=[appointment.id]))
        self.assertNotContains(response, reverse("appointment_create_from_request", args=[lead.id]))

    def test_service_request_detail_shows_appointments_plan_message_when_unavailable(self):
        matched_client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="plan-locked-appointment@example.com",
            phone="+1 721 555 5858",
            company_name="Locked Appointment Co",
            street_address="12 Main Street",
        )
        lead = self._build_request_lead(
            email=matched_client.email,
            phone=matched_client.phone,
        )

        self.client.force_login(self.user)

        response = self.client.get(reverse("staff_lead_detail", args=[lead.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Appointments are not included in the current workspace plan.")
        self.assertNotContains(response, reverse("appointment_create_from_request", args=[lead.id]))

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

    def test_dashboard_shows_appointment_card_when_plan_allows_appointments(self):
        self._enable_appointments_for_business()
        client_record = Client.objects.create(
            business=self.business,
            first_name="Casey",
            last_name="Client",
            email="dashboard-appointment@example.com",
            phone="+1 721 555 6161",
            company_name="Dashboard Client Co",
            street_address="11 Main Street",
        )
        start_time = timezone.now().replace(second=0, microsecond=0)
        appointment = Appointment.objects.create(
            business=self.business,
            client=client_record,
            title="Dashboard upcoming visit",
            start_time=start_time + timedelta(hours=2),
            end_time=start_time + timedelta(hours=3),
            status=Appointment.Status.SCHEDULED,
        )

        self.client.force_login(self.viewer_user)

        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Today's Appointments")
        self.assertContains(response, "Dashboard upcoming visit")
        self.assertContains(response, reverse("appointment_detail", args=[appointment.id]))
        self.assertNotContains(response, reverse("appointment_create"))

    def test_dashboard_hides_appointment_card_when_plan_blocks_appointments(self):
        client_record = Client.objects.create(
            business=self.business,
            first_name="Casey",
            last_name="Client",
            email="dashboard-hidden@example.com",
            phone="+1 721 555 6262",
            company_name="Hidden Dashboard Co",
            street_address="11 Main Street",
        )
        start_time = timezone.now().replace(second=0, microsecond=0)
        Appointment.objects.create(
            business=self.business,
            client=client_record,
            title="Hidden dashboard visit",
            start_time=start_time + timedelta(hours=2),
            end_time=start_time + timedelta(hours=3),
            status=Appointment.Status.SCHEDULED,
        )

        self.client.force_login(self.user)

        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Today's Appointments")
        self.assertNotContains(response, "Hidden dashboard visit")

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
        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = plan
        subscription.save(update_fields=["plan", "updated_at"])

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
        subscription = BusinessSubscription.objects.get(business=self.business)
        subscription.plan = plan
        subscription.save(update_fields=["plan", "updated_at"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("invoice_list"))
        self.assertContains(response, "Invoices Locked")
        self.assertContains(response, "Billing Module")
        self.assertContains(response, "Locked")

    def test_viewer_cannot_open_client_create_page(self):
        self.client.force_login(self.viewer_user)

        response = self.client.get(reverse("staff_client_create"), follow=True)

        self.assertRedirects(response, reverse("staff_client_list"))
        self.assertContains(response, "You do not have permission to create or edit clients.")

    def test_accountant_can_open_client_create_page(self):
        self.client.force_login(self.accountant_user)

        response = self.client.get(reverse("staff_client_create"))

        self.assertEqual(response.status_code, 200)

    def test_accountant_cannot_open_lead_create_page(self):
        self.client.force_login(self.accountant_user)

        response = self.client.get(reverse("staff_lead_create"), follow=True)

        self.assertRedirects(response, reverse("staff_lead_list"))
        self.assertContains(response, "You do not have permission to create or edit service requests.")

    def test_viewer_client_list_hides_create_and_edit_actions(self):
        client_record = Client.objects.create(
            business=self.business,
            first_name="Casey",
            last_name="Viewer",
            email="casey-viewer@example.com",
            phone="+1 721 555 0100",
            company_name="Alpha Co",
            street_address="11 Main Street",
        )
        self.client.force_login(self.viewer_user)

        response = self.client.get(reverse("staff_client_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("staff_client_create"))
        self.assertNotContains(response, reverse("staff_client_update", args=[client_record.id]))

    def test_accountant_lead_list_hides_create_and_edit_actions(self):
        lead = Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            status=Lead.Status.NEW,
            first_name="Jordan",
            last_name="Lead",
            email="jordan-lead@example.com",
            phone="+1 721 555 8888",
            company_name="Lead Co",
        )
        self.client.force_login(self.accountant_user)

        response = self.client.get(reverse("staff_lead_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("staff_lead_create"))
        self.assertNotContains(response, reverse("staff_lead_update", args=[lead.id]))

    def test_accountant_cannot_open_service_management(self):
        self.client.force_login(self.accountant_user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.id
        session.save()

        response = self.client.get(reverse("business_service_list"), follow=True)

        self.assertRedirects(response, reverse("agent_dashboard"))
        self.assertContains(response, "You do not have permission to manage services or categories.")
