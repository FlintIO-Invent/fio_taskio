from __future__ import annotations

import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .importing.jobs import create_import_job
from .importing.service_preview import ServicePreviewStatus, persist_service_preview
from .importing.services import (
    SERVICE_IMPORT_SCHEMA,
    SERVICE_TEMPLATE_FIELDS,
    validate_service_import,
)
from .importing.types import ImportType
from .models import BusinessService, ImportJob, ServiceCategory


class ServiceImportTestMixin:
    def setUp(self):
        self.business = Business.objects.create(
            name="Service Import Workspace",
            slug="service-import-workspace",
            country="Sint Maarten",
            tax_rate=Decimal("7.50"),
        )
        plan = ClarivoPlan.objects.create(name="Service Plan", slug="service-plan")
        BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.user = TaskIOUser.objects.create_user(
            email="service-preview-owner@example.com",
            password="testpass123",
        )
        BusinessUser.objects.create(
            business=self.business,
            user=self.user,
            role=BusinessUser.Role.OWNER,
        )
        self.base_row = {
            "name": "Emergency Callout",
            "unit_price": "125.00",
            "description": "After-hours callout",
            "tax_rate": "",
            "category": "Urgent Response",
            "is_active": "true",
            "external_code": "EMERGENCY-001",
            "is_bookable_online": "true",
            "default_duration_minutes": "60",
            "booking_buffer_minutes": "15",
            "public_description": "Public callout",
            "requires_manual_confirmation": "true",
        }

    def upload(self, rows, *, headers=SERVICE_TEMPLATE_FIELDS, name="services.csv"):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return SimpleUploadedFile(
            name,
            output.getvalue().encode("utf-8"),
            content_type="text/csv",
        )

    def preview(self, rows, *, headers=SERVICE_TEMPLATE_FIELDS):
        upload = self.upload(rows, headers=headers)
        validation = validate_service_import(upload, business=self.business)
        job = create_import_job(
            business=self.business,
            actor=self.user,
            import_type=ImportType.SERVICES,
            schema_version=SERVICE_IMPORT_SCHEMA.version,
            parsed_file=validation.parsed_file,
        )
        preview = persist_service_preview(
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


class ServiceImportValidationPreviewTests(ServiceImportTestMixin, TestCase):
    def test_schema_is_versioned_and_uses_all_existing_columns(self):
        self.assertEqual(SERVICE_IMPORT_SCHEMA.version, "1")
        self.assertEqual(SERVICE_IMPORT_SCHEMA.allowed_columns, SERVICE_TEMPLATE_FIELDS)

    def test_create_preview_is_read_only_and_proposes_category(self):
        job, preview = self.preview([self.base_row])

        self.assertEqual(preview.rows[0].status, ServicePreviewStatus.CREATE)
        self.assertTrue(preview.rows[0].category["will_create"])
        self.assertEqual(preview.summary.categories_to_create, 1)
        self.assertTrue(preview.ready)
        self.assertEqual(job.status, ImportJob.Status.READY)
        self.assertFalse(BusinessService.objects.exists())
        self.assertFalse(ServiceCategory.objects.exists())

    def test_unique_same_business_external_code_is_update_with_visible_changes(self):
        service = BusinessService.objects.create(
            business=self.business,
            name="Old name",
            external_code="emergency-001",
            unit_price=Decimal("10.00"),
            tax_rate=Decimal("3.00"),
        )

        _job, preview = self.preview([self.base_row])

        row = preview.rows[0]
        self.assertEqual(row.status, ServicePreviewStatus.UPDATE)
        self.assertEqual(row.existing_service_id, service.pk)
        changed_fields = {change["field"] for change in row.changes}
        self.assertIn("name", changed_fields)
        self.assertIn("unit_price", changed_fields)
        self.assertIn("tax_rate", changed_fields)
        service.refresh_from_db()
        self.assertEqual(service.name, "Old name")

    def test_cross_business_external_code_and_category_are_ignored(self):
        other = Business.objects.create(name="Other", slug="other-service-preview")
        BusinessService.objects.create(
            business=other,
            name="Foreign",
            external_code="EMERGENCY-001",
            unit_price=Decimal("5.00"),
        )
        ServiceCategory.objects.create(business=other, name="Urgent Response")

        _job, preview = self.preview([self.base_row])

        self.assertEqual(preview.rows[0].status, ServicePreviewStatus.CREATE)
        self.assertTrue(preview.rows[0].category["will_create"])

    def test_matching_name_without_external_code_is_still_create(self):
        BusinessService.objects.create(
            business=self.business,
            name=self.base_row["name"],
            unit_price=Decimal("5.00"),
        )

        _job, preview = self.preview([{**self.base_row, "external_code": ""}])

        self.assertEqual(preview.rows[0].status, ServicePreviewStatus.CREATE)

    def test_ambiguous_database_external_code_requires_review(self):
        for index in range(2):
            BusinessService.objects.create(
                business=self.business,
                name=f"Duplicate {index}",
                external_code="EMERGENCY-001",
                unit_price=Decimal("5.00"),
            )

        job, preview = self.preview([self.base_row])

        self.assertEqual(preview.rows[0].status, ServicePreviewStatus.REVIEW)
        self.assertFalse(preview.ready)
        self.assertEqual(job.status, ImportJob.Status.VALIDATED)

    def test_duplicate_external_code_inside_upload_requires_review(self):
        second = {**self.base_row, "name": "Second"}

        _job, preview = self.preview([self.base_row, second])

        self.assertEqual(
            [row.status for row in preview.rows],
            [ServicePreviewStatus.REVIEW, ServicePreviewStatus.REVIEW],
        )
        self.assertFalse(preview.ready)

    def test_existing_category_is_resolved_only_in_current_business(self):
        category = ServiceCategory.objects.create(
            business=self.business,
            name="Urgent Response",
        )

        _job, preview = self.preview([self.base_row])

        self.assertEqual(preview.rows[0].category["existing_id"], category.pk)
        self.assertFalse(preview.rows[0].category["will_create"])

    def test_inactive_existing_category_retains_legacy_resolution(self):
        category = ServiceCategory.objects.create(
            business=self.business,
            name="Urgent Response",
            is_active=False,
        )

        _job, preview = self.preview([self.base_row])

        self.assertTrue(preview.ready)
        self.assertEqual(preview.rows[0].category["existing_id"], category.pk)

    def test_ambiguous_category_blocks_preview(self):
        ServiceCategory.objects.create(business=self.business, name="Urgent Response")
        ServiceCategory.objects.create(business=self.business, name="Urgent Response")

        _job, preview = self.preview([self.base_row])

        self.assertEqual(preview.rows[0].status, ServicePreviewStatus.ERROR)
        self.assertFalse(preview.ready)

    def test_invalid_new_category_blocks_preview(self):
        _job, preview = self.preview([{**self.base_row, "category": "!!!"}])

        self.assertEqual(preview.rows[0].status, ServicePreviewStatus.ERROR)
        self.assertFalse(preview.ready)

    def test_booking_columns_omitted_preserve_update_values_and_are_explained(self):
        service = BusinessService.objects.create(
            business=self.business,
            name="Booked",
            external_code="BOOKED-1",
            unit_price=Decimal("10.00"),
            tax_rate=Decimal("3.00"),
            is_bookable_online=True,
            default_duration_minutes=45,
            booking_buffer_minutes=5,
            public_description="Existing public copy",
            requires_manual_confirmation=False,
        )
        headers = (
            "name",
            "unit_price",
            "description",
            "tax_rate",
            "category",
            "is_active",
            "external_code",
        )
        row = {
            "name": "Booked",
            "unit_price": "20.00",
            "external_code": service.external_code,
        }

        _job, preview = self.preview([row], headers=headers)

        fields = preview.rows[0].service_fields
        self.assertTrue(fields["is_bookable_online"])
        self.assertEqual(fields["default_duration_minutes"], 45)
        self.assertEqual(fields["booking_buffer_minutes"], 5)
        self.assertEqual(fields["public_description"], "Existing public copy")
        self.assertFalse(fields["requires_manual_confirmation"])
        self.assertTrue(any("omitted" in note for note in preview.rows[0].notes))

    def test_blank_booking_columns_show_and_apply_historical_defaults(self):
        service = BusinessService.objects.create(
            business=self.business,
            name="Booked",
            external_code="BOOKED-1",
            unit_price=Decimal("10.00"),
            is_bookable_online=True,
            default_duration_minutes=45,
            booking_buffer_minutes=5,
            public_description="Existing public copy",
            requires_manual_confirmation=False,
        )
        row = {**self.base_row, "external_code": service.external_code}
        for field_name in (
            "is_bookable_online",
            "default_duration_minutes",
            "booking_buffer_minutes",
            "public_description",
            "requires_manual_confirmation",
        ):
            row[field_name] = ""

        _job, preview = self.preview([row])

        fields = preview.rows[0].service_fields
        self.assertFalse(fields["is_bookable_online"])
        self.assertIsNone(fields["default_duration_minutes"])
        self.assertIsNone(fields["booking_buffer_minutes"])
        self.assertEqual(fields["public_description"], "")
        self.assertTrue(fields["requires_manual_confirmation"])
        self.assertEqual(sum("blank" in note for note in preview.rows[0].notes), 5)

    def test_localized_decimals_and_boolean_vocabulary_are_preserved(self):
        self.business.country = "Netherlands"
        self.business.default_locale = "nl-NL"
        self.business.save(update_fields=["country", "default_locale", "updated_at"])
        row = {
            **self.base_row,
            "unit_price": "1.234,56",
            "tax_rate": "21,00",
            "is_active": "off",
            "is_bookable_online": "on",
        }

        _job, preview = self.preview([row])

        fields = preview.rows[0].service_fields
        self.assertEqual(fields["unit_price"], "1234.56")
        self.assertEqual(fields["tax_rate"], "21.00")
        self.assertFalse(fields["is_active"])
        self.assertTrue(fields["is_bookable_online"])

    def test_direct_post_creates_preview_and_does_not_write_services(self):
        self.login()

        response = self.client.post(
            reverse("business_service_import"),
            {"csv_file": self.upload([self.base_row])},
            follow=True,
        )

        self.assertContains(response, "Service Import Preview")
        self.assertContains(response, "Confirm Service Import")
        self.assertFalse(BusinessService.objects.exists())
        self.assertEqual(ImportJob.objects.get().status, ImportJob.Status.READY)

    def test_missing_required_header_is_visible_in_preview(self):
        self.login()
        response = self.client.post(
            reverse("business_service_import"),
            {
                "csv_file": self.upload(
                    [{"name": "No price", "external_code": "NO-PRICE"}],
                    headers=("name", "external_code"),
                )
            },
            follow=True,
        )

        self.assertContains(response, "Missing required CSV column: unit_price.")
        self.assertNotContains(response, "Confirm Service Import")
