from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.businesses.business_data_purge import purge_business
from apps.businesses.models import Business, BusinessSubscription, BusinessUser, ClarivoPlan
from apps.businesses.utils import CURRENT_BUSINESS_SESSION_KEY

from .importing.client_execution import ClientImportExecutionCode, execute_client_import
from .importing.retention import (
    IMPORT_JOB_METADATA_RETENTION,
    IMPORT_PREVIEW_PAYLOAD_RETENTION,
    cleanup_import_jobs,
)
from .models import BusinessService, Client, ImportJob, Lead


class ImportHistoryTestMixin:
    def setUp(self):
        self.business = Business.objects.create(
            name="Import History Workspace",
            slug="import-history-workspace",
        )
        self.other_business = Business.objects.create(
            name="Other Import Workspace",
            slug="other-import-workspace",
        )
        plan = ClarivoPlan.objects.create(name="Import History Plan", slug="import-history-plan")
        for business in (self.business, self.other_business):
            BusinessSubscription.objects.create(
                business=business,
                plan=plan,
                status=BusinessSubscription.Status.ACTIVE,
                current_period_end=timezone.now() + timedelta(days=30),
            )
        self.owner = TaskIOUser.objects.create_user(
            email="history-owner@example.com",
            password="testpass123",
        )
        self.admin = TaskIOUser.objects.create_user(
            email="history-admin@example.com",
            password="testpass123",
        )
        self.staff = TaskIOUser.objects.create_user(
            email="history-staff@example.com",
            password="testpass123",
        )
        self.accountant = TaskIOUser.objects.create_user(
            email="history-accountant@example.com",
            password="testpass123",
        )
        for user, role in (
            (self.owner, BusinessUser.Role.OWNER),
            (self.admin, BusinessUser.Role.ADMIN),
            (self.staff, BusinessUser.Role.STAFF),
            (self.accountant, BusinessUser.Role.ACCOUNTANT),
        ):
            BusinessUser.objects.create(
                business=self.business,
                user=user,
                role=role,
            )
        BusinessUser.objects.create(
            business=self.other_business,
            user=self.owner,
            role=BusinessUser.Role.OWNER,
        )

    def login(self, user=None, business=None):
        self.client.force_login(user or self.owner)
        session = self.client.session
        session[CURRENT_BUSINESS_SESSION_KEY] = (business or self.business).pk
        session.save()

    def make_job(
        self,
        *,
        business=None,
        actor=None,
        status=ImportJob.Status.COMPLETED,
        filename="historical-clients.csv",
        preview_payload=None,
        expires_at=None,
    ):
        now = timezone.now()
        return ImportJob.objects.create(
            business=business or self.business,
            created_by=actor or self.owner,
            import_type=ImportJob.ImportType.CLIENTS,
            schema_version="1",
            original_filename=filename,
            file_digest="a" * 64,
            status=status,
            rows_detected=8,
            rows_created=5,
            rows_updated=1,
            rows_skipped=1,
            rows_error=1,
            preview_payload=preview_payload or {},
            expires_at=expires_at or now + timedelta(hours=1),
            completed_at=now if status == ImportJob.Status.COMPLETED else None,
        )


class ImportHistoryViewTests(ImportHistoryTestMixin, TestCase):
    def test_owner_sees_only_current_business_history_metadata(self):
        own_job = self.make_job(filename="workspace-history.csv")
        self.make_job(
            business=self.other_business,
            filename="foreign-history.csv",
        )
        self.login()

        response = self.client.get(reverse("import_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, own_job.original_filename)
        self.assertContains(response, self.owner.email)
        self.assertContains(response, "workspace-history.csv")
        self.assertNotContains(response, "foreign-history.csv")
        self.assertContains(response, "5")

    def test_admin_can_view_history_but_staff_and_accountant_cannot(self):
        self.make_job()
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("import_history")).status_code, 200)

        for user in (self.staff, self.accountant):
            self.login(user)
            response = self.client.get(reverse("import_history"))
            self.assertRedirects(response, reverse("agent_dashboard"))

    def test_data_import_navigation_is_owner_admin_only(self):
        history_url = reverse("import_history")
        self.login(self.owner)
        self.assertContains(self.client.get(reverse("data_import")), f'href="{history_url}"')

        self.login(self.accountant)
        self.assertNotContains(self.client.get(reverse("data_import")), f'href="{history_url}"')

    def test_terminal_detail_is_sanitized_and_never_renders_preview_payload(self):
        private_value = "private-customer@example.com"
        jobs = [
            self.make_job(
                status=status,
                filename=f"{status}.csv",
                preview_payload={
                    "normalized_rows": [{"email": private_value}],
                    "traceback": "private stack trace",
                },
            )
            for status in (
                ImportJob.Status.COMPLETED,
                ImportJob.Status.FAILED,
                ImportJob.Status.EXPIRED,
            )
        ]
        self.login()

        for job in jobs:
            response = self.client.get(reverse("import_history_detail", args=[job.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, job.original_filename)
            self.assertContains(response, "Sanitized result")
            self.assertNotContains(response, private_value)
            self.assertNotContains(response, "private stack trace")
            self.assertNotContains(response, "normalized_rows")

    def test_active_and_cross_business_job_details_are_not_exposed(self):
        active = self.make_job(status=ImportJob.Status.READY)
        foreign = self.make_job(business=self.other_business)
        self.login()

        self.assertEqual(
            self.client.get(reverse("import_history_detail", args=[active.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("import_history_detail", args=[foreign.pk])).status_code,
            404,
        )


class ImportJobRetentionTests(ImportHistoryTestMixin, TestCase):
    def test_policy_constants_are_centralized_at_24_hours_and_90_days(self):
        self.assertEqual(IMPORT_PREVIEW_PAYLOAD_RETENTION, timedelta(hours=24))
        self.assertEqual(IMPORT_JOB_METADATA_RETENTION, timedelta(days=90))

    def test_cleanup_expires_stale_usable_jobs_without_early_payload_removal(self):
        now = timezone.now()
        jobs = []
        for status in (
            ImportJob.Status.UPLOADED,
            ImportJob.Status.VALIDATED,
            ImportJob.Status.READY,
        ):
            jobs.append(
                self.make_job(
                    status=status,
                    filename=f"{status}.csv",
                    preview_payload={"normalized_rows": [{"private": status}]},
                    expires_at=now - timedelta(minutes=1),
                )
            )

        result = cleanup_import_jobs(at=now)

        self.assertEqual(result.stale_jobs_marked_expired, 3)
        self.assertEqual(result.preview_payloads_cleared, 0)
        self.assertEqual(
            set(ImportJob.objects.values_list("status", flat=True)),
            {ImportJob.Status.EXPIRED},
        )
        self.assertTrue(all(job.preview_payload for job in ImportJob.objects.all()))
        execution = execute_client_import(
            job_id=jobs[0].pk,
            business=self.business,
            actor=self.owner,
        )
        self.assertEqual(execution.code, ClientImportExecutionCode.EXPIRED)
        self.assertFalse(Client.objects.exists())

    def test_cleanup_clears_old_terminal_payloads_but_preserves_recent_payloads(self):
        now = timezone.now()
        old = now - IMPORT_PREVIEW_PAYLOAD_RETENTION - timedelta(minutes=1)
        recent = now - IMPORT_PREVIEW_PAYLOAD_RETENTION + timedelta(minutes=1)
        old_jobs = []
        recent_jobs = []
        for status in (
            ImportJob.Status.COMPLETED,
            ImportJob.Status.FAILED,
            ImportJob.Status.EXPIRED,
        ):
            old_job = self.make_job(
                status=status,
                filename=f"old-{status}.csv",
                preview_payload={"normalized_rows": [{"private": "old"}]},
                expires_at=old if status == ImportJob.Status.EXPIRED else now,
            )
            recent_job = self.make_job(
                status=status,
                filename=f"recent-{status}.csv",
                preview_payload={"normalized_rows": [{"private": "recent"}]},
                expires_at=recent if status == ImportJob.Status.EXPIRED else now,
            )
            completed_updates = (
                {"completed_at": old} if status == ImportJob.Status.COMPLETED else {}
            )
            ImportJob.objects.filter(pk=old_job.pk).update(updated_at=old, **completed_updates)
            completed_updates = (
                {"completed_at": recent} if status == ImportJob.Status.COMPLETED else {}
            )
            ImportJob.objects.filter(pk=recent_job.pk).update(
                updated_at=recent,
                **completed_updates,
            )
            old_jobs.append(old_job)
            recent_jobs.append(recent_job)

        result = cleanup_import_jobs(at=now)

        self.assertEqual(result.preview_payloads_cleared, 3)
        for job in old_jobs:
            job.refresh_from_db()
            self.assertEqual(job.preview_payload, {})
        for job in recent_jobs:
            job.refresh_from_db()
            self.assertTrue(job.preview_payload)

    def test_cleanup_deletes_metadata_after_90_days(self):
        now = timezone.now()
        old_job = self.make_job(preview_payload={"private": "old"})
        recent_job = self.make_job(filename="recent.csv")
        ImportJob.objects.filter(pk=old_job.pk).update(
            created_at=now - IMPORT_JOB_METADATA_RETENTION - timedelta(minutes=1)
        )

        result = cleanup_import_jobs(at=now)

        self.assertEqual(result.metadata_jobs_deleted, 1)
        self.assertFalse(ImportJob.objects.filter(pk=old_job.pk).exists())
        self.assertTrue(ImportJob.objects.filter(pk=recent_job.pk).exists())

    def test_dry_run_reports_without_database_writes(self):
        now = timezone.now()
        job = self.make_job(
            status=ImportJob.Status.READY,
            preview_payload={"private": "retained"},
            expires_at=now - timedelta(days=2),
        )
        output = StringIO()

        with CaptureQueriesContext(connection) as captured:
            call_command("cleanup_import_jobs", "--dry-run", stdout=output)

        write_verbs = {"DELETE", "INSERT", "UPDATE"}
        verbs = {
            query["sql"].lstrip().partition(" ")[0].upper()
            for query in captured.captured_queries
        }
        self.assertTrue(verbs.isdisjoint(write_verbs))
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.READY)
        self.assertTrue(job.preview_payload)
        self.assertIn("DRY RUN", output.getvalue())

    def test_cleanup_is_idempotent_and_can_be_scoped_to_exact_business(self):
        now = timezone.now()
        selected = self.make_job(
            status=ImportJob.Status.READY,
            expires_at=now - timedelta(days=2),
            preview_payload={"private": "selected"},
        )
        other = self.make_job(
            business=self.other_business,
            status=ImportJob.Status.READY,
            expires_at=now - timedelta(days=2),
            preview_payload={"private": "other"},
        )

        first = cleanup_import_jobs(at=now, business_id=self.business.pk)
        second = cleanup_import_jobs(at=now, business_id=self.business.pk)

        selected.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(first.stale_jobs_marked_expired, 1)
        self.assertEqual(first.preview_payloads_cleared, 1)
        self.assertEqual(selected.status, ImportJob.Status.EXPIRED)
        self.assertEqual(selected.preview_payload, {})
        self.assertEqual(other.status, ImportJob.Status.READY)
        self.assertTrue(other.preview_payload)
        self.assertEqual(second.stale_jobs_marked_expired, 0)
        self.assertEqual(second.preview_payloads_cleared, 0)
        self.assertEqual(second.metadata_jobs_deleted, 0)

    def test_cleanup_command_executes_and_is_safe_to_repeat(self):
        now = timezone.now()
        job = self.make_job(
            status=ImportJob.Status.READY,
            expires_at=now - timedelta(days=2),
            preview_payload={"private": "clear me"},
        )
        first_output = StringIO()
        second_output = StringIO()

        call_command("cleanup_import_jobs", stdout=first_output)
        call_command("cleanup_import_jobs", stdout=second_output)

        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.Status.EXPIRED)
        self.assertEqual(job.preview_payload, {})
        self.assertIn("Stale jobs to expire: 1", first_output.getvalue())
        self.assertIn("Preview payloads to clear: 1", first_output.getvalue())
        self.assertIn("Stale jobs to expire: 0", second_output.getvalue())
        self.assertIn("Preview payloads to clear: 0", second_output.getvalue())

    def test_cleanup_command_business_id_scope_is_exact(self):
        now = timezone.now()
        selected = self.make_job(
            status=ImportJob.Status.READY,
            expires_at=now - timedelta(days=2),
            preview_payload={"private": "selected"},
        )
        other = self.make_job(
            business=self.other_business,
            status=ImportJob.Status.READY,
            expires_at=now - timedelta(days=2),
            preview_payload={"private": "other"},
        )
        output = StringIO()

        call_command(
            "cleanup_import_jobs",
            "--business-id",
            str(self.business.pk),
            stdout=output,
        )

        selected.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(selected.status, ImportJob.Status.EXPIRED)
        self.assertEqual(selected.preview_payload, {})
        self.assertEqual(other.status, ImportJob.Status.READY)
        self.assertTrue(other.preview_payload)
        self.assertIn(f"business_id={self.business.pk}", output.getvalue())

    def test_cleanup_never_deletes_completed_domain_records(self):
        now = timezone.now()
        client = Client.objects.create(
            business=self.business,
            first_name="Imported",
            last_name="Client",
            email="retained-client@example.com",
            phone="+1 721 555 0100",
            company_name="Retained Client",
        )
        lead = Lead.objects.create(
            business=self.business,
            lead_type=Lead.LeadType.REQUEST,
            first_name="Imported",
            last_name="Lead",
            email="retained-lead@example.com",
            phone="+1 721 555 0101",
            company_name="Retained Lead",
        )
        service = BusinessService.objects.create(
            business=self.business,
            name="Imported Service",
            unit_price=Decimal("25.00"),
        )
        job = self.make_job()
        ImportJob.objects.filter(pk=job.pk).update(
            created_at=now - IMPORT_JOB_METADATA_RETENTION - timedelta(days=1)
        )

        cleanup_import_jobs(at=now)

        self.assertFalse(ImportJob.objects.filter(pk=job.pk).exists())
        self.assertTrue(Client.objects.filter(pk=client.pk).exists())
        self.assertTrue(Lead.objects.filter(pk=lead.pk).exists())
        self.assertTrue(BusinessService.objects.filter(pk=service.pk).exists())

    def test_business_purge_removes_import_jobs_with_preview_payloads(self):
        purge_target = Business.objects.create(
            name="Import Purge Target",
            slug="import-purge-target",
            is_active=False,
        )
        purge_owner = TaskIOUser.objects.create_user(
            email="import-purge-owner@example.com",
            password="testpass123",
        )
        BusinessUser.objects.create(
            business=purge_target,
            user=purge_owner,
            role=BusinessUser.Role.OWNER,
        )
        job = self.make_job(
            business=purge_target,
            actor=purge_owner,
            preview_payload={"normalized_rows": [{"private": "purge me"}]},
        )

        result = purge_business(
            business_id=purge_target.pk,
            reason_reference="TEST-IMPORT-HISTORY-PURGE",
        )

        self.assertTrue(result.purged)
        self.assertEqual(result.deletion_counts["import_jobs"], 1)
        self.assertFalse(ImportJob.objects.filter(pk=job.pk).exists())
        self.assertFalse(Business.objects.filter(pk=purge_target.pk).exists())
