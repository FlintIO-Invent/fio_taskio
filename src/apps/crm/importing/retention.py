from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.crm.models import ImportJob

IMPORT_PREVIEW_PAYLOAD_RETENTION = timedelta(hours=24)
IMPORT_JOB_METADATA_RETENTION = timedelta(days=90)

USABLE_IMPORT_JOB_STATUSES = (
    ImportJob.Status.UPLOADED,
    ImportJob.Status.VALIDATED,
    ImportJob.Status.READY,
)


@dataclass(frozen=True, slots=True)
class ImportJobCleanupPlan:
    stale_job_ids: tuple[object, ...]
    preview_cleanup_job_ids: tuple[object, ...]
    metadata_deletion_job_ids: tuple[object, ...]

    @property
    def stale_jobs(self) -> int:
        return len(self.stale_job_ids)

    @property
    def preview_payloads(self) -> int:
        return len(self.preview_cleanup_job_ids)

    @property
    def metadata_jobs(self) -> int:
        return len(self.metadata_deletion_job_ids)


@dataclass(frozen=True, slots=True)
class ImportJobCleanupResult:
    stale_jobs_marked_expired: int
    preview_payloads_cleared: int
    metadata_jobs_deleted: int
    dry_run: bool


def _scoped_jobs(*, business_id: int | None = None):
    jobs = ImportJob.objects.all()
    if business_id is not None:
        if business_id <= 0:
            raise ValueError("business_id must be a positive integer.")
        jobs = jobs.filter(business_id=business_id)
    return jobs


def build_import_job_cleanup_plan(
    *,
    at=None,
    business_id: int | None = None,
) -> ImportJobCleanupPlan:
    checked_at = at or timezone.now()
    payload_cutoff = checked_at - IMPORT_PREVIEW_PAYLOAD_RETENTION
    metadata_cutoff = checked_at - IMPORT_JOB_METADATA_RETENTION
    jobs = _scoped_jobs(business_id=business_id)

    metadata_ids = tuple(
        jobs.filter(created_at__lte=metadata_cutoff)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    retained_jobs = jobs.exclude(pk__in=metadata_ids)
    stale_ids = tuple(
        retained_jobs.filter(
            status__in=USABLE_IMPORT_JOB_STATUSES,
            expires_at__lte=checked_at,
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )

    terminal_payload_filter = (
        Q(status=ImportJob.Status.EXPIRED, expires_at__lte=payload_cutoff)
        | Q(status=ImportJob.Status.COMPLETED, completed_at__lte=payload_cutoff)
        | Q(
            status=ImportJob.Status.COMPLETED,
            completed_at__isnull=True,
            updated_at__lte=payload_cutoff,
        )
        | Q(status=ImportJob.Status.FAILED, updated_at__lte=payload_cutoff)
    )
    preview_ids = set(
        retained_jobs.exclude(preview_payload={})
        .filter(terminal_payload_filter)
        .values_list("pk", flat=True)
    )
    # A usable job whose expiry is already beyond the payload grace period is
    # both expired and scrubbed in the same cleanup run.
    preview_ids.update(
        retained_jobs.exclude(preview_payload={})
        .filter(
            pk__in=stale_ids,
            expires_at__lte=payload_cutoff,
        )
        .values_list("pk", flat=True)
    )

    return ImportJobCleanupPlan(
        stale_job_ids=stale_ids,
        preview_cleanup_job_ids=tuple(sorted(preview_ids, key=str)),
        metadata_deletion_job_ids=metadata_ids,
    )


def cleanup_import_jobs(
    *,
    at=None,
    business_id: int | None = None,
    dry_run: bool = False,
) -> ImportJobCleanupResult:
    checked_at = at or timezone.now()
    if dry_run:
        plan = build_import_job_cleanup_plan(at=checked_at, business_id=business_id)
        return ImportJobCleanupResult(
            stale_jobs_marked_expired=plan.stale_jobs,
            preview_payloads_cleared=plan.preview_payloads,
            metadata_jobs_deleted=plan.metadata_jobs,
            dry_run=True,
        )

    with transaction.atomic():
        initial_plan = build_import_job_cleanup_plan(
            at=checked_at,
            business_id=business_id,
        )
        candidate_ids = (
            initial_plan.stale_job_ids
            + initial_plan.preview_cleanup_job_ids
            + initial_plan.metadata_deletion_job_ids
        )
        if candidate_ids:
            list(
                ImportJob.objects.select_for_update()
                .filter(pk__in=candidate_ids)
                .values_list("pk", flat=True)
            )
        plan = build_import_job_cleanup_plan(at=checked_at, business_id=business_id)

        stale_count = ImportJob.objects.filter(pk__in=plan.stale_job_ids).update(
            status=ImportJob.Status.EXPIRED,
            updated_at=checked_at,
        )
        preview_count = ImportJob.objects.filter(
            pk__in=plan.preview_cleanup_job_ids
        ).update(
            preview_payload={},
            updated_at=checked_at,
        )
        metadata_jobs = ImportJob.objects.filter(pk__in=plan.metadata_deletion_job_ids)
        metadata_count = metadata_jobs.count()
        metadata_jobs.delete()

    return ImportJobCleanupResult(
        stale_jobs_marked_expired=stale_count,
        preview_payloads_cleared=preview_count,
        metadata_jobs_deleted=metadata_count,
        dry_run=False,
    )
