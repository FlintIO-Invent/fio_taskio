from __future__ import annotations

import csv
import io
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as TestClient
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .importing.jobs import create_import_job
from .importing.lead_execution import LeadImportExecutionCode, execute_lead_import
from .importing.lead_preview import persist_lead_preview
from .importing.leads import LEAD_IMPORT_SCHEMA, LEAD_TEMPLATE_FIELDS, validate_lead_import
from .importing.types import ImportType
from .models import ActivityLog, BusinessService, Client, ImportJob, Lead, ServiceCategory


class LeadExecutionTestMixin:
    def setUp(self):
        self.business = Business.objects.create(
            name="Lead Execution Workspace",
            slug="lead-execution-workspace",
            country="Sint Maarten",
        )
        plan = ClarivoPlan.objects.create(name="Lead Execution Plan", slug="lead-execution-plan")
        BusinessSubscription.objects.create(
            business=self.business,
            plan=plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.user = TaskIOUser.objects.create_user(
            email="lead-execution-owner@example.com",
            password="testpass123",
        )
        self.membership = BusinessUser.objects.create(
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
            "status": "CONTACTED",
            "category": "",
            "street_address": "12 Example Street",
            "district": "SIMPSON_BAY",
            "country": "",
            "postal_code": "",
            "message": "Historical request",
            "notes": "Imported history",
            "consent_to_contact": "false",
        }

    def upload(self, rows):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=LEAD_TEMPLATE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        return SimpleUploadedFile(
            "leads.csv",
            output.getvalue().encode("utf-8"),
            content_type="text/csv",
        )

    def ready_job(self, rows):
        validation = validate_lead_import(self.upload(rows), business=self.business)
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
        self.assertTrue(preview.ready)
        self.assertEqual(job.status, ImportJob.Status.READY)
        return job

    def execute(self, job):
        return execute_lead_import(
            job_id=job.pk,
            business=self.business,
            actor=self.user,
        )

    def login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()


class LeadImportExecutionSuccessTests(LeadExecutionTestMixin, TestCase):
    def test_lead_is_created_with_only_normalized_and_forced_safe_values(self):
        category = ServiceCategory.objects.create(business=self.business, name="Maintenance")
        job = self.ready_job(
            [{**self.base_row, "category": "Maintenance", "consent_to_contact": "yes"}]
        )

        result = self.execute(job)

        self.assertEqual(result.code, LeadImportExecutionCode.COMPLETED)
        lead = Lead.objects.get()
        self.assertEqual(lead.business, self.business)
        self.assertEqual(lead.category, category)
        self.assertEqual(lead.first_name, "Jamie")
        self.assertEqual(lead.status, Lead.Status.CONTACTED)
        self.assertTrue(lead.consent_to_contact)
        self.assertTrue(lead.is_active)
        self.assertEqual(lead.request_source, Lead.RequestSource.OTHER)
        self.assertIsNone(lead.requested_service)
        self.assertIsNone(lead.preferred_start_time)
        self.assertIsNone(lead.preferred_end_time)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.COMPLETED)
        self.assertEqual(job.rows_created, 1)

    def test_multiple_types_are_created_and_exact_duplicates_are_skipped(self):
        interest = {
            **self.base_row,
            "lead_type": "INTEREST",
            "email": "interest@example.com",
            "phone": "+1 721 555 0101",
        }
        job = self.ready_job([self.base_row, self.base_row, interest])

        result = self.execute(job)

        self.assertEqual(result.leads_created, 2)
        self.assertEqual(result.duplicates_skipped, 1)
        self.assertEqual(result.total_processed, 3)
        self.assertEqual(
            set(Lead.objects.values_list("lead_type", flat=True)),
            {Lead.LeadType.REQUEST, Lead.LeadType.INTEREST},
        )

    def test_replay_is_idempotent(self):
        job = self.ready_job([self.base_row])

        first = self.execute(job)
        second = self.execute(job)

        self.assertEqual(first.code, LeadImportExecutionCode.COMPLETED)
        self.assertEqual(second.code, LeadImportExecutionCode.ALREADY_COMPLETED)
        self.assertEqual(second.leads_created, 1)
        self.assertEqual(Lead.objects.count(), 1)


class LeadImportExecutionSafetyTests(LeadExecutionTestMixin, TestCase):
    def test_wrong_business_and_wrong_creator_are_denied(self):
        job = self.ready_job([self.base_row])
        other_business = Business.objects.create(name="Other", slug="other-lead-execution")
        other_user = TaskIOUser.objects.create_user(
            email="other-lead-executor@example.com",
            password="testpass123",
        )
        BusinessUser.objects.create(
            business=other_business,
            user=self.user,
            role=BusinessUser.Role.OWNER,
        )
        BusinessUser.objects.create(
            business=self.business,
            user=other_user,
            role=BusinessUser.Role.ADMIN,
        )

        with self.assertRaises(PermissionDenied):
            execute_lead_import(job_id=job.pk, business=other_business, actor=self.user)
        with self.assertRaises(PermissionDenied):
            execute_lead_import(job_id=job.pk, business=self.business, actor=other_user)
        self.assertFalse(Lead.objects.exists())

    def test_role_change_expiry_and_non_ready_jobs_create_nothing(self):
        role_job = self.ready_job([self.base_row])
        self.membership.role = BusinessUser.Role.VIEWER
        self.membership.save(update_fields=["role"])
        with self.assertRaises(PermissionDenied):
            self.execute(role_job)

        self.membership.role = BusinessUser.Role.OWNER
        self.membership.save(update_fields=["role"])
        expired_job = self.ready_job([self.base_row])
        expired_job.expires_at = timezone.now() - timedelta(seconds=1)
        expired_job.save(update_fields=["expires_at"])
        self.assertEqual(self.execute(expired_job).code, LeadImportExecutionCode.EXPIRED)

        validation = validate_lead_import(
            self.upload([{**self.base_row, "email": "bad"}]),
            business=self.business,
        )
        non_ready = create_import_job(
            business=self.business,
            actor=self.user,
            import_type=ImportType.LEADS,
            schema_version=LEAD_IMPORT_SCHEMA.version,
            parsed_file=validation.parsed_file,
        )
        persist_lead_preview(
            validation,
            job=non_ready,
            business=self.business,
            actor=self.user,
        )
        self.assertEqual(self.execute(non_ready).code, LeadImportExecutionCode.NOT_READY)
        self.assertFalse(Lead.objects.exists())

    def test_duplicate_appearing_after_preview_blocks_all_rows(self):
        second = {
            **self.base_row,
            "email": "second@example.com",
            "phone": "+1 721 555 0102",
        }
        job = self.ready_job([self.base_row, second])
        Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            first_name="New existing",
            last_name="Lead",
            email="jamie@example.com",
            phone="different",
            company_name="Existing",
        )

        result = self.execute(job)

        self.assertEqual(result.code, LeadImportExecutionCode.DUPLICATES_CHANGED)
        self.assertEqual(Lead.objects.count(), 1)

    def test_category_change_after_preview_blocks_everything(self):
        category = ServiceCategory.objects.create(business=self.business, name="Maintenance")
        job = self.ready_job([{**self.base_row, "category": "Maintenance"}])
        category.is_active = False
        category.save(update_fields=["is_active"])

        result = self.execute(job)

        self.assertEqual(result.code, LeadImportExecutionCode.CATEGORY_CHANGED)
        self.assertFalse(Lead.objects.exists())

    def test_late_failure_rolls_back_every_lead(self):
        second = {
            **self.base_row,
            "email": "second@example.com",
            "phone": "+1 721 555 0102",
        }
        job = self.ready_job([self.base_row, second])
        original_save = Lead.save

        def fail_second(instance, *args, **kwargs):
            if instance.email == "second@example.com":
                raise RuntimeError("late failure")
            return original_save(instance, *args, **kwargs)

        with mock.patch.object(Lead, "save", autospec=True, side_effect=fail_second):
            result = self.execute(job)

        self.assertEqual(result.code, LeadImportExecutionCode.FAILED)
        self.assertFalse(Lead.objects.exists())
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.FAILED)

    def test_forged_post_is_ignored_and_execute_requires_post_and_csrf(self):
        job = self.ready_job([self.base_row])
        self.login()
        self.assertEqual(
            self.client.get(reverse("lead_import_execute", args=[job.pk])).status_code,
            405,
        )

        response = self.client.post(
            reverse("lead_import_execute", args=[job.pk]),
            {
                "email": "forged@example.com",
                "business_id": "999999",
                "status": "INVOICED",
                "request_source": "public_booking",
                "is_active": "false",
            },
        )
        self.assertRedirects(response, reverse("lead_import_result", args=[job.pk]))
        lead = Lead.objects.get()
        self.assertEqual(lead.email, "jamie@example.com")
        self.assertEqual(lead.status, Lead.Status.CONTACTED)
        self.assertEqual(lead.request_source, Lead.RequestSource.OTHER)
        self.assertTrue(lead.is_active)

        csrf_job = self.ready_job(
            [{**self.base_row, "email": "csrf@example.com", "phone": "+1 721 555 0199"}]
        )
        csrf_client = TestClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        session = csrf_client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        self.assertEqual(
            csrf_client.post(reverse("lead_import_execute", args=[csrf_job.pk])).status_code,
            403,
        )
        self.assertEqual(Lead.objects.count(), 1)

    def test_execution_has_no_forbidden_side_effects(self):
        client = Client.objects.create(
            business=self.business,
            first_name="Jamie",
            last_name="Client",
            email="jamie@example.com",
            phone="different",
            company_name="Existing Client",
        )
        baseline = {
            "clients": Client.objects.count(),
            "appointments": Appointment.objects.count(),
            "invoices": Invoice.objects.count(),
            "services": BusinessService.objects.count(),
            "activities": ActivityLog.objects.count(),
            "categories": ServiceCategory.objects.count(),
        }
        job = self.ready_job([self.base_row])

        result = self.execute(job)

        self.assertEqual(result.code, LeadImportExecutionCode.COMPLETED)
        self.assertEqual(Client.objects.count(), baseline["clients"])
        self.assertTrue(Client.objects.filter(pk=client.pk).exists())
        self.assertEqual(Appointment.objects.count(), baseline["appointments"])
        self.assertEqual(Invoice.objects.count(), baseline["invoices"])
        self.assertEqual(BusinessService.objects.count(), baseline["services"])
        self.assertEqual(ActivityLog.objects.count(), baseline["activities"])
        self.assertEqual(ServiceCategory.objects.count(), baseline["categories"])
        self.assertEqual(len(mail.outbox), 0)
