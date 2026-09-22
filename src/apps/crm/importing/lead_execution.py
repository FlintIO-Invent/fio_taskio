from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.businesses.models import Business, BusinessUser
from apps.businesses.utils import LEAD_MANAGE_ROLES
from apps.crm.models import ImportJob, Lead, ServiceCategory

from .lead_preview import LeadPreviewStatus, classify_validated_lead_rows
from .leads import (
    LEAD_ALLOWED_STATUSES,
    LEAD_IMPORT_SCHEMA,
    ValidatedLeadRow,
    resolve_lead_category,
)
from .preview import PreviewPayloadStore, database_preview_store, preview_binding_for_job
from .types import ImportType


class LeadImportExecutionCode(StrEnum):
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"
    EXPIRED = "expired"
    NOT_READY = "not_ready"
    DUPLICATES_CHANGED = "duplicates_changed"
    CATEGORY_CHANGED = "category_changed"
    PREVIEW_INVALID = "preview_invalid"
    FAILED = "failed"


@dataclass(frozen=True)
class LeadImportExecutionResult:
    code: LeadImportExecutionCode
    message: str
    leads_created: int = 0
    duplicates_skipped: int = 0
    total_processed: int = 0
    completed: bool = False


TRUSTED_LEAD_FIELD_NAMES = frozenset(
    field.name
    for field in fields(ValidatedLeadRow)
    if field.name not in {"source_row_number", "category_label", "category_id"}
)


class InvalidStoredLeadPreview(ValueError):
    pass


class LeadDuplicateStateChanged(ValueError):
    pass


class LeadCategoryStateChanged(ValueError):
    pass


def _result(
    code: LeadImportExecutionCode,
    message: str,
    *,
    leads_created: int = 0,
    duplicates_skipped: int = 0,
    completed: bool = False,
) -> LeadImportExecutionResult:
    return LeadImportExecutionResult(
        code=code,
        message=message,
        leads_created=leads_created,
        duplicates_skipped=duplicates_skipped,
        total_processed=leads_created + duplicates_skipped,
        completed=completed,
    )


def _record_execution_result(job: ImportJob, result: LeadImportExecutionResult) -> None:
    payload = dict(job.preview_payload) if isinstance(job.preview_payload, dict) else {}
    payload["execution_result"] = {**asdict(result), "code": result.code.value}
    job.preview_payload = payload
    job.save(update_fields=["preview_payload", "updated_at"])


def _fail_ready_job(
    job: ImportJob,
    code: LeadImportExecutionCode,
    message: str,
) -> LeadImportExecutionResult:
    result = _result(code, message)
    _record_execution_result(job, result)
    job.transition_to(ImportJob.Status.FAILED)
    return result


def _validate_lead_fields(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != TRUSTED_LEAD_FIELD_NAMES:
        raise InvalidStoredLeadPreview("Stored Lead fields do not match the allowlist.")
    lead_fields = dict(value)
    string_fields = TRUSTED_LEAD_FIELD_NAMES - {"consent_to_contact"}
    if any(not isinstance(lead_fields[field_name], str) for field_name in string_fields):
        raise InvalidStoredLeadPreview("Stored Lead text fields are invalid.")
    if type(lead_fields["consent_to_contact"]) is not bool:
        raise InvalidStoredLeadPreview("Stored Lead consent is invalid.")
    if lead_fields["lead_type"] not in {Lead.LeadType.REQUEST, Lead.LeadType.INTEREST}:
        raise InvalidStoredLeadPreview("Stored Lead type is not import-safe.")
    if lead_fields["status"] not in LEAD_ALLOWED_STATUSES:
        raise InvalidStoredLeadPreview("Stored Lead status is not import-safe.")
    return lead_fields


def _trusted_rows(payload, job: ImportJob) -> tuple[tuple[ValidatedLeadRow, ...], int]:
    metadata = payload.metadata
    if metadata.get("schema_version") != LEAD_IMPORT_SCHEMA.version:
        raise InvalidStoredLeadPreview("Stored Lead preview schema does not match.")
    if metadata.get("ready") is not True:
        raise InvalidStoredLeadPreview("Stored Lead preview is not ready.")

    approved: list[ValidatedLeadRow] = []
    approved_row_numbers: set[int] = set()
    duplicate_count = 0
    for stored in payload.normalized_rows:
        row_number = stored.get("row_number")
        if type(row_number) is not int or row_number < 1:
            raise InvalidStoredLeadPreview("Stored Lead row number is invalid.")
        try:
            status = LeadPreviewStatus(stored.get("status"))
        except ValueError as exc:
            raise InvalidStoredLeadPreview("Stored Lead classification is invalid.") from exc
        if status not in {LeadPreviewStatus.NEW, LeadPreviewStatus.DUPLICATE}:
            raise InvalidStoredLeadPreview("Stored Lead preview contains a blocking row.")

        lead_fields = _validate_lead_fields(stored.get("lead_fields"))
        category_id = stored.get("category_id")
        category_label = stored.get("category_label")
        if category_id is not None and type(category_id) is not int:
            raise InvalidStoredLeadPreview("Stored Lead category target is invalid.")
        if not isinstance(category_label, str):
            raise InvalidStoredLeadPreview("Stored Lead category label is invalid.")
        if bool(category_label) != (category_id is not None):
            raise InvalidStoredLeadPreview("Stored Lead category binding is invalid.")

        if status == LeadPreviewStatus.DUPLICATE:
            duplicate_of_row = stored.get("duplicate_of_row")
            if type(duplicate_of_row) is not int or duplicate_of_row not in approved_row_numbers:
                raise InvalidStoredLeadPreview("Stored Lead duplicate target is invalid.")
            duplicate_count += 1
            continue
        if stored.get("duplicate_of_row") is not None:
            raise InvalidStoredLeadPreview("Stored Lead row has an unexpected duplicate target.")

        approved.append(
            ValidatedLeadRow(
                source_row_number=row_number,
                category_label=category_label,
                category_id=category_id,
                **lead_fields,
            )
        )
        approved_row_numbers.add(row_number)

    summary = metadata.get("summary")
    if not isinstance(summary, dict):
        raise InvalidStoredLeadPreview("Stored Lead summary is missing.")
    if summary.get("ready_count") != len(approved):
        raise InvalidStoredLeadPreview("Stored Lead ready count does not match.")
    if summary.get("duplicate_count") != duplicate_count:
        raise InvalidStoredLeadPreview("Stored Lead duplicate count does not match.")
    if job.rows_valid != len(approved):
        raise InvalidStoredLeadPreview("Import job Lead count does not match its preview.")
    return tuple(approved), duplicate_count


def _locked_membership_allows_import(*, business, actor) -> bool:
    membership = (
        BusinessUser.objects.select_for_update()
        .filter(business=business, user=actor, is_active=True)
        .first()
    )
    return bool(membership and membership.role in LEAD_MANAGE_ROLES)


def _recheck_categories(rows: tuple[ValidatedLeadRow, ...], *, business) -> None:
    list(
        ServiceCategory.objects.select_for_update()
        .filter(Q(business=business) | Q(business__isnull=True))
        .values_list("pk", flat=True)
    )
    checked: set[tuple[str, int]] = set()
    for row in rows:
        if row.category_id is None:
            continue
        binding = (row.category_label.casefold(), row.category_id)
        if binding in checked:
            continue
        checked.add(binding)
        try:
            current = resolve_lead_category(business=business, label=row.category_label)
        except ValidationError as exc:
            raise LeadCategoryStateChanged from exc
        if current is None or current.pk != row.category_id:
            raise LeadCategoryStateChanged


def _recheck_duplicates(rows: tuple[ValidatedLeadRow, ...], *, business) -> None:
    list(
        Lead.objects.select_for_update()
        .filter(business=business)
        .values_list("pk", flat=True)
    )
    reclassified = classify_validated_lead_rows(rows, business=business)
    if any(row.status != LeadPreviewStatus.NEW for row in reclassified.values()):
        raise LeadDuplicateStateChanged


def _create_lead(row: ValidatedLeadRow, *, business) -> Lead:
    category = None
    if row.category_id is not None:
        category = ServiceCategory.objects.get(pk=row.category_id)
    lead = Lead(
        business=business,
        category=category,
        requested_service=None,
        preferred_start_time=None,
        preferred_end_time=None,
        request_source=Lead.RequestSource.OTHER,
        is_active=True,
        **row.as_lead_fields(),
    )
    lead.full_clean()
    lead.save()
    return lead


def execute_lead_import(
    *,
    job_id,
    business,
    actor,
    store: PreviewPayloadStore = database_preview_store,
) -> LeadImportExecutionResult:
    """Atomically create private historical Leads from a bound server preview."""

    if (
        business is None
        or not getattr(actor, "is_authenticated", False)
        or not getattr(business, "is_active", False)
    ):
        raise PermissionDenied("Lead import access denied.")

    with transaction.atomic():
        # Stable lock order: Business, membership, ImportJob, Leads, categories.
        locked_business = Business.objects.select_for_update().get(pk=business.pk)
        if not locked_business.is_active or not _locked_membership_allows_import(
            business=locked_business,
            actor=actor,
        ):
            raise PermissionDenied("Lead import access denied.")

        job = ImportJob.objects.select_for_update().filter(pk=job_id).first()
        if (
            job is None
            or job.business_id != locked_business.pk
            or job.created_by_id != actor.pk
            or job.import_type != ImportType.LEADS.value
            or job.schema_version != LEAD_IMPORT_SCHEMA.version
        ):
            raise PermissionDenied("Import job access denied.")

        if job.status == ImportJob.Status.COMPLETED:
            result = _result(
                LeadImportExecutionCode.ALREADY_COMPLETED,
                "This Lead import was already completed.",
                leads_created=job.rows_created,
                duplicates_skipped=job.rows_skipped,
                completed=True,
            )
            _record_execution_result(job, result)
            return result
        if job.expires_at <= timezone.now() or job.status == ImportJob.Status.EXPIRED:
            result = _result(
                LeadImportExecutionCode.EXPIRED,
                "This Lead import preview has expired. Create a new preview.",
            )
            _record_execution_result(job, result)
            if job.status == ImportJob.Status.READY:
                job.transition_to(ImportJob.Status.EXPIRED)
            return result
        if job.status != ImportJob.Status.READY:
            return _result(
                LeadImportExecutionCode.NOT_READY,
                "This Lead import is not ready. Create a new preview.",
            )

        try:
            with transaction.atomic():
                payload = store.load(preview_binding_for_job(job))
                if payload is None:
                    raise InvalidStoredLeadPreview("Stored preview binding did not match.")
                rows, duplicate_count = _trusted_rows(payload, job)
                _recheck_duplicates(rows, business=locked_business)
                _recheck_categories(rows, business=locked_business)
                for row in rows:
                    _create_lead(row, business=locked_business)
        except InvalidStoredLeadPreview:
            return _fail_ready_job(
                job,
                LeadImportExecutionCode.PREVIEW_INVALID,
                "The stored Lead preview could not be verified. Create a new preview.",
            )
        except LeadDuplicateStateChanged:
            return _fail_ready_job(
                job,
                LeadImportExecutionCode.DUPLICATES_CHANGED,
                "Lead duplicates changed after preview. Create a new preview.",
            )
        except LeadCategoryStateChanged:
            return _fail_ready_job(
                job,
                LeadImportExecutionCode.CATEGORY_CHANGED,
                "Lead categories changed after preview. Create a new preview.",
            )
        except Exception:
            return _fail_ready_job(
                job,
                LeadImportExecutionCode.FAILED,
                "The Lead import failed safely. No Leads were created.",
            )

        result = _result(
            LeadImportExecutionCode.COMPLETED,
            "Lead import complete.",
            leads_created=len(rows),
            duplicates_skipped=duplicate_count,
            completed=True,
        )
        job.rows_created = result.leads_created
        job.rows_skipped = result.duplicates_skipped
        job.save(update_fields=["rows_created", "rows_skipped", "updated_at"])
        _record_execution_result(job, result)
        job.transition_to(ImportJob.Status.COMPLETED)
        return result


def lead_execution_result_from_job(job: ImportJob) -> LeadImportExecutionResult:
    payload = job.preview_payload if isinstance(job.preview_payload, dict) else {}
    stored = payload.get("execution_result", {})
    try:
        return LeadImportExecutionResult(
            code=LeadImportExecutionCode(stored["code"]),
            message=str(stored["message"]),
            leads_created=int(stored.get("leads_created", 0)),
            duplicates_skipped=int(stored.get("duplicates_skipped", 0)),
            total_processed=int(stored.get("total_processed", 0)),
            completed=bool(stored.get("completed", False)),
        )
    except (KeyError, TypeError, ValueError):
        if job.status == ImportJob.Status.COMPLETED:
            return _result(
                LeadImportExecutionCode.ALREADY_COMPLETED,
                "This Lead import was already completed.",
                leads_created=job.rows_created,
                duplicates_skipped=job.rows_skipped,
                completed=True,
            )
        if job.status == ImportJob.Status.EXPIRED or job.is_expired:
            return _result(
                LeadImportExecutionCode.EXPIRED,
                "This Lead import preview has expired. Create a new preview.",
            )
        if job.status == ImportJob.Status.FAILED:
            return _result(
                LeadImportExecutionCode.FAILED,
                "The Lead import failed safely. No Leads were created.",
            )
        return _result(
            LeadImportExecutionCode.NOT_READY,
            "This Lead import has not been completed.",
        )
