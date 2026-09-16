from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.businesses.utils import (
    get_business_plan_limit,
    get_business_subscription,
    get_business_usage_count,
)
from apps.crm.models import Client, ImportJob

from .clients import CLIENT_IMPORT_SCHEMA, ClientImportValidationResult, ValidatedClientRow
from .permissions import check_import_capacity, user_can_import
from .preview import PreviewPayloadStore, database_preview_store, preview_binding_for_job
from .types import (
    ImportAccessDecision,
    ImportIssue,
    ImportType,
    IssueSeverity,
    StoredPreviewPayload,
)


class ClientPreviewStatus(StrEnum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    REVIEW = "REVIEW"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ClientCapacityProjection:
    available: bool
    allowed: bool
    code: str
    message: str
    current_active_clients: int
    plan_limit: int | None
    remaining_capacity: int | None
    new_importable_clients: int


@dataclass(frozen=True)
class ClientPreviewRow:
    row_number: int
    status: ClientPreviewStatus
    display: dict[str, str]
    client_fields: dict[str, Any] | None
    issues: tuple[ImportIssue, ...] = ()
    existing_client_id: int | None = None
    duplicate_of_row: int | None = None


@dataclass(frozen=True)
class ClientPreviewSummary:
    rows_detected: int
    new_count: int
    duplicate_count: int
    review_count: int
    warning_count: int
    error_count: int


@dataclass(frozen=True)
class ClientPreviewResult:
    rows: tuple[ClientPreviewRow, ...]
    file_issues: tuple[ImportIssue, ...]
    summary: ClientPreviewSummary
    capacity: ClientCapacityProjection
    ready: bool


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().casefold()


def _normalized_phone(value: str | None) -> str:
    return "".join(character for character in (value or "").strip() if character.isdigit())


def _issue(
    code: str,
    message: str,
    *,
    row_number: int,
    severity: IssueSeverity = IssueSeverity.WARNING,
) -> ImportIssue:
    return ImportIssue(
        code=code,
        message=message,
        severity=severity,
        row_number=row_number,
    )


def _display_values(values: dict[str, Any]) -> dict[str, str]:
    return {
        "first_name": str(values.get("first_name") or "").strip(),
        "last_name": str(values.get("last_name") or "").strip(),
        "email": str(values.get("email") or "").strip(),
        "phone": str(values.get("phone") or "").strip(),
    }


def _existing_client_indexes(business) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    emails: dict[str, list[int]] = defaultdict(list)
    phones: dict[str, list[int]] = defaultdict(list)
    for client_id, email, phone in Client.objects.filter(business=business).values_list(
        "pk", "email", "phone"
    ):
        normalized_email = _normalized_email(email)
        normalized_phone = _normalized_phone(phone)
        if normalized_email:
            emails[normalized_email].append(client_id)
        if normalized_phone:
            phones[normalized_phone].append(client_id)
    return dict(emails), dict(phones)


def classify_validated_client_rows(
    validated_rows: tuple[ValidatedClientRow, ...],
    *,
    business,
) -> dict[int, ClientPreviewRow]:
    existing_emails, existing_phones = _existing_client_indexes(business)
    uploaded_emails: dict[str, int] = {}
    uploaded_phones: dict[str, int] = {}
    classified: dict[int, ClientPreviewRow] = {}

    for row in validated_rows:
        client_fields = row.as_client_fields()
        display = _display_values(client_fields)
        normalized_email = _normalized_email(row.email)
        normalized_phone = _normalized_phone(row.phone)
        status = ClientPreviewStatus.NEW
        issues: list[ImportIssue] = []
        existing_client_id = None
        duplicate_of_row = None

        if normalized_email and normalized_email in uploaded_emails:
            status = ClientPreviewStatus.DUPLICATE
            duplicate_of_row = uploaded_emails[normalized_email]
            issues.append(
                _issue(
                    "uploaded_email_duplicate",
                    f"Matches uploaded row {duplicate_of_row} by email and will be skipped.",
                    row_number=row.source_row_number,
                )
            )
        else:
            if normalized_email:
                uploaded_emails[normalized_email] = row.source_row_number

            email_matches = existing_emails.get(normalized_email, [])
            if len(email_matches) == 1:
                status = ClientPreviewStatus.DUPLICATE
                existing_client_id = email_matches[0]
                issues.append(
                    _issue(
                        "existing_email_duplicate",
                        "Matches an existing client by email and will be skipped.",
                        row_number=row.source_row_number,
                    )
                )
            elif len(email_matches) > 1:
                status = ClientPreviewStatus.REVIEW
                issues.append(
                    _issue(
                        "ambiguous_email_match",
                        "Email matches more than one existing client and requires review.",
                        row_number=row.source_row_number,
                    )
                )
            elif normalized_phone and normalized_phone in uploaded_phones:
                status = ClientPreviewStatus.REVIEW
                duplicate_of_row = uploaded_phones[normalized_phone]
                issues.append(
                    _issue(
                        "uploaded_phone_candidate",
                        f"Phone may match uploaded row {duplicate_of_row}; review the CSV.",
                        row_number=row.source_row_number,
                    )
                )
            else:
                phone_matches = existing_phones.get(normalized_phone, [])
                if len(phone_matches) == 1:
                    status = ClientPreviewStatus.REVIEW
                    existing_client_id = phone_matches[0]
                    issues.append(
                        _issue(
                            "existing_phone_candidate",
                            "Phone may match an existing client and requires review.",
                            row_number=row.source_row_number,
                        )
                    )
                elif len(phone_matches) > 1:
                    status = ClientPreviewStatus.REVIEW
                    issues.append(
                        _issue(
                            "ambiguous_phone_match",
                            "Phone matches more than one existing client and requires review.",
                            row_number=row.source_row_number,
                        )
                    )

        if normalized_phone and normalized_phone not in uploaded_phones:
            uploaded_phones[normalized_phone] = row.source_row_number

        classified[row.source_row_number] = ClientPreviewRow(
            row_number=row.source_row_number,
            status=status,
            display=display,
            client_fields=client_fields,
            issues=tuple(issues),
            existing_client_id=existing_client_id,
            duplicate_of_row=duplicate_of_row,
        )

    return classified


def project_client_capacity(*, business, new_importable_clients: int) -> ClientCapacityProjection:
    current_active_clients = get_business_usage_count(business, "clients")
    subscription = get_business_subscription(business)
    plan_limit = get_business_plan_limit(business, "clients")

    if subscription is None or not subscription.has_access or plan_limit is None:
        decision = check_import_capacity(
            business=business,
            import_type=ImportType.CLIENTS,
            requested_rows=new_importable_clients,
            capacity_checker=lambda **_kwargs: ImportAccessDecision(
                False,
                "client_capacity_unavailable",
                "Client plan capacity could not be verified for this workspace.",
            ),
        )
        return ClientCapacityProjection(
            available=False,
            allowed=decision.allowed,
            code=decision.code,
            message=decision.message,
            current_active_clients=current_active_clients,
            plan_limit=None,
            remaining_capacity=None,
            new_importable_clients=new_importable_clients,
        )

    remaining_capacity = max(plan_limit - current_active_clients, 0)

    def capacity_checker(*, business, requested_rows):
        del business
        if requested_rows <= remaining_capacity:
            return ImportAccessDecision(True, "within_client_capacity")
        return ImportAccessDecision(
            False,
            "client_capacity_exceeded",
            (
                f"The preview contains {requested_rows} new clients but only "
                f"{remaining_capacity} client slots remain."
            ),
        )

    decision = check_import_capacity(
        business=business,
        import_type=ImportType.CLIENTS,
        requested_rows=new_importable_clients,
        capacity_checker=capacity_checker,
    )
    return ClientCapacityProjection(
        available=True,
        allowed=decision.allowed,
        code=decision.code,
        message=decision.message,
        current_active_clients=current_active_clients,
        plan_limit=plan_limit,
        remaining_capacity=remaining_capacity,
        new_importable_clients=new_importable_clients,
    )


def build_client_preview(
    validation: ClientImportValidationResult,
    *,
    business,
) -> ClientPreviewResult:
    classified = classify_validated_client_rows(validation.validated_rows, business=business)
    parsed_rows = {row.row_number: row.values for row in validation.parsed_file.rows}

    for row_result in validation.row_results:
        if row_result.is_valid:
            preview_row = classified[row_result.source_row_number]
            classified[row_result.source_row_number] = replace(
                preview_row,
                issues=row_result.issues + preview_row.issues,
            )
            continue
        classified[row_result.source_row_number] = ClientPreviewRow(
            row_number=row_result.source_row_number,
            status=ClientPreviewStatus.ERROR,
            display=_display_values(parsed_rows.get(row_result.source_row_number, {})),
            client_fields=None,
            issues=row_result.issues,
        )

    rows = tuple(classified[row_number] for row_number in sorted(classified))
    file_errors = sum(
        issue.severity == IssueSeverity.ERROR for issue in validation.parsed_file.issues
    )
    file_warnings = sum(
        issue.severity == IssueSeverity.WARNING for issue in validation.parsed_file.issues
    )
    summary = ClientPreviewSummary(
        rows_detected=validation.parsed_file.rows_detected,
        new_count=sum(row.status == ClientPreviewStatus.NEW for row in rows),
        duplicate_count=sum(row.status == ClientPreviewStatus.DUPLICATE for row in rows),
        review_count=sum(row.status == ClientPreviewStatus.REVIEW for row in rows),
        warning_count=(
            sum(
                row.status == ClientPreviewStatus.REVIEW
                or (
                    row.status == ClientPreviewStatus.NEW
                    and any(issue.severity == IssueSeverity.WARNING for issue in row.issues)
                )
                for row in rows
            )
            + file_warnings
        ),
        error_count=(
            sum(row.status == ClientPreviewStatus.ERROR for row in rows) + file_errors
        ),
    )
    capacity = project_client_capacity(
        business=business,
        new_importable_clients=summary.new_count,
    )
    ready = (
        not validation.has_errors
        and summary.review_count == 0
        and capacity.available
        and capacity.allowed
    )
    return ClientPreviewResult(
        rows=rows,
        file_issues=validation.parsed_file.issues,
        summary=summary,
        capacity=capacity,
        ready=ready,
    )


def _serialized_issue(issue: ImportIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity.value,
        "row_number": issue.row_number,
        "column": issue.column,
    }


def stored_client_preview_payload(
    job: ImportJob,
    preview: ClientPreviewResult,
) -> StoredPreviewPayload:
    normalized_rows = tuple(
        {
            "row_number": row.row_number,
            "status": row.status.value,
            "display": row.display,
            "client_fields": row.client_fields,
            "issues": [_serialized_issue(issue) for issue in row.issues],
            "existing_client_id": row.existing_client_id,
            "duplicate_of_row": row.duplicate_of_row,
        }
        for row in preview.rows
    )
    return StoredPreviewPayload(
        binding=preview_binding_for_job(job),
        normalized_rows=normalized_rows,
        metadata={
            "schema_version": CLIENT_IMPORT_SCHEMA.version,
            "summary": asdict(preview.summary),
            "capacity": asdict(preview.capacity),
            "file_issues": [_serialized_issue(issue) for issue in preview.file_issues],
            "ready": preview.ready,
        },
    )


def persist_client_preview(
    validation: ClientImportValidationResult,
    *,
    job: ImportJob,
    business,
    actor,
    store: PreviewPayloadStore = database_preview_store,
) -> ClientPreviewResult:
    if not user_can_import(business, actor, ImportType.CLIENTS):
        raise PermissionDenied("Client import access denied.")

    with transaction.atomic():
        locked_job = ImportJob.objects.select_for_update().get(pk=job.pk)
        if locked_job.business_id != business.pk or locked_job.created_by_id != actor.pk:
            raise PermissionDenied("Import job access denied.")
        if locked_job.import_type != ImportType.CLIENTS.value:
            raise ValidationError("Import job type does not match the Client schema.")
        if locked_job.schema_version != CLIENT_IMPORT_SCHEMA.version:
            raise ValidationError("Import job schema version does not match the Client schema.")
        if locked_job.file_digest != validation.parsed_file.file_digest:
            raise ValidationError("Import job file digest does not match the uploaded CSV.")
        locked_job.assert_usable()
        if locked_job.status not in {
            ImportJob.Status.UPLOADED,
            ImportJob.Status.VALIDATED,
        } or locked_job.preview_payload:
            raise ValidationError("This import job has already been previewed.")

        preview = build_client_preview(validation, business=business)
        locked_job.rows_detected = preview.summary.rows_detected
        locked_job.rows_valid = preview.summary.new_count
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
        store.save(stored_client_preview_payload(locked_job, preview))
        if locked_job.status == ImportJob.Status.UPLOADED:
            locked_job.transition_to(ImportJob.Status.VALIDATED)
        if preview.ready:
            locked_job.transition_to(ImportJob.Status.READY)
        return preview
