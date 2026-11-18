"""Services Clients integration contracts, verified disposable PostgreSQL only."""

from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.test_service_allowances import ServicesFixture
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY
from apps.crm.forms import PrivateClientForm
from apps.crm.models import Client
from apps.crm.test_services_dashboard_ui import assert_disposable


class FormFields(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.names = []
        self.ids = set()
        self.labels = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and "data-client-form" in attrs:
            self.inside = True
        if not self.inside:
            return
        if tag in {"input", "select", "textarea"} and attrs.get("type") != "hidden":
            self.names.append(attrs.get("name"))
            self.ids.add(attrs.get("id"))
        if tag == "label":
            self.labels.add(attrs.get("for"))

    def handle_endtag(self, tag):
        if tag == "form":
            self.inside = False


class ServicesClientsPresentationTests(ServicesFixture, TestCase):
    def setUp(self):
        assert_disposable()
        super().setUp()
        self.login()
        self.create_url = reverse("staff_client_create")
        self.detail_url = reverse("staff_client_detail", args=[self.customer.pk])
        self.edit_url = reverse("staff_client_update", args=[self.customer.pk])

    def values(self, **overrides):
        values = {
            "client_type": "BUSINESS",
            "first_name": "Created",
            "last_name": "Client",
            "company_name": "Created Client Co",
            "email": "new-client@example.test",
            "phone": "+1 721 555 0199",
            "street_address": "12 New Street",
            "country": "Sint Maarten",
            "district": "PHILIPSBURG",
            "postal_code": "",
            "preferred_contact_method": "EMAIL",
            "client_status": "ACTIVE",
            "priority": "MEDIUM",
            "consent_to_contact": "on",
            "business_legal_name": "Created Client Legal",
            "trade_name": "Trade name",
            "industry": "Hospitality",
            "website": "https://example.test",
            "registration_number": "SYNTH-001",
            "business_description": "All supplied details retained.",
            "job_title": "Coordinator",
            "department": "Operations",
            "secondary_email": "secondary@example.test",
            "secondary_phone": "555 0100",
            "whatsapp_number": "555 0101",
            "preferred_language": "English",
            "lead_source": "REFERRAL",
            "assigned_to": str(self.owner.pk),
            "interested_services": "Maintenance",
            "message": "Original request",
            "communication_notes": "Email estimates",
            "notes": "Preserve this draft note.",
        }
        return {**values, **overrides}

    def test_full_create_and_edit_render_every_real_field_with_an_associated_label(self):
        expected = set(PrivateClientForm(business=self.business).fields)
        for url in [self.create_url, self.edit_url]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                parser = FormFields()
                parser.feed(response.content.decode())
                self.assertEqual(set(parser.names), expected)
                self.assertEqual(len(parser.names), 32)
                self.assertTrue(parser.ids <= parser.labels)
                self.assertNotIn("is_active", parser.names)
                self.assertContains(response, 'data-services-clients="form"')
                self.assertContains(response, "client-create-address-data")

    def test_create_and_edit_post_all_values_and_keep_existing_returns(self):
        response = self.client.post(self.create_url, self.values())
        self.assertRedirects(response, reverse("staff_client_list"))
        customer = Client.objects.get(email="new-client@example.test")
        self.assertEqual(customer.business, self.business)
        self.assertEqual(customer.notes, "Preserve this draft note.")
        self.assertEqual(customer.registration_number, "SYNTH-001")
        invoice = Invoice.objects.create(
            business=self.business, client=customer, invoice_number="KEEP-001"
        )
        appointment = self.appointment(client=customer)
        edit = reverse("staff_client_update", args=[customer.pk])
        response = self.client.post(
            edit, self.values(notes="Updated notes", client_status="PROSPECT")
        )
        self.assertRedirects(response, reverse("staff_client_detail", args=[customer.pk]))
        customer.refresh_from_db()
        self.assertEqual(customer.notes, "Updated notes")
        self.assertEqual(customer.client_status, "PROSPECT")
        self.assertTrue(customer.is_active)
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk, client=customer).exists())
        self.assertTrue(Appointment.objects.filter(pk=appointment.pk, client=customer).exists())

    def test_server_errors_retain_optional_draft_and_expose_linked_errors(self):
        response = self.client.post(
            self.create_url, self.values(email="invalid", street_address="")
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "email", "Enter a valid email address.")
        self.assertContains(response, "Preserve this draft note.")
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'id="id_email_errors"')
        self.assertContains(response, 'href="#id_email"')
        self.assertContains(response, "Client was not saved. Please correct the following:")
        self.assertFalse(Client.objects.filter(email="invalid").exists())

    def test_individual_still_requires_company_and_create_country_rules_are_authoritative(self):
        response = self.client.post(
            self.create_url, self.values(client_type="INDIVIDUAL", company_name="")
        )
        self.assertFormError(response.context["form"], "company_name", "This field is required.")
        response = self.client.post(
            self.create_url,
            self.values(country="Netherlands", district="Amsterdam", postal_code="1012ab"),
        )
        self.assertEqual(response.status_code, 302)
        customer = Client.objects.get(email="new-client@example.test")
        self.assertEqual(customer.country, "Netherlands")
        self.assertEqual(customer.district, "Amsterdam")
        self.assertEqual(customer.postal_code, "1012 AB")

    def test_cross_tenant_assignee_and_client_remain_unavailable(self):
        other = Business.objects.create(name="Foreign", slug="foreign-clients-ui")
        BusinessSubscription.objects.create(
            business=other, plan=self.plan, status="active", payment_provider="local"
        )
        outsider = self.user()
        BusinessUser.objects.create(business=other, user=outsider, role="owner")
        response = self.client.post(self.create_url, self.values(assigned_to=outsider.pk))
        self.assertIn("assigned_to", response.context["form"].errors)
        self.assertFalse(Client.objects.filter(email="new-client@example.test").exists())
        foreign = Client.objects.create(business=other, first_name="Foreign", last_name="Customer")
        self.assertEqual(
            self.client.get(reverse("staff_client_detail", args=[foreign.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.post(reverse("staff_client_archive", args=[foreign.pk])).status_code, 404
        )

    def test_role_actions_and_invoice_reads_match_existing_permissions(self):
        invoice = Invoice.objects.create(
            business=self.business, client=self.customer, invoice_number="ROLE-001"
        )
        for role in ["owner", "admin", "staff", "accountant", "viewer"]:
            with self.subTest(role=role):
                self.member.role = role
                self.member.save(update_fields=["role"])
                page = self.client.get(self.detail_url)
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, reverse("invoice_detail", args=[invoice.pk]))
                self.assertEqual(
                    b"data-client-archive>" in page.content, role in {"owner", "admin"}
                )
                self.assertEqual(
                    reverse("staff_client_update", args=[self.customer.pk])
                    in page.content.decode(),
                    role != "viewer",
                )
                self.assertEqual(
                    reverse("appointment_create") + "?client_id=" in page.content.decode(),
                    role in {"owner", "admin", "staff"},
                )
        response = self.client.post(self.create_url, self.values())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Client.objects.filter(email="new-client@example.test").exists())

    def test_capacity_denial_is_still_server_enforced(self):
        self.limit(max_clients=1)
        before = Client.objects.count()
        response = self.client.post(self.create_url, self.values())
        self.assertRedirects(response, reverse("staff_client_list"))
        self.assertEqual(Client.objects.count(), before)

    def test_archive_keeps_related_records_and_existing_classification_rule(self):
        invoice = Invoice.objects.create(
            business=self.business, client=self.customer, invoice_number="ARCHIVE-001"
        )
        appointment = self.appointment()
        response = self.client.post(reverse("staff_client_archive", args=[self.customer.pk]))
        self.assertRedirects(response, reverse("staff_client_list"))
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertEqual(self.customer.client_status, "INACTIVE")
        self.assertTrue(Invoice.objects.filter(pk=invoice.pk).exists())
        self.assertTrue(Appointment.objects.filter(pk=appointment.pk).exists())

    def test_financial_review_and_pagination_reuse_existing_partial(self):
        for i in range(8):
            Invoice.objects.create(
                business=self.business,
                client=self.customer,
                invoice_number=f"REVIEW-{i}",
                status="PAID",
                total="240.00",
                subtotal="240.00",
            )
        first = self.client.get(self.detail_url)
        self.assertTemplateUsed(first, "crm/main/client_invoice.html")
        self.assertContains(first, "Unverified — review required")
        self.assertEqual(len(first.context["client_invoices"]), 6)
        second = self.client.get(self.detail_url, {"invoice_page": 2})
        self.assertEqual(len(second.context["client_invoices"]), 2)

    def test_existing_secondary_contact_and_website_links_remain_available(self):
        self.customer.website = "https://example.test"
        self.customer.secondary_email = "office@example.test"
        self.customer.secondary_phone = "+17215550180"
        self.customer.whatsapp_number = "17215550181"
        self.customer.save()
        response = self.client.get(self.detail_url)
        for href in [
            "https://example.test",
            "mailto:office@example.test",
            "tel:+17215550180",
            "https://wa.me/17215550181",
        ]:
            self.assertContains(response, 'href="' + href + '"')

    def test_disabled_related_modules_remove_data_sections(self):
        self.limit(allow_invoicing=False, allow_appointments=False)
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, 'id="client-invoices"')
        self.assertNotContains(response, 'id="client-appointments"')
        self.assertNotContains(
            response, reverse("invoice_create_from_client", args=[self.customer.pk])
        )

    def test_legacy_all_clients_route_stays_on_original_multi_client_composition(self):
        response = self.client.get(reverse("client_detail_view"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-services-clients="detail"')
        self.assertNotContains(response, 'id="client-invoices"')

    def test_logistics_branches_keep_original_templates_and_no_clients_assets(self):
        business = Business.objects.create(
            name="Logistics regression", slug="clients-logistics-ui", vertical="LOGISTICS"
        )
        logistics_plan = ClarivoPlan.objects.get(slug="logistics")
        logistics_plan.is_active = True
        logistics_plan.save(update_fields=["is_active"])
        BusinessSubscription.objects.create(
            business=business,
            plan=logistics_plan,
            status="active",
            billing_interval="yearly",
        )
        BusinessUser.objects.create(business=business, user=self.owner, role="owner")
        customer = Client.objects.create(
            business=business,
            first_name="Logistics",
            last_name="Customer",
            street_address="12 Port Street",
        )
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = business.pk
        session.save()
        for url in [
            reverse("staff_client_list"),
            reverse("staff_client_detail", args=[customer.pk]),
            reverse("staff_client_create"),
            reverse("staff_client_update", args=[customer.pk]),
            reverse("client_import_upload"),
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "services-clients.css")
                self.assertNotContains(response, "services-clients.js")
                self.assertNotContains(response, "data-services-clients=")

    def test_csv_upload_keeps_optional_fields_and_server_upload_errors(self):
        url = reverse("client_import_upload")
        response = self.client.get(url)
        self.assertContains(response, "All fields are optional")
        self.assertContains(response, 'name="csv_file"')
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Choose a CSV file to preview.", status_code=400)

    def test_inline_modal_preserves_endpoint_prefixes_and_parent_draft_hooks(self):
        for route in ["appointment_create", "staff_lead_create"]:
            response = self.client.get(reverse(route))
            self.assertContains(response, "mm-services-clients-inline")
            self.assertContains(response, reverse("staff_client_quick_create"))
            self.assertContains(response, "data-draft-client-form")
            for name in [
                "first_name",
                "last_name",
                "email",
                "phone",
                "company_name",
                "street_address",
            ]:
                self.assertContains(response, f'name="new_client-{name}"')
