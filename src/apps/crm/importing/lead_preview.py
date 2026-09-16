from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.crm.models import Client, ImportJob, Lead

from .leads import LEAD_IMPORT_SCHEMA, LeadImportValidationResult, ValidatedLeadRow
from .permissions import user_can_import
from .preview import PreviewPayloadStore, database_preview_store, preview_binding_for_job
from .types import ImportIssue, ImportType, IssueSeverity, StoredPreviewPayload


class LeadPreviewStatus(StrEnum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    REVIEW = "REVIEW"
    ERROR = "ERROR"


@dataclass(frozen=True)
class LeadPreviewRow:
    row_number: int
    status: LeadPreviewStatus
    display: dict[str, str]
    lead_fields: dict[str, Any] | None
    category_id: int | None = None
    category_label: str = ""
    issues: tuple[ImportIssue, ...] = ()
    duplicate_of_row: int | None = None
    matching_lead_ids: tuple[int, ...] = ()
    matching_client_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class LeadPreviewSummary:
    rows_detected: int
    ready_count: int
    duplicate_count: int
    review_count: int
    warning_count: int
    error_count: int


@dataclass(frozen=True)
class LeadPreviewResult:
    rows: tuple[LeadPreviewRow, ...]
    file_issues: tuple[ImportIssue, ...]
    summary: LeadPreviewSummary
    ready: bool


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().casefold()


def _normalized_phone(value: str | None) -> str:
    return "".join(character for character in (value or "") if character.isdigit())


def _normalized_text(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def _fingerprint(row: ValidatedLeadRow) -> tuple[Any, ...]:
    return (
        row.lead_type,
        _normalized_text(row.first_name),
        _normalized_text(row.last_name),
        _normalized_email(row.email),
        _normalized_phone(row.phone),
        _normalized_text(row.company_name),
        row.status,
        row.category_id,
        _normalized_text(row.street_address),
        _normalized_text(row.district),
        _normalized_text(row.country),
        _normalized_text(row.postal_code),
        _normalized_text(row.message),
        _normalized_text(row.notes),
        row.consent_to_contact,
    )


def _contact_indexes(queryset) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    emails: dict[str, list[int]] = defaultdict(list)
    phones: dict[str, list[int]] = defaultdict(list)
    for record_id, email, phone in queryset.values_list("pk", "email", "phone"):
        normalized_email = _normalized_email(email)
        normalized_phone = _normalized_phone(phone)
        if normalized_email:
            emails[normalized_email].append(record_id)
        if normalized_phone:
            phones[normalized_phone].append(record_id)
    return dict(emails), dict(phones)


def _issue(
    *,
    row_number: int,
    code: str,
    message: str,
    severity: IssueSeverity = IssueSeverity.WARNING,
) -> ImportIssue:
    return ImportIssue(
        row_number=row_number,
        code=code,
        message=message,
        severity=severity,
    )


def _display(row: ValidatedLeadRow) -> dict[str, str]:
    return {
        "lead_type": row.lead_type,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "email": row.email,
        "phone": row.phone,
        "category": row.category_label,
    }


def classify_validated_lead_rows(
    validated_rows: tuple[ValidatedLeadRow, ...],
    *,
    business,
) -> dict[int, LeadPreviewRow]:
    existing_lead_emails, existing_lead_phones = _contact_indexes(
        Lead.objects.filter(business=business)
    )
    client_emails, client_phones = _contact_indexes(Client.objects.filter(business=business))
    uploaded_fingerprints: dict[tuple[Any, ...], int] = {}
    uploaded_emails: dict[str, int] = {}
    uploaded_phones: dict[str, int] = {}
    classified: dict[int, LeadPreviewRow] = {}

    for row in validated_rows:
        fingerprint = _fingerprint(row)
        email = _normalized_email(row.email)
        phone = _normalized_phone(row.phone)
        issues: list[ImportIssue] = []
        status = LeadPreviewStatus.NEW
        duplicate_of_row = uploaded_fingerprints.get(fingerprint)

        if duplicate_of_row is not None:
            status = LeadPreviewStatus.DUPLICATE
            issues.append(
                _issue(
                    row_number=row.source_row_number,
                    code="exact_uploaded_duplicate",
                    message=(
                        f"Exactly matches uploaded row {duplicate_of_row} and will be skipped."
                    ),
                )
            )
        else:
            uploaded_fingerprints[fingerprint] = row.source_row_number
            uploaded_contact_row = uploaded_emails.get(email) if email else None
            if uploaded_contact_row is None and phone:
                uploaded_contact_row = uploaded_phones.get(phone)
            if uploaded_contact_row is not None:
                status = LeadPreviewStatus.REVIEW
                issues.append(
                    _issue(
                        row_number=row.source_row_number,
                        code="near_duplicate_in_upload",
                        message=(
                            f"Shares contact details with uploaded row {uploaded_contact_row} "
                            "and requires review."
                        ),
                    )
                )
            if email:
                uploaded_emails.setdefault(email, row.source_row_number)
            if phone:
                uploaded_phones.setdefault(phone, row.source_row_number)

        matching_lead_ids = sorted(
            set(existing_lead_emails.get(email, []))
            | set(existing_lead_phones.get(phone, []) if phone else [])
        )
        if status != LeadPreviewStatus.DUPLICATE and matching_lead_ids:
            status = LeadPreviewStatus.REVIEW
            issues.append(
                _issue(
                    row_number=row.source_row_number,
                    code="existing_lead_match",
                    message=(
                        "Matches an existing Lead in this workspace by email or phone. "
                        "No merge or update will occur."
                    ),
                )
            )

        matching_client_ids = sorted(
            set(client_emails.get(email, []))
            | set(client_phones.get(phone, []) if phone else [])
        )
        if matching_client_ids:
            issues.append(
                _issue(
                    row_number=row.source_row_number,
                    code="existing_client_match",
                    message=(
                        "Matches an existing Client in this workspace. The Lead remains "
                        "separate and no conversion will occur."
                    ),
                )
            )

        classified[row.source_row_number] = LeadPreviewRow(
            row_number=row.source_row_number,
            status=status,
            display=_display(row),
            lead_fields=row.as_lead_fields(),
            category_id=row.category_id,
            category_label=row.category_label,
            issues=tuple(issues),
            duplicate_of_row=duplicate_of_row,
            matching_lead_ids=tuple(matching_lead_ids),
            matching_client_ids=tuple(matching_client_ids),
        )
    return classified


def build_lead_preview(validation: LeadImportValidationResult, *, business) -> LeadPreviewResult:
    validated_rows = tuple(
        row.validated_row
        for row in validation.row_results
        if row.validated_row is not None
    )
    classified = classify_validated_lead_rows(validated_rows, business=business)

    for row_result in validation.row_results:
        if row_result.validated_row is not None:
            classified[row_result.source_row_number] = replace(
                classified[row_result.source_row_number],
                issues=(
                    row_result.issues
                    + classified[row_result.source_row_number].issues
                ),
            )
            continue
        is_review = any(issue.code == "ambiguous_category" for issue in row_result.issues)
        classified[row_result.source_row_number] = LeadPreviewRow(
            row_number=row_result.source_row_number,
            status=LeadPreviewStatus.REVIEW if is_review else LeadPreviewStatus.ERROR,
            display=row_result.display,
            lead_fields=None,
            category_label=row_result.display.get("category", ""),
            issues=row_result.issues,
        )

    rows = tuple(classified[row_number] for row_number in sorted(classified))
    file_errors = sum(
        issue.severity == IssueSeverity.ERROR for issue in validation.parsed_file.issues
    )
    file_warnings = sum(
        issue.severity == IssueSeverity.WARNING for issue in validation.parsed_file.issues
    )
    summary = LeadPreviewSummary(
        rows_detected=validation.parsed_file.rows_detected,
        ready_count=sum(row.status == LeadPreviewStatus.NEW for row in rows),
        duplicate_count=sum(row.status == LeadPreviewStatus.DUPLICATE for row in rows),
        review_count=sum(row.status == LeadPreviewStatus.REVIEW for row in rows),
        warning_count=(
            sum(any(issue.severity == IssueSeverity.WARNING for issue in row.issues) for row in rows)
            + file_warnings
        ),
        error_count=sum(row.status == LeadPreviewStatus.ERROR for row in rows) + file_errors,
    )
    return LeadPreviewResult(
        rows=rows,
        file_issues=validation.parsed_file.issues,
        summary=summary,
        ready=summary.review_count == 0 and summary.error_count == 0 and bool(rows),
    )


def _serialize_issue(issue: ImportIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity.value,
        "row_number": issue.row_number,
        "column": issue.column,
    }


def stored_lead_preview_payload(job: ImportJob, preview: LeadPreviewResult) -> StoredPreviewPayload:
    return StoredPreviewPayload(
        binding=preview_binding_for_job(job),
        normalized_rows=tuple(
            {
                "row_number": row.row_number,
                "status": row.status.value,
                "display": row.display,
                "lead_fields": row.lead_fields,
                "category_id": row.category_id,
                "category_label": row.category_label,
                "issues": [_serialize_issue(issue) for issue in row.issues],
                "duplicate_of_row": row.duplicate_of_row,
                "matching_lead_ids": list(row.matching_lead_ids),
                "matching_client_ids": list(row.matching_client_ids),
            }
            for row in preview.rows
        ),
        metadata={
            "schema_version": LEAD_IMPORT_SCHEMA.version,
            "summary": asdict(preview.summary),
            "file_issues": [_serialize_issue(issue) for issue in preview.file_issues],
            "ready": preview.ready,
        },
    )


def persist_lead_preview(
    validation: LeadImportValidationResult,
    *,
    job: ImportJob,
    business,
    actor,
    store: PreviewPayloadStore = database_preview_store,
) -> LeadPreviewResult:
    if not user_can_import(business, actor, ImportType.LEADS):
        raise PermissionDenied("Lead import access denied.")

    with transaction.atomic():
        locked_job = ImportJob.objects.select_for_update().get(pk=job.pk)
        if locked_job.business_id != business.pk or locked_job.created_by_id != actor.pk:
            raise PermissionDenied("Import job access denied.")
        if (
            locked_job.import_type != ImportType.LEADS.value
            or locked_job.schema_version != LEAD_IMPORT_SCHEMA.version
            or locked_job.file_digest != validation.parsed_file.file_digest
        ):
            raise ValidationError("Import job does not match the Lead preview.")
        locked_job.assert_usable()
        if locked_job.status not in {
            ImportJob.Status.UPLOADED,
            ImportJob.Status.VALIDATED,
        } or locked_job.preview_payload:
            raise ValidationError("This import job has already been previewed.")

        preview = build_lead_preview(validation, business=business)
        locked_job.rows_detected = preview.summary.rows_detected
        locked_job.rows_valid = preview.summary.ready_count
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
        store.save(stored_lead_preview_payload(locked_job, preview))
        if locked_job.status == ImportJob.Status.UPLOADED:
            locked_job.transition_to(ImportJob.Status.VALIDATED)
        if preview.ready:
            locked_job.transition_to(ImportJob.Status.READY)
        return preview
