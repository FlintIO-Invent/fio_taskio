from __future__ import annotations

import csv
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .importing.clients import CLIENT_STANDARD_TEMPLATE_FIELDS
from .importing.constants import DEFAULT_CSV_LIMITS
from .importing.leads import LEAD_TEMPLATE_FIELDS
from .importing.services import SERVICE_TEMPLATE_FIELDS
from .models import BusinessService, Client, ImportJob, Lead


class ImportUXTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Import UX Workspace",
            slug="import-ux-workspace",
            country="Sint Maarten",
            tax_rate=Decimal("7.50"),
        )
        plan = ClarivoPlan.objects.create(
            name="Import UX Plan",
            slug="import-ux-plan",
            max_clients=50,
        )
        BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.owner = self.make_user("owner", BusinessUser.Role.OWNER)
        self.login(self.owner)

    def make_user(self, label: str, role: str):
        user = TaskIOUser.objects.create_user(
            email=f"import-ux-{label}@example.com",
            password="testpass123",
        )
        BusinessUser.objects.create(
            business=self.business,
            user=user,
            role=role,
        )
        return user

    def login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    @staticmethod
    def upload(name: str, content: str) -> SimpleUploadedFile:
        return SimpleUploadedFile(name, content.encode(), content_type="text/csv")

    def post_csv(self, route_name: str, name: str, content: str):
        return self.client.post(
            reverse(route_name),
            {"csv_file": self.upload(name, content)},
            follow=True,
        )

    def test_landing_explains_process_migration_and_role_appropriate_cards(self):
        response = self.client.get(reverse("data_import"))

        self.assertEqual(response.status_code, 200)
        for text in (
            "Download template",
            "Add or export your data",
            "Upload CSV",
            "Review MotionMate's interpretation",
            "Confirm import",
            "Moving from another system?",
            "Clients",
            "Services",
            "Leads",
            "Import History",
        ):
            self.assertContains(response, text)
        for route_name in (
            "client_import_upload",
            "client_import_template",
            "business_service_import",
            "business_service_sample_csv",
            "lead_import_upload",
            "lead_import_template",
            "import_history",
        ):
            self.assertContains(response, reverse(route_name))

    def test_upload_pages_show_shared_limits_templates_and_no_save_guidance(self):
        pages = (
            ("client_import_upload", "client_import_template"),
            ("business_service_import", "business_service_sample_csv"),
            ("lead_import_upload", "lead_import_template"),
        )
        for route_name, template_route_name in pages:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "CSV only")
                self.assertContains(
                    response,
                    f"{DEFAULT_CSV_LIMITS.maximum_upload_bytes // (1024 * 1024)} MB",
                )
                self.assertContains(response, f"{DEFAULT_CSV_LIMITS.maximum_data_rows} data rows")
                self.assertContains(response, "Nothing is saved before you confirm")
                self.assertContains(response, reverse(template_route_name))
        self.assertFalse(ImportJob.objects.exists())
        self.assertFalse(Client.objects.exists())
        self.assertFalse(Lead.objects.exists())
        self.assertFalse(BusinessService.objects.exists())

    def test_template_downloads_use_current_schema_and_fictional_examples(self):
        downloads = (
            (
                "client_import_template",
                CLIENT_STANDARD_TEMPLATE_FIELDS,
                "motionmate_clients_v1.csv",
                "jane@example.com",
            ),
            (
                "business_service_sample_csv",
                SERVICE_TEMPLATE_FIELDS,
                "motionmate_services_v1.csv",
                "Emergency Callout",
            ),
            (
                "lead_import_template",
                LEAD_TEMPLATE_FIELDS,
                "motionmate_leads_v1.csv",
                "jamie@example.com",
            ),
        )
        for route_name, expected_headers, filename, example in downloads:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                rows = list(csv.reader(response.content.decode().splitlines()))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(tuple(rows[0]), expected_headers)
                self.assertIn(filename, response["Content-Disposition"])
                self.assertContains(response, example)
                self.assertGreaterEqual(len(rows), 2)

    def test_client_preview_uses_accessible_states_and_confirmation_counts(self):
        row = "Jane,Doe,jane@example.com,+1 721 555 0100,Example Co,12 Example Street"
        response = self.post_csv(
            "client_import_upload",
            "clients.csv",
            f"first_name,last_name,email,phone,company_name,street_address\n{row}\n{row}\n",
        )

        self.assertContains(response, "Ready to confirm")
        self.assertContains(response, "Row status: </span>Create")
        self.assertContains(response, "Row status: </span>Duplicate")
        self.assertContains(response, "1</strong> clients will be created")
        self.assertContains(response, "1</strong> duplicates will be skipped")
        self.assertContains(response, "Import rows cannot be edited in the browser")

    def test_lead_preview_uses_accessible_states_and_confirmation_counts(self):
        row = "REQUEST,Jamie,Requester,jamie@example.com,+1 721 555 0100,Example Co"
        response = self.post_csv(
            "lead_import_upload",
            "leads.csv",
            f"lead_type,first_name,last_name,email,phone,company_name\n{row}\n{row}\n",
        )

        self.assertContains(response, "Ready to confirm")
        self.assertContains(response, "Row status: </span>Create")
        self.assertContains(response, "Row status: </span>Duplicate")
        self.assertContains(response, "1</strong> leads will be created")
        self.assertContains(response, "1</strong> duplicates will be skipped")

    def test_service_preview_shows_create_update_and_confirmation_counts(self):
        BusinessService.objects.create(
            business=self.business,
            name="Existing Service",
            external_code="SVC-1",
            unit_price=Decimal("10.00"),
            tax_rate=Decimal("7.50"),
        )
        response = self.post_csv(
            "business_service_import",
            "services.csv",
            "name,unit_price,external_code\n"
            "New Service,25.00,SVC-2\n"
            "Existing Service,15.00,SVC-1\n",
        )

        self.assertContains(response, "Ready to confirm")
        self.assertContains(response, "Row status: </span>Create")
        self.assertContains(response, "Row status: </span>Update")
        self.assertContains(response, "1</strong> services will be created")
        self.assertContains(response, "1</strong> services will be updated")

    def test_blocking_file_error_explains_how_to_recover_without_writes(self):
        response = self.post_csv(
            "client_import_upload",
            "clients.csv",
            "first_name,last_name\nJane,Doe\n",
        )

        self.assertContains(response, "This import cannot continue yet")
        self.assertContains(response, "Blocking file issues")
        self.assertContains(response, "Download the current template")
        self.assertContains(response, "Upload a revised CSV")
        self.assertFalse(Client.objects.exists())

    def test_completed_results_offer_consistent_next_actions(self):
        flows = (
            (
                "client_import_upload",
                "client_import_execute",
                "clients.csv",
                "first_name,last_name,email,phone,company_name,street_address\n"
                "Alex,Client,alex@example.com,+1 721 555 0101,Example Co,1 Main Street\n",
                "View Clients",
            ),
            (
                "business_service_import",
                "business_service_import_execute",
                "services.csv",
                "name,unit_price,external_code\nResult Service,40.00,RESULT-1\n",
                "View Services",
            ),
            (
                "lead_import_upload",
                "lead_import_execute",
                "leads.csv",
                "lead_type,first_name,last_name,email,phone,company_name\n"
                "INTEREST,Alex,Lead,alex-lead@example.com,+1 721 555 0102,Example Co\n",
                "View Leads",
            ),
        )
        for upload_route, execute_route, filename, content, entity_action in flows:
            with self.subTest(upload_route=upload_route):
                self.post_csv(upload_route, filename, content)
                job = ImportJob.objects.order_by("-created_at", "-pk").first()
                response = self.client.post(
                    reverse(execute_route, args=[job.pk]),
                    follow=True,
                )
                self.assertContains(response, "Import complete")
                self.assertContains(response, "Total processed")
                self.assertContains(response, entity_action)
                self.assertContains(response, "Import More Data")
                self.assertContains(response, "View Import History")
                history_response = self.client.get(reverse("import_history"))
                self.assertContains(history_response, filename)
                self.assertContains(history_response, "Completed")

    def test_expired_result_gives_safe_recovery_action(self):
        self.post_csv(
            "client_import_upload",
            "clients.csv",
            "first_name,last_name,email,phone,company_name,street_address\n"
            "Expired,Client,expired@example.com,+1 721 555 0103,Example Co,1 Main Street\n",
        )
        job = ImportJob.objects.get()
        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["expires_at"])

        response = self.client.post(
            reverse("client_import_execute", args=[job.pk]),
            follow=True,
        )

        self.assertContains(response, "Import not completed")
        self.assertContains(response, "preview can no longer be used")
        self.assertContains(response, "Create a New Preview")
        self.assertFalse(Client.objects.exists())

    def test_navigation_links_follow_existing_import_role_matrix(self):
        owner_client_page = self.client.get(reverse("staff_client_list"))
        owner_lead_page = self.client.get(reverse("staff_lead_list"))
        self.assertContains(owner_client_page, reverse("data_import"))
        self.assertContains(owner_client_page, reverse("client_import_upload"))
        self.assertContains(owner_lead_page, reverse("lead_import_upload"))

        accountant = self.make_user("accountant", BusinessUser.Role.ACCOUNTANT)
        self.login(accountant)
        accountant_page = self.client.get(reverse("staff_client_list"))
        self.assertContains(accountant_page, reverse("data_import"))
        self.assertContains(accountant_page, reverse("client_import_upload"))
        self.assertNotContains(accountant_page, reverse("lead_import_upload"))

        viewer = self.make_user("viewer", BusinessUser.Role.VIEWER)
        self.login(viewer)
        viewer_page = self.client.get(reverse("staff_client_list"))
        self.assertNotContains(viewer_page, reverse("data_import"))
        self.assertNotContains(viewer_page, reverse("client_import_upload"))
        self.assertNotContains(viewer_page, reverse("lead_import_upload"))

    def test_every_import_route_requires_authentication_and_active_membership(self):
        job_id = uuid.uuid4()
        get_routes = (
            reverse("data_import"),
            reverse("import_history"),
            reverse("import_history_detail", args=[job_id]),
            reverse("client_import_upload"),
            reverse("client_import_template"),
            reverse("client_import_preview", args=[job_id]),
            reverse("client_import_result", args=[job_id]),
            reverse("lead_import_upload"),
            reverse("lead_import_template"),
            reverse("lead_import_preview", args=[job_id]),
            reverse("lead_import_result", args=[job_id]),
            reverse("business_service_import"),
            reverse("business_service_sample_csv"),
            reverse("business_service_import_preview", args=[job_id]),
            reverse("business_service_import_result", args=[job_id]),
        )
        post_routes = (
            reverse("client_import_execute", args=[job_id]),
            reverse("lead_import_execute", args=[job_id]),
            reverse("business_service_import_execute", args=[job_id]),
        )

        self.client.logout()
        for url in get_routes:
            with self.subTest(access="anonymous-get", url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("business_login"), response.url)
        for url in post_routes:
            with self.subTest(access="anonymous-post", url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("business_login"), response.url)

        self.login(self.owner)
        membership = BusinessUser.objects.get(business=self.business, user=self.owner)
        membership.is_active = False
        membership.save(update_fields=["is_active"])
        for url in get_routes:
            with self.subTest(access="revoked-get", url=url):
                self.assertRedirects(self.client.get(url), reverse("business_setup"))
        for url in post_routes:
            with self.subTest(access="revoked-post", url=url):
                self.assertRedirects(self.client.post(url), reverse("business_setup"))

        self.assertFalse(ImportJob.objects.exists())
