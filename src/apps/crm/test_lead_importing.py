from __future__ import annotations

import csv
import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .importing.jobs import create_import_job
from .importing.lead_preview import LeadPreviewStatus, persist_lead_preview
from .importing.leads import (
    LEAD_FORBIDDEN_FIELDS,
    LEAD_IMPORT_SCHEMA,
    LEAD_TEMPLATE_FIELDS,
    validate_lead_import,
)
from .importing.types import ImportType
from .models import Client, ImportJob, Lead, ServiceCategory


class LeadImportTestMixin:
    def setUp(self):
        self.business = Business.objects.create(
            name="Lead Import Workspace",
            slug="lead-import-workspace",
            country="Sint Maarten",
        )
        plan = ClarivoPlan.objects.create(name="Lead Plan", slug="lead-plan")
        BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.user = TaskIOUser.objects.create_user(
            email="lead-import-owner@example.com",
            password="testpass123",
        )
        BusinessUser.objects.create(
            business=self.business,
            user=self.user,
            role=BusinessUser.Role.OWNER,
        )
        self.base_row = {
            "lead_type": "REQUEST",
            "first_name": " Jamie ",
            "last_name": " Requester ",
            "email": "jamie@example.com",
            "phone": "+1 (721) 555-0100",
            "company_name": "Example Customer",
            "status": "NEW",
            "category": "",
            "street_address": "12 Example Street",
            "district": "SIMPSON_BAY",
            "country": "",
            "postal_code": "",
            "message": "Historical service request",
            "notes": "Imported from the previous CRM",
            "consent_to_contact": "",
        }

    def upload(self, rows, *, headers=LEAD_TEMPLATE_FIELDS, name="leads.csv"):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return SimpleUploadedFile(
            name,
            output.getvalue().encode("utf-8"),
            content_type="text/csv",
        )

    def preview(self, rows, *, headers=LEAD_TEMPLATE_FIELDS):
        validation = validate_lead_import(
            self.upload(rows, headers=headers),
            business=self.business,
        )
        job = create_import_job(
            business=self.business,
            actor=self.user,
            import_type=ImportType.LEADS,
            schema_version=LEAD_IMPORT_SCHEMA.version,
            parsed_file=validation.parsed_file,
        )
        preview = persist_lead_preview(
            validation,
            job=job,
            business=self.business,
            actor=self.user,
        )
        job.refresh_from_db()
        return job, preview

    def login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()


class LeadImportValidationTests(LeadImportTestMixin, TestCase):
    def test_schema_is_versioned_and_separates_server_fields(self):
        self.assertEqual(LEAD_IMPORT_SCHEMA.version, "1")
        self.assertEqual(LEAD_IMPORT_SCHEMA.allowed_columns, LEAD_TEMPLATE_FIELDS)
        self.assertIn("business_id", LEAD_FORBIDDEN_FIELDS)
        self.assertIn("requested_service", LEAD_FORBIDDEN_FIELDS)
        self.assertIn("preferred_start_time", LEAD_FORBIDDEN_FIELDS)
        self.assertIn("invoice_id", LEAD_FORBIDDEN_FIELDS)

    def test_request_and_interest_rows_validate_without_writes(self):
        rows = [
            self.base_row,
            {
                **self.base_row,
                "lead_type": "interest",
                "email": "interest@example.com",
                "phone": "+1 721 555 0101",
            },
        ]

        validation = validate_lead_import(self.upload(rows), business=self.business)

        self.assertFalse(validation.has_errors)
        self.assertEqual(
            [row.validated_row.lead_type for row in validation.row_results],
            [Lead.LeadType.REQUEST, Lead.LeadType.INTEREST],
        )
        self.assertFalse(Lead.objects.exists())

    def test_safe_statuses_are_accepted_and_invoiced_is_rejected(self):
        rows = [
            {**self.base_row, "status": "contacted"},
            {
                **self.base_row,
                "status": "CLOSED",
                "email": "closed@example.com",
                "phone": "+1 721 555 0102",
            },
            {
                **self.base_row,
                "status": "INVOICED",
                "email": "invoiced@example.com",
                "phone": "+1 721 555 0103",
            },
        ]

        validation = validate_lead_import(self.upload(rows), business=self.business)

        self.assertTrue(validation.row_results[0].is_valid)
        self.assertTrue(validation.row_results[1].is_valid)
        self.assertTrue(validation.row_results[2].has_errors)
        self.assertIn(
            "unsafe_invoiced_status",
            {issue.code for issue in validation.row_results[2].issues},
        )

    def test_required_values_and_strict_boolean_are_validated(self):
        validation = validate_lead_import(
            self.upload([{**self.base_row, "email": "", "consent_to_contact": "maybe"}]),
            business=self.business,
        )

        codes = {issue.code for issue in validation.row_results[0].issues}
        self.assertIn("required", codes)
        self.assertIn("invalid_boolean", codes)

    def test_defaults_use_workspace_country_and_do_not_manufacture_consent(self):
        validation = validate_lead_import(self.upload([self.base_row]), business=self.business)
        row = validation.row_results[0].validated_row

        self.assertEqual(row.country, "Sint Maarten")
        self.assertEqual(row.postal_code, "")
        self.assertFalse(row.consent_to_contact)

    def test_explicit_true_consent_and_category_label_are_normalized(self):
        category = ServiceCategory.objects.create(
            business=self.business,
            name="Maintenance",
        )
        validation = validate_lead_import(
            self.upload(
                [{**self.base_row, "category": "maintenance", "consent_to_contact": "YES"}]
            ),
            business=self.business,
        )
        row = validation.row_results[0].validated_row

        self.assertEqual(row.category_id, category.pk)
        self.assertEqual(row.category_label, "maintenance")
        self.assertTrue(row.consent_to_contact)

    def test_active_legacy_global_category_is_allowed(self):
        category = ServiceCategory.objects.create(name="Legacy Category")

        validation = validate_lead_import(
            self.upload([{**self.base_row, "category": "Legacy Category"}]),
            business=self.business,
        )

        self.assertEqual(validation.row_results[0].validated_row.category_id, category.pk)

    def test_ambiguous_category_requires_review_and_unknown_category_is_error(self):
        ServiceCategory.objects.create(business=self.business, name="Maintenance")
        ServiceCategory.objects.create(name="Maintenance")

        _job, ambiguous = self.preview([{**self.base_row, "category": "Maintenance"}])
        _job, unknown = self.preview([{**self.base_row, "category": "Not Available"}])

        self.assertEqual(ambiguous.rows[0].status, LeadPreviewStatus.REVIEW)
        self.assertFalse(ambiguous.ready)
        self.assertEqual(unknown.rows[0].status, LeadPreviewStatus.ERROR)
        self.assertFalse(unknown.ready)


class LeadImportPreviewTests(LeadImportTestMixin, TestCase):
    def test_new_row_is_ready_and_preview_is_read_only(self):
        job, preview = self.preview([self.base_row])

        self.assertTrue(preview.ready)
        self.assertEqual(preview.rows[0].status, LeadPreviewStatus.NEW)
        self.assertEqual(job.status, ImportJob.Status.READY)
        self.assertFalse(Lead.objects.exists())

    def test_exact_duplicate_in_upload_is_visible_and_skipped(self):
        _job, preview = self.preview([self.base_row, self.base_row])

        self.assertEqual(
            [row.status for row in preview.rows],
            [LeadPreviewStatus.NEW, LeadPreviewStatus.DUPLICATE],
        )
        self.assertEqual(preview.rows[1].duplicate_of_row, 2)
        self.assertEqual(preview.summary.ready_count, 1)
        self.assertTrue(preview.ready)

    def test_near_duplicate_in_upload_requires_review(self):
        second = {**self.base_row, "message": "Different history"}

        _job, preview = self.preview([self.base_row, second])

        self.assertEqual(preview.rows[1].status, LeadPreviewStatus.REVIEW)
        self.assertFalse(preview.ready)

    def test_same_business_existing_lead_requires_review(self):
        Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            first_name="Existing",
            last_name="Lead",
            email="jamie@example.com",
            phone="different",
            company_name="Existing",
        )

        _job, preview = self.preview([self.base_row])

        self.assertEqual(preview.rows[0].status, LeadPreviewStatus.REVIEW)
        self.assertFalse(preview.ready)

    def test_existing_client_is_warning_only_and_does_not_convert(self):
        client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="JAMIE@example.com",
            phone="different",
            company_name="Existing Client",
        )

        _job, preview = self.preview([self.base_row])

        self.assertEqual(preview.rows[0].status, LeadPreviewStatus.NEW)
        self.assertEqual(preview.rows[0].matching_client_ids, (client.pk,))
        self.assertTrue(preview.ready)
        self.assertEqual(Client.objects.count(), 1)

    def test_cross_business_lead_and_client_are_ignored(self):
        other = Business.objects.create(name="Other", slug="other-lead-import")
        Lead.objects.create(
            business=other,
            lead_type=Lead.LeadType.REQUEST,
            first_name="Foreign",
            last_name="Lead",
            email="jamie@example.com",
            phone=self.base_row["phone"],
            company_name="Foreign",
        )
        Client.objects.create(
            business=other,
            first_name="Foreign",
            last_name="Client",
            email="jamie@example.com",
            phone=self.base_row["phone"],
            company_name="Foreign",
        )

        _job, preview = self.preview([self.base_row])

        self.assertEqual(preview.rows[0].status, LeadPreviewStatus.NEW)
        self.assertFalse(preview.rows[0].matching_client_ids)

    def test_upload_preview_and_template_views_are_enabled(self):
        self.login()

        landing = self.client.get(reverse("data_import"))
        upload = self.client.get(reverse("lead_import_upload"))
        template = self.client.get(reverse("lead_import_template"))
        response = self.client.post(
            reverse("lead_import_upload"),
            {"csv_file": self.upload([self.base_row])},
        )

        self.assertContains(landing, "Upload Lead CSV")
        self.assertEqual(upload.status_code, 200)
        self.assertEqual(template.status_code, 200)
        self.assertEqual(template["Content-Type"], "text/csv")
        self.assertEqual(response.status_code, 302)
        job = ImportJob.objects.get()
        self.assertRedirects(response, reverse("lead_import_preview", args=[job.pk]))
        self.assertFalse(Lead.objects.exists())
