from __future__ import annotations

from datetime import timedelta
from pathlib import PurePath

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.crm.models import ImportJob

from .types import ImportType, ParsedImportFile


def create_import_job(
    *,
    business,
    actor,
    import_type: ImportType | str,
    schema_version: str,
    parsed_file: ParsedImportFile,
    lifetime: timedelta = timedelta(hours=24),
) -> ImportJob:
    """Persist metadata only; normalized rows remain outside this model."""

    return ImportJob.objects.create(
        business=business,
        created_by=actor,
        import_type=ImportType(import_type).value,
        schema_version=schema_version,
        original_filename=PurePath(parsed_file.original_filename).name[:255],
        file_digest=parsed_file.file_digest,
        rows_detected=parsed_file.rows_detected,
        rows_warning=parsed_file.warning_count,
        rows_error=sum(issue.severity.value == "error" for issue in parsed_file.issues),
        expires_at=timezone.now() + lifetime,
    )


def get_import_job_for_owner(
    *,
    job_id,
    business,
    actor,
    require_usable: bool = True,
) -> ImportJob:
    """Return only the current actor's job in the explicitly supplied tenant."""

    if not getattr(actor, "is_authenticated", False) or business is None:
        raise PermissionDenied("Import job access denied.")

    job = ImportJob.objects.filter(
        pk=job_id,
        business=business,
        created_by=actor,
    ).first()
    if job is None:
        raise PermissionDenied("Import job access denied.")
    if require_usable:
        job.assert_usable()
    return job


def get_confirmable_import_job_for_owner(*, job_id, business, actor) -> ImportJob:
    """Resolve an owner-bound, unexpired READY job for a future commit request."""

    job = get_import_job_for_owner(job_id=job_id, business=business, actor=actor)
    job.assert_confirmable()
    return job
