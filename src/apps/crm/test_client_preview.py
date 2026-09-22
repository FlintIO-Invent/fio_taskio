from __future__ import annotations

import csv
import io
import uuid
from datetime import timedelta

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .importing.client_preview import (
    ClientPreviewStatus,
    build_client_preview,
    persist_client_preview,
    preview_binding_for_job,
)
from .importing.clients import (
    CLIENT_IMPORT_SCHEMA,
    CLIENT_STANDARD_TEMPLATE_FIELDS,
    validate_client_import,
)
from .importing.jobs import create_import_job
from .importing.preview import database_preview_store
from .importing.types import ImportType
from .models import ActivityLog, BusinessService, Client, ImportJob, Lead, ServiceCategory


class ClientPreviewTestMixin:
    def setUp(self):
        self.business = Business.objects.create(
            name="Preview Workspace",
            slug="preview-workspace",
            country="Sint Maarten",
        )
        self.plan = ClarivoPlan.objects.create(
            name="Preview Plan",
            slug="preview-plan",
            max_clients=10,
        )
        self.subscription = BusinessSubscription.objects.create(
            business=self.business,
            plan=self.plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        self.user = TaskIOUser.objects.create_user(
            email="preview-owner@example.com",
            password="testpass123",
        )
        BusinessUser.objects.create(
            business=self.business,
            user=self.user,
            role=BusinessUser.Role.OWNER,
        )
        self.valid_row = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@example.com",
            "phone": "+1 721 555 0100",
            "company_name": "Example Consulting",
            "street_address": "12 Example Street",
        }

    def upload(self, rows, *, headers=CLIENT_STANDARD_TEMPLATE_FIELDS, name="clients.csv"):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return SimpleUploadedFile(name, output.getvalue().encode("utf-8"), content_type="text/csv")

    def existing_client(self, **overrides):
        sequence = Client.objects.count() + 1
        values = {
            "business": self.business,
            "first_name": "Existing",
            "last_name": f"Client {sequence}",
            "email": f"existing-{sequence}@example.com",
            "phone": f"+1 721 555 {sequence:04d}",
            "company_name": "Existing Company",
            "street_address": "1 Existing Street",
        }
        values.update(overrides)
        return Client.objects.create(**values)

    def preview(self, rows, *, headers=CLIENT_STANDARD_TEMPLATE_FIELDS):
        upload = self.upload(rows, headers=headers)
        validation = validate_client_import(upload, business=self.business)
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
        return job, preview


class ClientPreviewClassificationTests(ClientPreviewTestMixin, TestCase):
    def test_new_row_is_ready_and_authoritatively_stored(self):
        job, preview = self.preview([self.valid_row])

        self.assertTrue(preview.ready)
        self.assertEqual(preview.rows[0].status, ClientPreviewStatus.NEW)
        self.assertEqual(job.status, ImportJob.Status.READY)
        payload = database_preview_store.load(preview_binding_for_job(job))
        self.assertIsNotNone(payload)
        self.assertEqual(payload.normalized_rows[0]["client_fields"]["email"], "jane@example.com")
        self.assertNotIn("business", payload.normalized_rows[0]["client_fields"])

    def test_preview_reuses_job_already_validated_by_block_2(self):
        upload = self.upload([self.valid_row])
        parsed_validation = validate_client_import(upload, business=self.business)
        job = create_import_job(
            business=self.business,
            actor=self.user,
            import_type=ImportType.CLIENTS,
            schema_version=CLIENT_IMPORT_SCHEMA.version,
            parsed_file=parsed_validation.parsed_file,
        )
        upload.seek(0)
        validation = validate_client_import(upload, business=self.business, job=job)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.VALIDATED)

        preview = persist_client_preview(
            validation,
            job=job,
            business=self.business,
            actor=self.user,
        )
        job.refresh_from_db()

        self.assertTrue(preview.ready)
        self.assertEqual(job.status, ImportJob.Status.READY)

    def test_mixed_valid_and_error_rows_retain_csv_row_numbers(self):
        invalid = {**self.valid_row, "email": "not-an-email"}
        job, preview = self.preview([self.valid_row, invalid])

        self.assertFalse(preview.ready)
        self.assertEqual([row.row_number for row in preview.rows], [2, 3])
        self.assertEqual(
            [row.status for row in preview.rows],
            [ClientPreviewStatus.NEW, ClientPreviewStatus.ERROR],
        )
        self.assertEqual(job.status, ImportJob.Status.VALIDATED)

    def test_preview_preserves_physical_row_numbers_across_blank_lines(self):
        headers = ",".join(CLIENT_STANDARD_TEMPLATE_FIELDS)
        first = ",".join(self.valid_row.get(field, "") for field in CLIENT_STANDARD_TEMPLATE_FIELDS)
        second_values = {
            **self.valid_row,
            "email": "second@example.com",
            "phone": "+1 721 555 0101",
        }
        second = ",".join(second_values.get(field, "") for field in CLIENT_STANDARD_TEMPLATE_FIELDS)
        upload = SimpleUploadedFile(
            "clients.csv",
            f"{headers}\n{first}\n\n{second}\n".encode(),
            content_type="text/csv",
        )
        validation = validate_client_import(upload, business=self.business)

        preview = build_client_preview(validation, business=self.business)
        self.assertEqual([row.row_number for row in preview.rows], [2, 4])

    def test_same_business_email_match_is_duplicate(self):
        existing = self.existing_client(email="jane@example.com")
        _job, preview = self.preview([self.valid_row])

        row = preview.rows[0]
        self.assertEqual(row.status, ClientPreviewStatus.DUPLICATE)
        self.assertEqual(row.existing_client_id, existing.pk)
        self.assertTrue(preview.ready)

    def test_email_matching_is_case_insensitive(self):
        self.existing_client(email="JANE@EXAMPLE.COM")
        _job, preview = self.preview([{**self.valid_row, "email": "jane@example.com"}])

        self.assertEqual(preview.rows[0].status, ClientPreviewStatus.DUPLICATE)

    def test_unique_phone_candidate_requires_review(self):
        existing = self.existing_client(phone="+1 (721) 555-0100")
        _job, preview = self.preview([self.valid_row])

        self.assertEqual(preview.rows[0].status, ClientPreviewStatus.REVIEW)
        self.assertEqual(preview.rows[0].existing_client_id, existing.pk)
        self.assertFalse(preview.ready)

    def test_ambiguous_email_match_requires_review(self):
        self.existing_client(email="jane@example.com")
        self.existing_client(email="JANE@example.com")
        _job, preview = self.preview([self.valid_row])

        self.assertEqual(preview.rows[0].status, ClientPreviewStatus.REVIEW)
        self.assertEqual(preview.rows[0].issues[0].code, "ambiguous_email_match")
        self.assertFalse(preview.ready)

    def test_cross_business_match_is_ignored(self):
        other_business = Business.objects.create(name="Other", slug="other-preview")
        self.existing_client(business=other_business, email="jane@example.com")
        _job, preview = self.preview([self.valid_row])

        self.assertEqual(preview.rows[0].status, ClientPreviewStatus.NEW)

    def test_duplicate_email_rows_within_file_are_visible_and_skipped(self):
        second = {**self.valid_row, "first_name": "Janet", "email": "JANE@example.com"}
        _job, preview = self.preview([self.valid_row, second])

        self.assertEqual(preview.summary.new_count, 1)
        self.assertEqual(preview.summary.duplicate_count, 1)
        self.assertEqual(preview.rows[1].status, ClientPreviewStatus.DUPLICATE)
        self.assertEqual(preview.rows[1].duplicate_of_row, 2)
        self.assertTrue(preview.ready)

    def test_duplicate_phone_rows_within_file_require_review(self):
        second = {
            **self.valid_row,
            "email": "second@example.com",
            "phone": "+1 (721) 555-0100",
        }
        _job, preview = self.preview([self.valid_row, second])

        self.assertEqual(preview.rows[1].status, ClientPreviewStatus.REVIEW)
        self.assertFalse(preview.ready)


class ClientPreviewCapacityTests(ClientPreviewTestMixin, TestCase):
    def rows(self, count):
        return [
            {
                **self.valid_row,
                "email": f"new-{index}@example.com",
                "phone": f"+1 721 900 {index:04d}",
            }
            for index in range(count)
        ]

    def test_below_limit_is_ready(self):
        self.plan.max_clients = 3
        self.plan.save(update_fields=["max_clients"])
        _job, preview = self.preview(self.rows(2))

        self.assertTrue(preview.capacity.allowed)
        self.assertTrue(preview.ready)

    def test_exactly_at_limit_is_ready(self):
        self.existing_client()
        self.plan.max_clients = 3
        self.plan.save(update_fields=["max_clients"])
        _job, preview = self.preview(self.rows(2))

        self.assertEqual(preview.capacity.remaining_capacity, 2)
        self.assertTrue(preview.ready)

    def test_exceeding_limit_blocks_without_selecting_first_rows(self):
        self.plan.max_clients = 2
        self.plan.save(update_fields=["max_clients"])
        job, preview = self.preview(self.rows(3))

        self.assertEqual(preview.summary.new_count, 3)
        self.assertFalse(preview.capacity.allowed)
        self.assertEqual(job.status, ImportJob.Status.VALIDATED)
        self.assertTrue(all(row.status == ClientPreviewStatus.NEW for row in preview.rows))

    def test_duplicate_rows_do_not_consume_capacity(self):
        self.plan.max_clients = 2
        self.plan.save(update_fields=["max_clients"])
        self.existing_client(email="duplicate@example.com")
        rows = self.rows(2)
        rows[0]["email"] = "duplicate@example.com"
        _job, preview = self.preview(rows)

        self.assertEqual(preview.capacity.current_active_clients, 1)
        self.assertEqual(preview.capacity.new_importable_clients, 1)
        self.assertTrue(preview.ready)

    def test_unavailable_entitlement_blocks_readiness(self):
        self.plan.max_clients = None
        self.plan.save(update_fields=["max_clients"])
        job, preview = self.preview(self.rows(1))

        self.assertFalse(preview.capacity.available)
        self.assertEqual(preview.capacity.code, "client_capacity_unavailable")
        self.assertFalse(preview.ready)
        self.assertEqual(job.status, ImportJob.Status.VALIDATED)


class ClientPreviewViewSecurityTests(ClientPreviewTestMixin, TestCase):
    def login(self, user=None, business=None):
        self.client.force_login(user or self.user)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = (business or self.business).pk
        session.save()

    def post_upload(self, rows, **extra):
        data = {"csv_file": self.upload(rows), **extra}
        return self.client.post(reverse("client_import_upload"), data)

    def test_valid_upload_redirects_to_server_rendered_preview(self):
        self.login()
        response = self.post_upload([self.valid_row])

        job = ImportJob.objects.get()
        self.assertRedirects(response, reverse("client_import_preview", args=[job.pk]))
        preview_response = self.client.get(response.url)
        self.assertContains(preview_response, "Client Import Preview")
        self.assertContains(preview_response, "Ready to confirm")
        self.assertContains(preview_response, "jane@example.com")

    def test_template_download_uses_schema_header(self):
        self.login()
        response = self.client.get(reverse("client_import_template"))

        self.assertEqual(response.status_code, 200)
        header = response.content.decode().splitlines()[0]
        self.assertEqual(tuple(next(csv.reader([header]))), CLIENT_STANDARD_TEMPLATE_FIELDS)
        self.assertIn("motionmate_clients_v1.csv", response["Content-Disposition"])

    def test_wrong_user_cannot_open_preview(self):
        job, _preview = self.preview([self.valid_row])
        other_user = TaskIOUser.objects.create_user(
            email="other-preview-user@example.com", password="testpass123"
        )
        BusinessUser.objects.create(
            business=self.business,
            user=other_user,
            role=BusinessUser.Role.ADMIN,
        )
        self.login(other_user)

        response = self.client.get(reverse("client_import_preview", args=[job.pk]))
        self.assertEqual(response.status_code, 403)

    def test_wrong_business_cannot_open_preview(self):
        job, _preview = self.preview([self.valid_row])
        other_business = Business.objects.create(name="Other Access", slug="other-access")
        other_plan = ClarivoPlan.objects.create(
            name="Other Plan", slug="other-plan", max_clients=10
        )
        BusinessSubscription.objects.create(
            business=other_business,
            plan=other_plan,
            status=BusinessSubscription.Status.ACTIVE,
            current_period_end=timezone.now() + timedelta(days=30),
        )
        BusinessUser.objects.create(
            business=other_business,
            user=self.user,
            role=BusinessUser.Role.OWNER,
        )
        self.login(business=other_business)

        response = self.client.get(reverse("client_import_preview", args=[job.pk]))
        self.assertEqual(response.status_code, 403)

    def test_viewer_is_denied_upload_and_preview_routes(self):
        job, _preview = self.preview([self.valid_row])
        viewer = TaskIOUser.objects.create_user(
            email="preview-viewer@example.com", password="testpass123"
        )
        BusinessUser.objects.create(
            business=self.business,
            user=viewer,
            role=BusinessUser.Role.VIEWER,
        )
        self.login(viewer)

        for url in (
            reverse("client_import_upload"),
            reverse("client_import_template"),
            reverse("client_import_preview", args=[job.pk]),
        ):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse("agent_dashboard"))

    def test_expired_preview_is_gone(self):
        job, _preview = self.preview([self.valid_row])
        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["expires_at"])
        self.login()

        response = self.client.get(reverse("client_import_preview", args=[job.pk]))
        self.assertEqual(response.status_code, 410)
        self.assertContains(response, "expired", status_code=410)

    def test_forged_job_id_is_denied(self):
        self.login()
        response = self.client.get(reverse("client_import_preview", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, 403)

    def test_browser_cannot_post_or_replace_normalized_preview_rows(self):
        self.login()
        response = self.post_upload(
            [self.valid_row],
            business_id="999999",
            user_id="999999",
            assigned_to="999999",
            is_active="false",
            normalized_rows='[{"email":"forged@example.com"}]',
        )
        job = ImportJob.objects.get()
        payload = database_preview_store.load(preview_binding_for_job(job))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(payload.normalized_rows[0]["client_fields"]["email"], "jane@example.com")
        self.assertTrue(payload.normalized_rows[0]["client_fields"]["is_active"])
        self.assertNotIn("business_id", payload.normalized_rows[0]["client_fields"])
        post_response = self.client.post(
            reverse("client_import_preview", args=[job.pk]),
            {"normalized_rows": "forged"},
        )
        self.assertEqual(post_response.status_code, 405)

    def test_upload_and_preview_have_no_business_side_effects(self):
        self.login()
        model_counts = {
            Client: Client.objects.count(),
            Lead: Lead.objects.count(),
            BusinessService: BusinessService.objects.count(),
            ServiceCategory: ServiceCategory.objects.count(),
            Appointment: Appointment.objects.count(),
            Invoice: Invoice.objects.count(),
            ActivityLog: ActivityLog.objects.count(),
        }
        email_count = len(mail.outbox)

        response = self.post_upload([self.valid_row])
        self.client.get(response.url)

        for model, initial_count in model_counts.items():
            self.assertEqual(model.objects.count(), initial_count)
        self.assertEqual(len(mail.outbox), email_count)


class ClientPreviewStorageBindingTests(ClientPreviewTestMixin, TestCase):
    def test_store_rejects_changed_binding(self):
        job, _preview = self.preview([self.valid_row])
        binding = preview_binding_for_job(job)
        forged_binding = type(binding)(
            job_id=binding.job_id,
            business_id=binding.business_id,
            actor_id=binding.actor_id + 1000,
            schema_version=binding.schema_version,
            file_digest=binding.file_digest,
            expires_at=binding.expires_at,
        )

        self.assertIsNone(database_preview_store.load(forged_binding))

    def test_raw_csv_is_not_stored(self):
        secret_note = "raw-only-marker"
        job, _preview = self.preview([{**self.valid_row, "notes": secret_note}])

        # Normalized supported fields are stored for future execution, but there
        # is no uploaded byte stream, raw CSV text, or browser-supplied payload.
        self.assertNotIn("raw_csv", job.preview_payload)
        self.assertNotIn("uploaded_file", job.preview_payload)
