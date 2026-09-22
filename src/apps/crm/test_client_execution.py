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

from .importing.client_execution import (
    ClientImportExecutionCode,
    execute_client_import,
)
from .importing.client_preview import persist_client_preview
from .importing.clients import (
    CLIENT_IMPORT_SCHEMA,
    CLIENT_STANDARD_TEMPLATE_FIELDS,
    validate_client_import,
)
from .importing.jobs import create_import_job
from .importing.types import ImportType
from .models import ActivityLog, BusinessService, Client, ImportJob, Lead, ServiceCategory


class ClientExecutionTestMixin:
    def setUp(self):
        self.business = Business.objects.create(
            name="Execution Workspace",
            slug="execution-workspace",
            country="Sint Maarten",
        )
        self.plan = ClarivoPlan.objects.create(
            name="Execution Plan",
            slug="execution-plan",
            max_clients=10,
        )
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.user = TaskIOUser.objects.create_user(
            email="execution-owner@example.com",
            password="testpass123",
        )
        self.membership = BusinessUser.objects.create(
            business=self.business,
            user=self.user,
            role=BusinessUser.Role.OWNER,
        )
        self.valid_row = {
            "first_name": " Jane ",
            "last_name": " Doe ",
            "email": "jane@example.com",
            "phone": "+1 (721) 555-0100",
            "company_name": "Example Consulting",
            "street_address": "12 Example Street",
        }

    def upload(self, rows):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CLIENT_STANDARD_TEMPLATE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        return SimpleUploadedFile(
            "clients.csv",
            output.getvalue().encode("utf-8"),
            content_type="text/csv",
        )

    def existing_client(self, **overrides):
        sequence = Client.objects.count() + 1
        values = {
            "business": self.business,
            "first_name": "Existing",
            "last_name": f"Client {sequence}",
            "email": f"existing-{sequence}@example.com",
            "phone": f"+1 721 800 {sequence:04d}",
            "company_name": "Existing Company",
            "street_address": "1 Existing Street",
        }
        values.update(overrides)
        return Client.objects.create(**values)

    def ready_job(self, rows):
        uploaded_file = self.upload(rows)
        validation = validate_client_import(uploaded_file, business=self.business)
        job = create_import_job(
            business=self.business,
            actor=self.user,
            import_type=ImportType.CLIENTS,
            schema_version=CLIENT_IMPORT_SCHEMA.version,
            parsed_file=validation.parsed_file,
        )
        preview = persist_client_preview(
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
        return execute_client_import(
            job_id=job.pk,
            business=self.business,
            actor=self.user,
        )

    def login(self, user=None, business=None):
        self.client.force_login(user or self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = (business or self.business).pk
        session.save()


class ClientImportExecutionSuccessTests(ClientExecutionTestMixin, TestCase):
    def test_one_client_uses_normalized_defaults_and_forced_business_fields(self):
        job = self.ready_job([self.valid_row])
        result = self.execute(job)

        self.assertEqual(result.code, ClientImportExecutionCode.COMPLETED)
        client = Client.objects.get()
        self.assertEqual(client.business, self.business)
        self.assertEqual(client.first_name, "Jane")
        self.assertEqual(client.last_name, "Doe")
        self.assertEqual(client.phone, "+1 (721) 555-0100")
        self.assertEqual(client.client_type, Client.ClientType.BUSINESS)
        self.assertEqual(client.client_status, Client.ClientStatus.LEAD)
        self.assertEqual(client.priority, Client.Priority.MEDIUM)
        self.assertEqual(
            client.preferred_contact_method,
            Client.PreferredContactMethod.EMAIL,
        )
        self.assertFalse(client.consent_to_contact)
        self.assertTrue(client.is_active)

        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.COMPLETED)
        self.assertEqual(job.rows_created, 1)
        self.assertEqual(job.rows_skipped, 0)
        self.assertIsNotNone(job.completed_at)

    def test_multiple_clients_are_created(self):
        rows = [
            {
                **self.valid_row,
                "email": f"client-{index}@example.com",
                "phone": f"+1 721 900 {index:04d}",
            }
            for index in range(3)
        ]
        job = self.ready_job(rows)

        result = self.execute(job)

        self.assertEqual(result.clients_created, 3)
        self.assertEqual(Client.objects.filter(business=self.business).count(), 3)

    def test_previewed_duplicates_are_skipped(self):
        existing = self.existing_client(email="duplicate@example.com")
        rows = [
            {**self.valid_row, "email": "duplicate@example.com", "phone": existing.phone},
            {**self.valid_row, "email": "new@example.com", "phone": "+1 721 555 0199"},
        ]
        job = self.ready_job(rows)

        result = self.execute(job)

        self.assertEqual(result.clients_created, 1)
        self.assertEqual(result.duplicates_skipped, 1)
        self.assertEqual(result.total_processed, 2)
        self.assertEqual(Client.objects.filter(business=self.business).count(), 2)


class ClientImportExecutionSecurityTests(ClientExecutionTestMixin, TestCase):
    def test_wrong_business_is_denied_and_creates_nothing(self):
        job = self.ready_job([self.valid_row])
        other_business = Business.objects.create(name="Other", slug="other-execution")
        BusinessUser.objects.create(
            business=other_business,
            user=self.user,
            role=BusinessUser.Role.OWNER,
        )

        with self.assertRaises(PermissionDenied):
            execute_client_import(
                job_id=job.pk,
                business=other_business,
                actor=self.user,
            )
        self.assertFalse(Client.objects.exists())

    def test_wrong_creator_is_denied_and_creates_nothing(self):
        job = self.ready_job([self.valid_row])
        other_user = TaskIOUser.objects.create_user(
            email="other-executor@example.com", password="testpass123"
        )
        BusinessUser.objects.create(
            business=self.business,
            user=other_user,
            role=BusinessUser.Role.ADMIN,
        )

        with self.assertRaises(PermissionDenied):
            execute_client_import(
                job_id=job.pk,
                business=self.business,
                actor=other_user,
            )
        self.assertFalse(Client.objects.exists())

    def test_viewer_is_denied(self):
        job = self.ready_job([self.valid_row])
        self.membership.role = BusinessUser.Role.VIEWER
        self.membership.save(update_fields=["role"])

        with self.assertRaises(PermissionDenied):
            self.execute(job)
        self.assertFalse(Client.objects.exists())

    def test_expired_job_creates_nothing(self):
        job = self.ready_job([self.valid_row])
        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["expires_at"])

        result = self.execute(job)

        self.assertEqual(result.code, ClientImportExecutionCode.EXPIRED)
        self.assertFalse(Client.objects.exists())
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.EXPIRED)

    def test_non_ready_job_creates_nothing(self):
        self.plan.max_clients = 0
        self.plan.save(update_fields=["max_clients"])
        uploaded_file = self.upload([self.valid_row])
        validation = validate_client_import(uploaded_file, business=self.business)
        job = create_import_job(
            business=self.business,
            actor=self.user,
            import_type=ImportType.CLIENTS,
            schema_version=CLIENT_IMPORT_SCHEMA.version,
            parsed_file=validation.parsed_file,
        )
        persist_client_preview(
            validation,
            job=job,
            business=self.business,
            actor=self.user,
        )

        result = self.execute(job)

        self.assertEqual(result.code, ClientImportExecutionCode.NOT_READY)
        self.assertFalse(Client.objects.exists())

    def test_changed_preview_digest_is_rejected(self):
        job = self.ready_job([self.valid_row])
        job.file_digest = "0" * 64
        job.save(update_fields=["file_digest"])

        result = self.execute(job)

        self.assertEqual(result.code, ClientImportExecutionCode.PREVIEW_INVALID)
        self.assertFalse(Client.objects.exists())

    def test_changed_job_schema_is_denied(self):
        job = self.ready_job([self.valid_row])
        job.schema_version = "forged"
        job.save(update_fields=["schema_version"])

        with self.assertRaises(PermissionDenied):
            self.execute(job)
        self.assertFalse(Client.objects.exists())

    def test_forged_browser_payload_is_ignored(self):
        job = self.ready_job([self.valid_row])
        self.login()

        response = self.client.post(
            reverse("client_import_execute", args=[job.pk]),
            {
                "first_name": "Forged",
                "email": "forged@example.com",
                "business_id": "999999",
                "assigned_to": "999999",
                "is_active": "false",
            },
        )

        self.assertRedirects(response, reverse("client_import_result", args=[job.pk]))
        client = Client.objects.get()
        self.assertEqual(client.first_name, "Jane")
        self.assertEqual(client.email, "jane@example.com")
        self.assertEqual(client.business, self.business)
        self.assertTrue(client.is_active)

    def test_execute_requires_post_and_csrf(self):
        job = self.ready_job([self.valid_row])
        self.login()
        self.assertEqual(
            self.client.get(reverse("client_import_execute", args=[job.pk])).status_code,
            405,
        )

        csrf_client = TestClient(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        session = csrf_client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = self.business.pk
        session.save()
        response = csrf_client.post(reverse("client_import_execute", args=[job.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Client.objects.exists())


class ClientImportExecutionRevalidationTests(ClientExecutionTestMixin, TestCase):
    def test_duplicate_appearing_after_preview_blocks_everything(self):
        job = self.ready_job([self.valid_row])
        self.existing_client(email="jane@example.com", phone="+1 721 111 0001")

        result = self.execute(job)

        self.assertEqual(result.code, ClientImportExecutionCode.DUPLICATES_CHANGED)
        self.assertEqual(Client.objects.count(), 1)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.FAILED)

    def test_ambiguous_match_appearing_after_preview_blocks_everything(self):
        job = self.ready_job([self.valid_row])
        self.existing_client(email="jane@example.com")
        self.existing_client(email="JANE@EXAMPLE.COM")

        result = self.execute(job)

        self.assertEqual(result.code, ClientImportExecutionCode.DUPLICATES_CHANGED)
        self.assertEqual(Client.objects.count(), 2)

    def test_capacity_decreasing_after_preview_blocks_entire_batch(self):
        self.plan.max_clients = 2
        self.plan.save(update_fields=["max_clients"])
        job = self.ready_job([self.valid_row])
        self.existing_client()
        self.existing_client()

        result = self.execute(job)

        self.assertEqual(result.code, ClientImportExecutionCode.CAPACITY_CHANGED)
        self.assertEqual(Client.objects.count(), 2)
        job.refresh_from_db()
        self.assertEqual(job.rows_created, 0)

    def test_permission_change_after_preview_blocks_execution(self):
        job = self.ready_job([self.valid_row])
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])

        with self.assertRaises(PermissionDenied):
            self.execute(job)
        self.assertFalse(Client.objects.exists())


class ClientImportExecutionAtomicityTests(ClientExecutionTestMixin, TestCase):
    def test_later_row_failure_rolls_back_entire_batch(self):
        rows = [
            {
                **self.valid_row,
                "email": f"atomic-{index}@example.com",
                "phone": f"+1 721 700 {index:04d}",
            }
            for index in range(2)
        ]
        job = self.ready_job(rows)

        from .importing import client_execution

        original_create = client_execution._create_client_from_trusted_row
        call_count = 0

        def fail_second(row, *, business):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("forced later-row failure")
            return original_create(row, business=business)

        with mock.patch.object(
            client_execution,
            "_create_client_from_trusted_row",
            side_effect=fail_second,
        ):
            result = self.execute(job)

        self.assertEqual(result.code, ClientImportExecutionCode.FAILED)
        self.assertFalse(Client.objects.exists())
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.FAILED)
        self.assertEqual(job.rows_created, 0)


class ClientImportExecutionIdempotencyTests(ClientExecutionTestMixin, TestCase):
    def test_completed_job_replay_creates_no_additional_clients(self):
        job = self.ready_job([self.valid_row])

        first = self.execute(job)
        second = self.execute(job)

        self.assertEqual(first.code, ClientImportExecutionCode.COMPLETED)
        self.assertEqual(second.code, ClientImportExecutionCode.ALREADY_COMPLETED)
        self.assertEqual(second.clients_created, 1)
        self.assertEqual(Client.objects.count(), 1)

    def test_double_post_creates_clients_once_and_shows_replay_result(self):
        job = self.ready_job([self.valid_row])
        self.login()
        execute_url = reverse("client_import_execute", args=[job.pk])

        first = self.client.post(execute_url)
        second = self.client.post(execute_url)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Client.objects.count(), 1)
        result_response = self.client.get(reverse("client_import_result", args=[job.pk]))
        self.assertContains(result_response, "Import already completed")
        self.assertContains(result_response, "Clients created")
        self.assertContains(result_response, "Duplicates skipped")
        self.assertContains(result_response, "Total processed")


class ClientImportExecutionSideEffectTests(ClientExecutionTestMixin, TestCase):
    def test_success_creates_only_clients_and_import_metadata(self):
        job = self.ready_job([self.valid_row])
        model_counts = {
            Lead: Lead.objects.count(),
            BusinessService: BusinessService.objects.count(),
            ServiceCategory: ServiceCategory.objects.count(),
            Appointment: Appointment.objects.count(),
            Invoice: Invoice.objects.count(),
            ActivityLog: ActivityLog.objects.count(),
        }
        email_count = len(mail.outbox)

        result = self.execute(job)

        self.assertEqual(result.clients_created, 1)
        for model, initial_count in model_counts.items():
            self.assertEqual(model.objects.count(), initial_count)
        self.assertEqual(len(mail.outbox), email_count)


class ManualClientCapacityLockRegressionTests(ClientExecutionTestMixin, TestCase):
    def test_manual_create_rechecks_capacity_inside_shared_lock(self):
        self.login()
        post_data = {
            **self.valid_row,
            "client_type": Client.ClientType.BUSINESS,
            "client_status": Client.ClientStatus.LEAD,
            "priority": Client.Priority.MEDIUM,
            "preferred_contact_method": Client.PreferredContactMethod.EMAIL,
            "country": "Sint Maarten",
        }

        with mock.patch(
            "apps.crm.views.business_limit_reached",
            side_effect=[False, True],
        ):
            response = self.client.post(reverse("staff_client_create"), post_data)

        self.assertRedirects(response, reverse("staff_client_list"))
        self.assertFalse(Client.objects.exists())
