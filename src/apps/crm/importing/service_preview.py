from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.crm.models import BusinessService, ImportJob

from .permissions import user_can_import
from .preview import PreviewPayloadStore, database_preview_store, preview_binding_for_job
from .services import (
    SERVICE_BOOKING_FIELDS,
    SERVICE_IMPORT_SCHEMA,
    ServiceImportValidationResult,
    ValidatedServiceRow,
)
from .types import ImportIssue, ImportType, IssueSeverity, StoredPreviewPayload


class ServicePreviewStatus(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    ERROR = "ERROR"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class ServicePreviewRow:
    row_number: int
    status: ServicePreviewStatus
    display: dict[str, str]
    service_fields: dict[str, Any] | None
    present_fields: tuple[str, ...] = ()
    blank_fields: tuple[str, ...] = ()
    existing_service_id: int | None = None
    category: dict[str, Any] | None = None
    changes: tuple[dict[str, str], ...] = ()
    notes: tuple[str, ...] = ()
    issues: tuple[ImportIssue, ...] = ()


@dataclass(frozen=True)
class ServicePreviewSummary:
    rows_detected: int
    create_count: int
    update_count: int
    review_count: int
    warning_count: int
    error_count: int
    categories_to_create: int


@dataclass(frozen=True)
class ServicePreviewResult:
    rows: tuple[ServicePreviewRow, ...]
    file_issues: tuple[ImportIssue, ...]
    summary: ServicePreviewSummary
    ready: bool


SERVICE_FIELD_LABELS = {
    "name": "Name",
    "unit_price": "Price",
    "description": "Description",
    "tax_rate": "Tax rate",
    "is_active": "Active",
    "external_code": "External code",
    "is_bookable_online": "Bookable online",
    "default_duration_minutes": "Default duration",
    "booking_buffer_minutes": "Booking buffer",
    "public_description": "Public description",
    "requires_manual_confirmation": "Manual confirmation",
    "category": "Category",
}


def _display_value(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _category_payload(row: ValidatedServiceRow) -> dict[str, Any]:
    return {
        "label": row.category_label,
        "existing_id": row.category_id,
        "will_create": row.category_will_create,
        "key": row.category_key,
        "display": (
            f"Will create: {row.category_label}"
            if row.category_will_create
            else (row.category_label or "Uncategorized")
        ),
    }


def _changes_for_update(
    row: ValidatedServiceRow,
    existing: BusinessService,
) -> tuple[dict[str, str], ...]:
    changes: list[dict[str, str]] = []
    target_category = row.category_id
    if existing.category_id != target_category or row.category_will_create:
        changes.append(
            {
                "field": "category",
                "label": SERVICE_FIELD_LABELS["category"],
                "before": _display_value(existing.category.name if existing.category else None),
                "after": _display_value(
                    f"New category: {row.category_label}"
                    if row.category_will_create
                    else row.category_label
                ),
            }
        )

    for field_name, imported_value in row.as_service_fields().items():
        current_value = getattr(existing, field_name)
        if field_name in {"unit_price", "tax_rate"}:
            imported_value = getattr(row, field_name)
        if current_value == imported_value:
            continue
        changes.append(
            {
                "field": field_name,
                "label": SERVICE_FIELD_LABELS[field_name],
                "before": _display_value(current_value),
                "after": _display_value(imported_value),
            }
        )
    return tuple(changes)


def _booking_notes(row: ValidatedServiceRow) -> tuple[str, ...]:
    notes: list[str] = []
    fields = row.as_service_fields()
    for field_name in SERVICE_BOOKING_FIELDS:
        label = SERVICE_FIELD_LABELS[field_name]
        value = _display_value(fields[field_name])
        if field_name not in row.present_fields:
            behavior = "keeps the current value" if row.existing_service_id else f"uses {value}"
            notes.append(f"{label} omitted: {behavior}.")
        elif field_name in row.blank_fields:
            notes.append(f"{label} blank: sets {value}.")
    return tuple(notes)


def _preview_row_from_validation(row_result, *, existing_by_id) -> ServicePreviewRow:
    has_review = any(
        issue.severity == IssueSeverity.WARNING
        and issue.code in {"ambiguous_external_code", "duplicate_uploaded_external_code"}
        for issue in row_result.issues
    )
    if row_result.has_errors:
        return ServicePreviewRow(
            row_number=row_result.source_row_number,
            status=ServicePreviewStatus.ERROR,
            display=row_result.display,
            service_fields=None,
            issues=row_result.issues,
        )
    if has_review:
        validated = row_result.validated_row
        return ServicePreviewRow(
            row_number=row_result.source_row_number,
            status=ServicePreviewStatus.REVIEW,
            display=row_result.display,
            service_fields=validated.as_service_fields() if validated else None,
            present_fields=validated.present_fields if validated else (),
            blank_fields=validated.blank_fields if validated else (),
            existing_service_id=validated.existing_service_id if validated else None,
            category=_category_payload(validated) if validated else None,
            issues=row_result.issues,
        )

    validated = row_result.validated_row
    if validated is None:
        return ServicePreviewRow(
            row_number=row_result.source_row_number,
            status=ServicePreviewStatus.ERROR,
            display=row_result.display,
            service_fields=None,
            issues=row_result.issues,
        )
    status = (
        ServicePreviewStatus.UPDATE
        if validated.existing_service_id is not None
        else ServicePreviewStatus.CREATE
    )
    existing = existing_by_id.get(validated.existing_service_id)
    changes = _changes_for_update(validated, existing) if existing is not None else ()
    return ServicePreviewRow(
        row_number=row_result.source_row_number,
        status=status,
        display={
            "name": validated.name,
            "unit_price": str(validated.unit_price),
            "external_code": validated.external_code or "",
            "category": validated.category_label,
        },
        service_fields=validated.as_service_fields(),
        present_fields=validated.present_fields,
        blank_fields=validated.blank_fields,
        existing_service_id=validated.existing_service_id,
        category=_category_payload(validated),
        changes=changes,
        notes=_booking_notes(validated),
        issues=row_result.issues,
    )


def build_service_preview(validation: ServiceImportValidationResult, *, business) -> ServicePreviewResult:
    existing_ids = {
        row.validated_row.existing_service_id
        for row in validation.row_results
        if row.validated_row is not None and row.validated_row.existing_service_id is not None
    }
    existing_by_id = {
        service.pk: service
        for service in BusinessService.objects.filter(
            business=business,
            pk__in=existing_ids,
        ).select_related("category")
    }
    rows = tuple(
        _preview_row_from_validation(row_result, existing_by_id=existing_by_id)
        for row_result in validation.row_results
    )
    file_errors = sum(
        issue.severity == IssueSeverity.ERROR for issue in validation.parsed_file.issues
    )
    file_warnings = sum(
        issue.severity == IssueSeverity.WARNING for issue in validation.parsed_file.issues
    )
    proposed_categories = {
        row.category["key"]
        for row in rows
        if row.category and row.category["will_create"]
    }
    summary = ServicePreviewSummary(
        rows_detected=validation.parsed_file.rows_detected,
        create_count=sum(row.status == ServicePreviewStatus.CREATE for row in rows),
        update_count=sum(row.status == ServicePreviewStatus.UPDATE for row in rows),
        review_count=sum(row.status == ServicePreviewStatus.REVIEW for row in rows),
        warning_count=(
            sum(any(issue.severity == IssueSeverity.WARNING for issue in row.issues) for row in rows)
            + file_warnings
        ),
        error_count=sum(row.status == ServicePreviewStatus.ERROR for row in rows) + file_errors,
        categories_to_create=len(proposed_categories),
    )
    return ServicePreviewResult(
        rows=rows,
        file_issues=validation.parsed_file.issues,
        summary=summary,
        ready=summary.error_count == 0 and summary.review_count == 0 and bool(rows),
    )


def _serialize_issue(issue: ImportIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity.value,
        "row_number": issue.row_number,
        "column": issue.column,
    }


def stored_service_preview_payload(job: ImportJob, preview: ServicePreviewResult) -> StoredPreviewPayload:
    return StoredPreviewPayload(
        binding=preview_binding_for_job(job),
        normalized_rows=tuple(
            {
                "row_number": row.row_number,
                "status": row.status.value,
                "display": row.display,
                "service_fields": row.service_fields,
                "present_fields": list(row.present_fields),
                "blank_fields": list(row.blank_fields),
                "existing_service_id": row.existing_service_id,
                "category": row.category,
                "changes": list(row.changes),
                "notes": list(row.notes),
                "issues": [_serialize_issue(issue) for issue in row.issues],
            }
            for row in preview.rows
        ),
        metadata={
            "schema_version": SERVICE_IMPORT_SCHEMA.version,
            "summary": asdict(preview.summary),
            "file_issues": [_serialize_issue(issue) for issue in preview.file_issues],
            "ready": preview.ready,
        },
    )


def persist_service_preview(
    validation: ServiceImportValidationResult,
    *,
    job: ImportJob,
    business,
    actor,
    store: PreviewPayloadStore = database_preview_store,
) -> ServicePreviewResult:
    if not user_can_import(business, actor, ImportType.SERVICES):
        raise PermissionDenied("Service import access denied.")

    with transaction.atomic():
        locked_job = ImportJob.objects.select_for_update().get(pk=job.pk)
        if locked_job.business_id != business.pk or locked_job.created_by_id != actor.pk:
            raise PermissionDenied("Import job access denied.")
        if (
            locked_job.import_type != ImportType.SERVICES.value
            or locked_job.schema_version != SERVICE_IMPORT_SCHEMA.version
            or locked_job.file_digest != validation.parsed_file.file_digest
        ):
            raise ValidationError("Import job does not match the Service preview.")
        locked_job.assert_usable()
        if locked_job.status not in {
            ImportJob.Status.UPLOADED,
            ImportJob.Status.VALIDATED,
        } or locked_job.preview_payload:
            raise ValidationError("This import job has already been previewed.")

        preview = build_service_preview(validation, business=business)
        locked_job.rows_detected = preview.summary.rows_detected
        locked_job.rows_valid = preview.summary.create_count + preview.summary.update_count
        locked_job.rows_warning = preview.summary.warning_count
        locked_job.rows_error = preview.summary.error_count
        locked_job.save(
            update_fields=[
                "rows_detected",
                "rows_valid",
                "rows_warning",
                "rows_error",
                "updated_at",
            ]
        )
        store.save(stored_service_preview_payload(locked_job, preview))
        if locked_job.status == ImportJob.Status.UPLOADED:
            locked_job.transition_to(ImportJob.Status.VALIDATED)
        if preview.ready:
            locked_job.transition_to(ImportJob.Status.READY)
        return preview
