from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .importing.constants import CSVLimits
from .importing.jobs import (
    create_import_job,
    get_confirmable_import_job_for_owner,
    get_import_job_for_owner,
)
from .importing.parsing import parse_csv_upload
from .importing.permissions import check_import_capacity, user_can_import
from .importing.schemas import ImportSchema
from .importing.types import ImportType
from .models import ActivityLog, BusinessService, Client, ImportJob, Lead, ServiceCategory


class SharedCSVParserTests(TestCase):
    def setUp(self):
        self.schema = ImportSchema(
            import_type=ImportType.CLIENTS,
            version="1",
            required_columns=("name", "email"),
            optional_columns=("notes",),
            server_derived_fields=("business", "created_by"),
            defaults={"notes": ""},
        )

    def parse(self, content: bytes, *, name: str = "clients.csv", limits=None):
        upload = SimpleUploadedFile(name, content, content_type="text/csv")
        kwargs = {"limits": limits} if limits is not None else {}
        return parse_csv_upload(upload, self.schema, **kwargs)

    def issue_codes(self, result):
        return {issue.code for issue in result.issues}

    def test_valid_utf8_csv_is_normalized(self):
        result = self.parse(b" Name ,EMAIL,notes\nAlice,alice@example.com, Hello \n")

        self.assertFalse(result.has_errors)
        self.assertEqual(result.headers, ("name", "email", "notes"))
        self.assertEqual(result.rows[0].row_number, 2)
        self.assertEqual(
            result.rows[0].values,
            {"name": "Alice", "email": "alice@example.com", "notes": "Hello"},
        )

    def test_utf8_bom_csv_is_accepted(self):
        result = self.parse("name,email\nJosé,jose@example.com\n".encode("utf-8-sig"))

        self.assertFalse(result.has_errors)
        self.assertEqual(result.headers, ("name", "email"))
        self.assertEqual(result.rows[0].values["name"], "José")

    def test_empty_file_is_rejected(self):
        self.assertIn("empty_upload", self.issue_codes(self.parse(b"")))

    def test_header_only_file_is_rejected(self):
        self.assertIn("no_data_rows", self.issue_codes(self.parse(b"name,email\n")))

    def test_blank_rows_only_are_rejected(self):
        result = self.parse(b"name,email\n,\n  ,  \n")
        self.assertIn("no_data_rows", self.issue_codes(result))

    def test_file_with_only_blank_rows_has_no_header(self):
        result = self.parse(b"\n,\n  \n")
        self.assertIn("missing_header", self.issue_codes(result))

    def test_invalid_encoding_is_rejected(self):
        self.assertIn("invalid_encoding", self.issue_codes(self.parse(b"name,email\n\xff,x\n")))

    def test_non_csv_extension_is_rejected(self):
        result = self.parse(b"name,email\nAlice,a@example.com\n", name="clients.xlsx")
        self.assertIn("invalid_file_type", self.issue_codes(result))

    def test_missing_required_header_is_reported(self):
        result = self.parse(b"name\nAlice\n")
        self.assertIn("missing_required_header", self.issue_codes(result))

    def test_duplicate_normalized_headers_are_rejected(self):
        result = self.parse(b"name, Name ,email\nAlice,Other,a@example.com\n")
        self.assertIn("duplicate_header", self.issue_codes(result))

    def test_blank_header_is_rejected(self):
        result = self.parse(b"name,,email\nAlice,x,a@example.com\n")
        self.assertIn("blank_header", self.issue_codes(result))

    def test_unknown_header_is_rejected_for_strict_schema(self):
        result = self.parse(b"name,email,surprise\nAlice,a@example.com,x\n")
        self.assertIn("unexpected_header", self.issue_codes(result))

    def test_forbidden_tenant_header_is_rejected_explicitly(self):
        result = self.parse(b"name,email,business_id\nAlice,a@example.com,999\n")
        self.assertIn("forbidden_header", self.issue_codes(result))

    def test_too_many_rows_stops_at_limit(self):
        content = "name,email\n" + "".join(
            f"User {index},user{index}@example.com\n" for index in range(501)
        )
        result = self.parse(content.encode())

        self.assertIn("too_many_rows", self.issue_codes(result))
        self.assertEqual(len(result.rows), 500)

    def test_too_many_columns_is_rejected(self):
        schema = ImportSchema(
            import_type=ImportType.CLIENTS,
            version="1",
            required_columns=("name",),
            optional_columns=tuple(f"column_{index}" for index in range(50)),
        )
        headers = ",".join(schema.allowed_columns)
        values = ",".join("x" for _ in schema.allowed_columns)
        upload = SimpleUploadedFile("wide.csv", f"{headers}\n{values}\n".encode())

        result = parse_csv_upload(upload, schema)

        self.assertIn("too_many_columns", self.issue_codes(result))

    def test_cell_too_long_is_rejected(self):
        limits = CSVLimits(maximum_cell_characters=5)
        result = self.parse(b"name,email\nAlice,too-long\n", limits=limits)
        self.assertIn("cell_too_long", self.issue_codes(result))

    def test_too_many_row_values_are_rejected_without_discarding_extras(self):
        result = self.parse(b"name,email\nAlice,a@example.com,extra\n")
        self.assertIn("too_many_values", self.issue_codes(result))
        self.assertEqual(result.rows, ())

    def test_too_few_row_values_are_rejected(self):
        result = self.parse(b"name,email\nAlice\n")
        self.assertIn("too_few_values", self.issue_codes(result))
        self.assertEqual(result.rows, ())

    def test_malformed_csv_is_reported_without_exception_details(self):
        result = self.parse(b'name,email\n"Alice,a@example.com\n')
        self.assertIn("malformed_csv", self.issue_codes(result))
        self.assertNotIn("unexpected end", result.issues[0].message.lower())

    def test_upload_size_limit_is_enforced(self):
        limits = CSVLimits(maximum_upload_bytes=10)
        result = self.parse(b"name,email\nAlice,a@example.com\n", limits=limits)
        self.assertIn("file_too_large", self.issue_codes(result))

    def test_schema_rejects_tenant_columns_and_arbitrary_defaults(self):
        with self.assertRaises(ValueError):
            ImportSchema(
                import_type=ImportType.CLIENTS,
                version="1",
                required_columns=("name", "business"),
            )
        with self.assertRaises(ValueError):
            ImportSchema(
                import_type=ImportType.CLIENTS,
                version="1",
                required_columns=("name",),
                defaults={"unmapped_model_field": "unsafe"},
            )

    def test_parsing_has_no_business_data_or_email_side_effects(self):
        model_counts = {
            model: model.objects.count()
            for model in (
                Client,
                Lead,
                BusinessService,
                ServiceCategory,
                Appointment,
                Invoice,
                ActivityLog,
            )
        }
        mail_count = len(mail.outbox)

        result = self.parse(b"name,email\nAlice,alice@example.com\n")

        self.assertFalse(result.has_errors)
        for model, initial_count in model_counts.items():
            self.assertEqual(model.objects.count(), initial_count)
        self.assertEqual(len(mail.outbox), mail_count)


class ImportJobAndPermissionTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Alpha", slug="alpha-import")
        self.other_business = Business.objects.create(name="Bravo", slug="bravo-import")
        self.users = {}
        for role, _label in BusinessUser.Role.choices:
            user = TaskIOUser.objects.create_user(
                email=f"{role}@example.com",
                password="testpass123",
            )
            BusinessUser.objects.create(user=user, business=self.business, role=role)
            self.users[role] = user
        self.other_user = TaskIOUser.objects.create_user(
            email="other-owner@example.com", password="testpass123"
        )
        BusinessUser.objects.create(
            user=self.other_user,
            business=self.other_business,
            role=BusinessUser.Role.OWNER,
        )
        self.schema = ImportSchema(
            import_type=ImportType.CLIENTS,
            version="1",
            required_columns=("name",),
        )
        self.parsed_file = parse_csv_upload(
            SimpleUploadedFile("clients.csv", b"name\nAlice\n"), self.schema
        )

    def create_job(self, **overrides):
        kwargs = {
            "business": self.business,
            "actor": self.users[BusinessUser.Role.OWNER],
            "import_type": ImportType.CLIENTS,
            "schema_version": "1",
            "parsed_file": self.parsed_file,
        }
        kwargs.update(overrides)
        return create_import_job(**kwargs)

    def test_job_is_bound_to_business_creator_and_digest(self):
        job = self.create_job()

        self.assertEqual(job.business, self.business)
        self.assertEqual(job.created_by, self.users[BusinessUser.Role.OWNER])
        self.assertEqual(job.file_digest, self.parsed_file.file_digest)
        self.assertEqual(job.rows_detected, 1)
        self.assertEqual(job.status, ImportJob.Status.UPLOADED)

    def test_cross_business_access_is_denied(self):
        job = self.create_job()
        with self.assertRaises(PermissionDenied):
            get_import_job_for_owner(
                job_id=job.pk,
                business=self.other_business,
                actor=self.users[BusinessUser.Role.OWNER],
            )

    def test_same_business_different_user_cannot_access_job(self):
        job = self.create_job()
        with self.assertRaises(PermissionDenied):
            get_confirmable_import_job_for_owner(
                job_id=job.pk,
                business=self.business,
                actor=self.users[BusinessUser.Role.ADMIN],
            )

    def test_expired_job_is_rejected(self):
        job = self.create_job(lifetime=timedelta(seconds=-1))
        with self.assertRaisesMessage(ValidationError, "expired"):
            get_import_job_for_owner(
                job_id=job.pk,
                business=self.business,
                actor=self.users[BusinessUser.Role.OWNER],
            )

    def test_status_transitions_are_explicit_and_terminal(self):
        job = self.create_job()
        job.transition_to(ImportJob.Status.VALIDATED)
        job.transition_to(ImportJob.Status.READY)
        job.transition_to(ImportJob.Status.COMPLETED)

        self.assertIsNotNone(job.completed_at)
        with self.assertRaises(ValidationError):
            job.transition_to(ImportJob.Status.READY)

        other_job = self.create_job()
        with self.assertRaises(ValidationError):
            other_job.transition_to(ImportJob.Status.COMPLETED)

    def test_only_ready_job_is_confirmable(self):
        job = self.create_job()
        with self.assertRaisesMessage(ValidationError, "not ready"):
            get_confirmable_import_job_for_owner(
                job_id=job.pk,
                business=self.business,
                actor=self.users[BusinessUser.Role.OWNER],
            )

        job.transition_to(ImportJob.Status.VALIDATED)
        job.transition_to(ImportJob.Status.READY)
        self.assertEqual(
            get_confirmable_import_job_for_owner(
                job_id=job.pk,
                business=self.business,
                actor=self.users[BusinessUser.Role.OWNER],
            ),
            job,
        )

    def test_client_import_role_matrix(self):
        allowed = {
            BusinessUser.Role.OWNER,
            BusinessUser.Role.ADMIN,
            BusinessUser.Role.STAFF,
            BusinessUser.Role.ACCOUNTANT,
        }
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.assertEqual(
                    user_can_import(self.business, user, ImportType.CLIENTS), role in allowed
                )

    def test_lead_import_role_matrix(self):
        allowed = {BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN, BusinessUser.Role.STAFF}
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.assertEqual(
                    user_can_import(self.business, user, ImportType.LEADS), role in allowed
                )

    def test_service_import_role_matrix(self):
        allowed = {BusinessUser.Role.OWNER, BusinessUser.Role.ADMIN}
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.assertEqual(
                    user_can_import(self.business, user, ImportType.SERVICES), role in allowed
                )

    def test_membership_in_another_business_does_not_grant_access(self):
        self.assertFalse(user_can_import(self.business, self.other_user, ImportType.CLIENTS))

    def test_capacity_without_entity_policy_does_not_grant_access(self):
        decision = check_import_capacity(
            business=self.business,
            import_type=ImportType.CLIENTS,
            requested_rows=1,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "capacity_check_not_configured")


class DataImportLandingPageTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Landing Workspace",
            slug="landing-workspace",
            tax_rate=Decimal("6.50"),
        )
        plan = ClarivoPlan.objects.create(name="Import CRM", slug="import-crm")
        BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )

    def make_user(self, role):
        user = TaskIOUser.objects.create_user(
            email=f"landing-{role}@example.com", password="testpass123"
        )
        BusinessUser.objects.create(user=user, business=self.business, role=role)
        return user

    def login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    def test_owner_sees_shell_and_existing_service_link_only(self):
        self.login(self.make_user(BusinessUser.Role.OWNER))

        response = self.client.get(reverse("data_import"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import Clients")
        self.assertContains(response, "Coming next")
        self.assertContains(response, "Import Leads")
        self.assertContains(response, reverse("business_service_import"))
        self.assertNotContains(response, "client-import")
        self.assertNotContains(response, "lead-import")

    def test_accountant_sees_client_only_and_not_service_or_lead(self):
        self.login(self.make_user(BusinessUser.Role.ACCOUNTANT))

        response = self.client.get(reverse("data_import"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Import Clients")
        self.assertNotContains(response, "Import Leads")
        self.assertNotContains(response, "Import Services")

    def test_viewer_is_denied_landing_page(self):
        self.login(self.make_user(BusinessUser.Role.VIEWER))

        response = self.client.get(reverse("data_import"))

        self.assertRedirects(response, reverse("agent_dashboard"))


class ExistingServiceImportCharacterizationTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Service Import Compatibility",
            slug="service-import-compatibility",
            tax_rate=Decimal("7.50"),
        )
        plan = ClarivoPlan.objects.create(name="Service CRM", slug="service-crm")
        BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.user = TaskIOUser.objects.create_user(
            email="service-import-owner@example.com", password="testpass123"
        )
        BusinessUser.objects.create(
            user=self.user,
            business=self.business,
            role=BusinessUser.Role.OWNER,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()

    def upload(self, content: bytes):
        return self.client.post(
            reverse("business_service_import"),
            {"csv_file": SimpleUploadedFile("services.csv", content, content_type="text/csv")},
            follow=True,
        )

    def test_existing_import_accepts_bom_case_and_whitespace_in_headers(self):
        response = self.upload(
            " Name ,UNIT_PRICE,external_code,is_active\nBOM Service,12.50,BOM-1,no\n".encode(
                "utf-8-sig"
            )
        )

        self.assertRedirects(response, reverse("business_service_list"))
        service = BusinessService.objects.get(external_code="BOM-1")
        self.assertEqual(service.unit_price, Decimal("12.50"))
        self.assertFalse(service.is_active)

    def test_existing_import_requires_name_and_unit_price_headers(self):
        response = self.upload(b"name,external_code\nMissing Price,NO-PRICE\n")

        self.assertContains(response, "Missing required CSV columns: unit_price.")
        self.assertFalse(BusinessService.objects.exists())

    def test_existing_import_rolls_back_services_and_categories_on_late_error(self):
        response = self.upload(
            b"name,unit_price,category,external_code\n"
            b"Valid First,10.00,Temporary Category,VALID-1\n"
            b"Invalid Second,not-a-decimal,,INVALID-2\n"
        )

        self.assertContains(response, "unit_price must be a valid decimal number")
        self.assertFalse(BusinessService.objects.exists())
        self.assertFalse(ServiceCategory.objects.exists())
