from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.businesses.models import BusinessUser
from apps.businesses.utils import CLIENT_MANAGE_ROLES
from apps.crm.client_capacity import lock_client_capacity_scope
from apps.crm.models import Client, ImportJob

from .client_preview import (
    ClientPreviewStatus,
    classify_validated_client_rows,
    project_client_capacity,
)
from .clients import CLIENT_IMPORT_SCHEMA, ValidatedClientRow
from .preview import PreviewPayloadStore, database_preview_store, preview_binding_for_job
from .types import ImportType


class ClientImportExecutionCode(StrEnum):
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"
    EXPIRED = "expired"
    NOT_READY = "not_ready"
    DUPLICATES_CHANGED = "duplicates_changed"
    CAPACITY_CHANGED = "capacity_changed"
    PREVIEW_INVALID = "preview_invalid"
    FAILED = "failed"


@dataclass(frozen=True)
class ClientImportExecutionResult:
    code: ClientImportExecutionCode
    message: str
    clients_created: int = 0
    duplicates_skipped: int = 0
    total_processed: int = 0
    completed: bool = False


TRUSTED_CLIENT_FIELD_NAMES = frozenset(
    field.name for field in fields(ValidatedClientRow) if field.name != "source_row_number"
)


class InvalidStoredPreview(ValueError):
    pass


class DuplicateStateChanged(ValueError):
    pass


class CapacityStateChanged(ValueError):
    pass


def _result(
    code: ClientImportExecutionCode,
    message: str,
    *,
    clients_created: int = 0,
    duplicates_skipped: int = 0,
    completed: bool = False,
) -> ClientImportExecutionResult:
    return ClientImportExecutionResult(
        code=code,
        message=message,
        clients_created=clients_created,
        duplicates_skipped=duplicates_skipped,
        total_processed=clients_created + duplicates_skipped,
        completed=completed,
    )


def _record_execution_result(job: ImportJob, result: ClientImportExecutionResult) -> None:
    preview_payload = dict(job.preview_payload) if isinstance(job.preview_payload, dict) else {}
    preview_payload["execution_result"] = {
        **asdict(result),
        "code": result.code.value,
    }
    job.preview_payload = preview_payload
    job.save(update_fields=["preview_payload", "updated_at"])


def _fail_ready_job(
    job: ImportJob,
    code: ClientImportExecutionCode,
    message: str,
) -> ClientImportExecutionResult:
    result = _result(code, message)
    _record_execution_result(job, result)
    job.transition_to(ImportJob.Status.FAILED)
    return result


def _trusted_new_rows(payload, job: ImportJob) -> tuple[tuple[ValidatedClientRow, ...], int]:
    metadata = payload.metadata
    if metadata.get("schema_version") != CLIENT_IMPORT_SCHEMA.version:
        raise InvalidStoredPreview("Stored Client preview schema does not match.")
    if metadata.get("ready") is not True:
        raise InvalidStoredPreview("Stored Client preview is not ready.")

    trusted_rows: list[ValidatedClientRow] = []
    duplicate_count = 0
    for stored_row in payload.normalized_rows:
        row_number = stored_row.get("row_number")
        status = stored_row.get("status")
        if type(row_number) is not int or row_number < 1:
            raise InvalidStoredPreview("Stored Client preview row number is invalid.")
        if status == ClientPreviewStatus.DUPLICATE.value:
            duplicate_count += 1
            continue
        if status != ClientPreviewStatus.NEW.value:
            raise InvalidStoredPreview("Stored Client preview contains a blocking row.")

        client_fields = stored_row.get("client_fields")
        if not isinstance(client_fields, dict) or set(client_fields) != TRUSTED_CLIENT_FIELD_NAMES:
            raise InvalidStoredPreview("Stored Client fields do not match the trusted allowlist.")
        try:
            trusted_row = ValidatedClientRow(
                source_row_number=row_number,
                **client_fields,
            )
        except (TypeError, ValueError) as exc:
            raise InvalidStoredPreview("Stored Client fields are invalid.") from exc
        trusted_rows.append(trusted_row)

    summary = metadata.get("summary")
    if not isinstance(summary, dict):
        raise InvalidStoredPreview("Stored Client preview summary is missing.")
    if summary.get("new_count") != len(trusted_rows):
        raise InvalidStoredPreview("Stored Client preview new-row count does not match.")
    if summary.get("duplicate_count") != duplicate_count:
        raise InvalidStoredPreview("Stored Client preview duplicate count does not match.")
    if job.rows_valid != len(trusted_rows):
        raise InvalidStoredPreview("Import job Client count does not match its preview.")
    return tuple(trusted_rows), duplicate_count


def _locked_membership_allows_import(*, business, actor) -> bool:
    membership = (
        BusinessUser.objects.select_for_update()
        .filter(
            business=business,
            user=actor,
            is_active=True,
        )
        .first()
    )
    return bool(membership and membership.role in CLIENT_MANAGE_ROLES)


def _create_client_from_trusted_row(row: ValidatedClientRow, *, business) -> Client:
    client_fields: dict[str, Any] = row.as_client_fields()
    client_fields["is_active"] = True
    client = Client(business=business, **client_fields)
    client.full_clean()
    client.save()
    return client


def execute_client_import(
    *,
    job_id,
    business,
    actor,
    store: PreviewPayloadStore = database_preview_store,
) -> ClientImportExecutionResult:
    """Atomically create only trusted NEW rows from a bound READY preview."""

    if (
        business is None
        or not getattr(actor, "is_authenticated", False)
        or not getattr(business, "is_active", False)
    ):
        raise PermissionDenied("Client import access denied.")

    with transaction.atomic():
        locked_business = lock_client_capacity_scope(business)
        if not locked_business.is_active or not _locked_membership_allows_import(
            business=locked_business,
            actor=actor,
        ):
            raise PermissionDenied("Client import access denied.")

        job = ImportJob.objects.select_for_update().filter(pk=job_id).first()
        if (
            job is None
            or job.business_id != locked_business.pk
            or job.created_by_id != actor.pk
        ):
            raise PermissionDenied("Import job access denied.")
        if (
            job.import_type != ImportType.CLIENTS.value
            or job.schema_version != CLIENT_IMPORT_SCHEMA.version
        ):
            raise PermissionDenied("Import job access denied.")

        if job.status == ImportJob.Status.COMPLETED:
            result = _result(
                ClientImportExecutionCode.ALREADY_COMPLETED,
                "This Client import was already completed.",
                clients_created=job.rows_created,
                duplicates_skipped=job.rows_skipped,
                completed=True,
            )
            _record_execution_result(job, result)
            return result
        if job.expires_at <= timezone.now() or job.status == ImportJob.Status.EXPIRED:
            result = _result(
                ClientImportExecutionCode.EXPIRED,
                "This Client import preview has expired. Create a new preview.",
            )
            _record_execution_result(job, result)
            if job.status == ImportJob.Status.READY:
                job.transition_to(ImportJob.Status.EXPIRED)
            return result
        if job.status != ImportJob.Status.READY:
            return _result(
                ClientImportExecutionCode.NOT_READY,
                "This Client import is not ready. Create a new preview.",
            )

        try:
            with transaction.atomic():
                payload = store.load(preview_binding_for_job(job))
                if payload is None:
                    raise InvalidStoredPreview("Stored preview binding did not match.")

                trusted_rows, duplicate_count = _trusted_new_rows(payload, job)
                reclassified = classify_validated_client_rows(
                    trusted_rows,
                    business=locked_business,
                )
                if any(
                    row.status != ClientPreviewStatus.NEW for row in reclassified.values()
                ):
                    raise DuplicateStateChanged

                capacity = project_client_capacity(
                    business=locked_business,
                    new_importable_clients=len(trusted_rows),
                )
                if not capacity.available or not capacity.allowed:
                    raise CapacityStateChanged

                for row in trusted_rows:
                    _create_client_from_trusted_row(row, business=locked_business)
        except InvalidStoredPreview:
            return _fail_ready_job(
                job,
                ClientImportExecutionCode.PREVIEW_INVALID,
                "The stored Client preview could not be verified. Create a new preview.",
            )
        except DuplicateStateChanged:
            return _fail_ready_job(
                job,
                ClientImportExecutionCode.DUPLICATES_CHANGED,
                "Client duplicates changed after preview. Create a new preview.",
            )
        except CapacityStateChanged:
            return _fail_ready_job(
                job,
                ClientImportExecutionCode.CAPACITY_CHANGED,
                "Client capacity changed after preview. Create a new preview.",
            )
        except Exception:
            return _fail_ready_job(
                job,
                ClientImportExecutionCode.FAILED,
                "The Client import failed safely. No Clients were created.",
            )

        result = _result(
            ClientImportExecutionCode.COMPLETED,
            "Client import complete.",
            clients_created=len(trusted_rows),
            duplicates_skipped=duplicate_count,
            completed=True,
        )
        job.rows_created = result.clients_created
        job.rows_skipped = result.duplicates_skipped
        job.save(update_fields=["rows_created", "rows_skipped", "updated_at"])
        _record_execution_result(job, result)
        job.transition_to(ImportJob.Status.COMPLETED)
        return result


def execution_result_from_job(job: ImportJob) -> ClientImportExecutionResult:
    preview_payload = job.preview_payload if isinstance(job.preview_payload, dict) else {}
    stored = preview_payload.get("execution_result", {})
    try:
        return ClientImportExecutionResult(
            code=ClientImportExecutionCode(stored["code"]),
            message=str(stored["message"]),
            clients_created=int(stored.get("clients_created", 0)),
            duplicates_skipped=int(stored.get("duplicates_skipped", 0)),
            total_processed=int(stored.get("total_processed", 0)),
            completed=bool(stored.get("completed", False)),
        )
    except (KeyError, TypeError, ValueError):
        if job.status == ImportJob.Status.COMPLETED:
            return _result(
                ClientImportExecutionCode.ALREADY_COMPLETED,
                "This Client import was already completed.",
                clients_created=job.rows_created,
                duplicates_skipped=job.rows_skipped,
                completed=True,
            )
        if job.status == ImportJob.Status.EXPIRED or job.is_expired:
            return _result(
                ClientImportExecutionCode.EXPIRED,
                "This Client import preview has expired. Create a new preview.",
            )
        if job.status == ImportJob.Status.FAILED:
            return _result(
                ClientImportExecutionCode.FAILED,
                "The Client import failed safely. No Clients were created.",
            )
        return _result(
            ClientImportExecutionCode.NOT_READY,
            "This Client import has not been completed.",
        )
