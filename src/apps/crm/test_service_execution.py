from __future__ import annotations

import csv
import io
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .importing.jobs import create_import_job
from .importing.service_execution import (
    ServiceImportExecutionCode,
    execute_service_import,
)
from .importing.service_preview import persist_service_preview
from .importing.services import (
    SERVICE_IMPORT_SCHEMA,
    SERVICE_TEMPLATE_FIELDS,
    validate_service_import,
)
from .importing.types import ImportType
from .models import ActivityLog, BusinessService, Client, ImportJob, Lead, ServiceCategory


class ServiceExecutionTestMixin:
    def setUp(self):
        self.business = Business.objects.create(
            name="Service Execution Workspace",
            slug="service-execution-workspace",
            tax_rate=Decimal("7.50"),
        )
        plan = ClarivoPlan.objects.create(name="Execution Plan", slug="service-execution-plan")
        BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.user = TaskIOUser.objects.create_user(
            email="service-executor@example.com",
            password="testpass123",
        )
        self.membership = BusinessUser.objects.create(
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

    def upload(self, rows, *, headers=SERVICE_TEMPLATE_FIELDS):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return SimpleUploadedFile(
            "services.csv",
            output.getvalue().encode("utf-8"),
            content_type="text/csv",
        )

    def job_for(self, rows, *, headers=SERVICE_TEMPLATE_FIELDS):
        validation = validate_service_import(
            self.upload(rows, headers=headers),
            business=self.business,
        )
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

    def ready_job(self, rows, *, headers=SERVICE_TEMPLATE_FIELDS):
        job, preview = self.job_for(rows, headers=headers)
        self.assertTrue(preview.ready)
        self.assertEqual(job.status, ImportJob.Status.READY)
        return job

    def execute(self, job):
        return execute_service_import(
            job_id=job.pk,
            business=self.business,
            actor=self.user,
        )

    def login(self, *, user=None, business=None):
        self.client.force_login(user or self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = (business or self.business).pk
        session.save()


class ServiceImportExecutionSuccessTests(ServiceExecutionTestMixin, TestCase):
    def test_atomic_create_update_and_category_creation(self):
        existing = BusinessService.objects.create(
            business=self.business,
            name="Old inspection",
            external_code="INSPECT-1",
            unit_price=Decimal("10.00"),
            tax_rate=Decimal("3.00"),
        )
        rows = [
            {**self.base_row, "category": "Maintenance"},
            {
                **self.base_row,
                "name": "Updated inspection",
                "external_code": "inspect-1",
                "category": "Maintenance",
            },
        ]
        job = self.ready_job(rows)

        result = self.execute(job)

        self.assertEqual(result.code, ServiceImportExecutionCode.COMPLETED)
        self.assertEqual(result.services_created, 1)
        self.assertEqual(result.services_updated, 1)
        self.assertEqual(result.categories_created, 1)
        self.assertEqual(ServiceCategory.objects.filter(business=self.business).count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Updated inspection")
        self.assertEqual(existing.business, self.business)
        self.assertEqual(existing.category.business, self.business)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.COMPLETED)
        self.assertEqual(job.rows_created, 1)
        self.assertEqual(job.rows_updated, 1)
        self.assertEqual(job.rows_skipped, 0)
        self.assertIsNotNone(job.completed_at)

    def test_omitted_booking_fields_are_preserved_on_execution(self):
        existing = BusinessService.objects.create(
            business=self.business,
            name="Booked",
            external_code="BOOKED-1",
            unit_price=Decimal("10.00"),
            is_bookable_online=True,
            default_duration_minutes=45,
            booking_buffer_minutes=5,
            public_description="Existing copy",
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
        job = self.ready_job(
            [
                {
                    "name": "Booked updated",
                    "unit_price": "50.00",
                    "external_code": existing.external_code,
                }
            ],
            headers=headers,
        )

        self.execute(job)

        existing.refresh_from_db()
        self.assertTrue(existing.is_bookable_online)
        self.assertEqual(existing.default_duration_minutes, 45)
        self.assertEqual(existing.booking_buffer_minutes, 5)
        self.assertEqual(existing.public_description, "Existing copy")
        self.assertFalse(existing.requires_manual_confirmation)

    def test_blank_booking_fields_apply_historical_defaults_on_execution(self):
        existing = BusinessService.objects.create(
            business=self.business,
            name="Booked",
            external_code="BOOKED-1",
            unit_price=Decimal("10.00"),
            is_bookable_online=True,
            default_duration_minutes=45,
            booking_buffer_minutes=5,
            public_description="Existing copy",
            requires_manual_confirmation=False,
        )
        row = {**self.base_row, "external_code": existing.external_code}
        for field_name in (
            "is_bookable_online",
            "default_duration_minutes",
            "booking_buffer_minutes",
            "public_description",
            "requires_manual_confirmation",
        ):
            row[field_name] = ""
        job = self.ready_job([row])

        self.execute(job)

        existing.refresh_from_db()
        self.assertFalse(existing.is_bookable_online)
        self.assertIsNone(existing.default_duration_minutes)
        self.assertIsNone(existing.booking_buffer_minutes)
        self.assertEqual(existing.public_description, "")
        self.assertTrue(existing.requires_manual_confirmation)

    def test_double_confirmation_is_idempotent(self):
        job = self.ready_job([self.base_row])

        first = self.execute(job)
        second = self.execute(job)

        self.assertEqual(first.code, ServiceImportExecutionCode.COMPLETED)
        self.assertEqual(second.code, ServiceImportExecutionCode.ALREADY_COMPLETED)
        self.assertEqual(second.services_created, 1)
        self.assertEqual(second.categories_created, 1)
        self.assertEqual(BusinessService.objects.count(), 1)
        self.assertEqual(ServiceCategory.objects.count(), 1)


class ServiceImportExecutionSafetyTests(ServiceExecutionTestMixin, TestCase):
    def test_category_creation_rolls_back_when_service_write_fails(self):
        job = self.ready_job([self.base_row])

        with mock.patch(
            "apps.crm.importing.service_execution._write_services",
            side_effect=RuntimeError("forced failure"),
        ):
            result = self.execute(job)

        self.assertEqual(result.code, ServiceImportExecutionCode.FAILED)
        self.assertFalse(ServiceCategory.objects.exists())
        self.assertFalse(BusinessService.objects.exists())

    def test_later_row_failure_rolls_back_prior_create_and_update(self):
        existing = BusinessService.objects.create(
            business=self.business,
            name="Before",
            external_code="EXISTING-1",
            unit_price=Decimal("10.00"),
        )
        job = self.ready_job(
            [
                {**self.base_row, "name": "After", "external_code": "EXISTING-1", "category": ""},
                {**self.base_row, "name": "New", "external_code": "NEW-1", "category": ""},
            ]
        )
        original_save = BusinessService.save
        calls = 0

        def save_then_fail(instance, *args, **kwargs):
            nonlocal calls
            original_save(instance, *args, **kwargs)
            calls += 1
            if calls == 2:
                raise RuntimeError("late write failure")

        with mock.patch.object(BusinessService, "save", autospec=True, side_effect=save_then_fail):
            result = self.execute(job)

        self.assertEqual(result.code, ServiceImportExecutionCode.FAILED)
        existing.refresh_from_db()
        self.assertEqual(existing.name, "Before")
        self.assertFalse(BusinessService.objects.filter(external_code="NEW-1").exists())

    def test_service_match_change_after_preview_blocks_all_rows(self):
        job = self.ready_job([self.base_row])
        BusinessService.objects.create(
            business=self.business,
            name="Inserted later",
            external_code="EMERGENCY-001",
            unit_price=Decimal("1.00"),
        )

        result = self.execute(job)

        self.assertEqual(result.code, ServiceImportExecutionCode.STATE_CHANGED)
        self.assertEqual(BusinessService.objects.count(), 1)

    def test_category_change_after_preview_blocks_all_rows(self):
        job = self.ready_job([self.base_row])
        ServiceCategory.objects.create(business=self.business, name="Urgent Response")

        result = self.execute(job)

        self.assertEqual(result.code, ServiceImportExecutionCode.STATE_CHANGED)
        self.assertFalse(BusinessService.objects.exists())

    def test_wrong_business_is_denied(self):
        job = self.ready_job([self.base_row])
        other = Business.objects.create(name="Other", slug="other-service-execution")
        BusinessUser.objects.create(business=other, user=self.user, role=BusinessUser.Role.OWNER)

        with self.assertRaises(PermissionDenied):
            execute_service_import(job_id=job.pk, business=other, actor=self.user)
        self.assertFalse(BusinessService.objects.exists())

    def test_wrong_creator_is_denied(self):
        job = self.ready_job([self.base_row])
        other_user = TaskIOUser.objects.create_user(email="other@example.com", password="test")
        BusinessUser.objects.create(
            business=self.business,
            user=other_user,
            role=BusinessUser.Role.ADMIN,
        )

        with self.assertRaises(PermissionDenied):
            execute_service_import(job_id=job.pk, business=self.business, actor=other_user)
        self.assertFalse(BusinessService.objects.exists())

    def test_role_is_rechecked_at_execution(self):
        job = self.ready_job([self.base_row])
        self.membership.role = BusinessUser.Role.VIEWER
        self.membership.save(update_fields=["role"])

        with self.assertRaises(PermissionDenied):
            self.execute(job)
        self.assertFalse(BusinessService.objects.exists())

    def test_expired_job_does_not_write(self):
        job = self.ready_job([self.base_row])
        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["expires_at"])

        result = self.execute(job)

        self.assertEqual(result.code, ServiceImportExecutionCode.EXPIRED)
        self.assertFalse(BusinessService.objects.exists())
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.EXPIRED)

    def test_non_ready_job_does_not_write(self):
        job, preview = self.job_for([{**self.base_row, "unit_price": "not-a-price"}])
        self.assertFalse(preview.ready)

        result = self.execute(job)

        self.assertEqual(result.code, ServiceImportExecutionCode.NOT_READY)
        self.assertFalse(BusinessService.objects.exists())

    def test_forged_browser_values_are_ignored(self):
        job = self.ready_job([self.base_row])
        other = Business.objects.create(name="Other", slug="forged-service-business")
        self.login()

        response = self.client.post(
            reverse("business_service_import_execute", args=[job.pk]),
            {
                "name": "Forged name",
                "unit_price": "0.01",
                "business": other.pk,
                "category": "Forged category",
            },
            follow=True,
        )

        self.assertContains(response, "Import complete")
        service = BusinessService.objects.get()
        self.assertEqual(service.name, self.base_row["name"])
        self.assertEqual(service.unit_price, Decimal("125.00"))
        self.assertEqual(service.business, self.business)

    def test_success_has_no_unrelated_side_effects(self):
        job = self.ready_job([self.base_row])

        self.execute(job)

        self.assertFalse(Client.objects.exists())
        self.assertFalse(Lead.objects.exists())
        self.assertFalse(Appointment.objects.exists())
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(ActivityLog.objects.exists())
        self.assertEqual(len(mail.outbox), 0)
