from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.businesses.models import Business, BusinessUser
from apps.businesses.utils import SERVICE_MANAGEMENT_ROLES
from apps.crm.models import BusinessService, ImportJob, ServiceCategory

from .preview import PreviewPayloadStore, database_preview_store, preview_binding_for_job
from .service_preview import ServicePreviewStatus
from .services import SERVICE_IMPORT_SCHEMA, resolve_service_category
from .types import ImportType


class ServiceImportExecutionCode(StrEnum):
    COMPLETED = "completed"
    ALREADY_COMPLETED = "already_completed"
    EXPIRED = "expired"
    NOT_READY = "not_ready"
    STATE_CHANGED = "state_changed"
    PREVIEW_INVALID = "preview_invalid"
    FAILED = "failed"


@dataclass(frozen=True)
class ServiceImportExecutionResult:
    code: ServiceImportExecutionCode
    message: str
    services_created: int = 0
    services_updated: int = 0
    rows_skipped: int = 0
    categories_created: int = 0
    total_processed: int = 0
    completed: bool = False


TRUSTED_SERVICE_FIELD_NAMES = frozenset(
    {
        "name",
        "unit_price",
        "description",
        "tax_rate",
        "is_active",
        "external_code",
        "is_bookable_online",
        "default_duration_minutes",
        "booking_buffer_minutes",
        "public_description",
        "requires_manual_confirmation",
    }
)
TRUSTED_CATEGORY_FIELD_NAMES = frozenset(
    {"label", "existing_id", "will_create", "key", "display"}
)


class InvalidStoredServicePreview(ValueError):
    pass


class ServiceStateChanged(ValueError):
    pass


@dataclass(frozen=True)
class TrustedServiceRow:
    row_number: int
    status: ServicePreviewStatus
    service_fields: dict[str, Any]
    existing_service_id: int | None
    category_label: str
    category_id: int | None
    category_will_create: bool
    category_key: str


def _result(
    code: ServiceImportExecutionCode,
    message: str,
    *,
    services_created: int = 0,
    services_updated: int = 0,
    rows_skipped: int = 0,
    categories_created: int = 0,
    completed: bool = False,
) -> ServiceImportExecutionResult:
    return ServiceImportExecutionResult(
        code=code,
        message=message,
        services_created=services_created,
        services_updated=services_updated,
        rows_skipped=rows_skipped,
        categories_created=categories_created,
        total_processed=services_created + services_updated + rows_skipped,
        completed=completed,
    )


def _record_execution_result(job: ImportJob, result: ServiceImportExecutionResult) -> None:
    payload = dict(job.preview_payload) if isinstance(job.preview_payload, dict) else {}
    payload["execution_result"] = {**asdict(result), "code": result.code.value}
    job.preview_payload = payload
    job.save(update_fields=["preview_payload", "updated_at"])


def _fail_ready_job(
    job: ImportJob,
    code: ServiceImportExecutionCode,
    message: str,
) -> ServiceImportExecutionResult:
    result = _result(code, message)
    _record_execution_result(job, result)
    job.transition_to(ImportJob.Status.FAILED)
    return result


def _validate_service_fields(fields: Any) -> dict[str, Any]:
    if not isinstance(fields, dict) or set(fields) != TRUSTED_SERVICE_FIELD_NAMES:
        raise InvalidStoredServicePreview("Stored Service fields do not match the allowlist.")
    normalized = dict(fields)
    if not isinstance(normalized["name"], str) or not normalized["name"]:
        raise InvalidStoredServicePreview("Stored Service name is invalid.")
    for field_name in ("description", "public_description"):
        if not isinstance(normalized[field_name], str):
            raise InvalidStoredServicePreview("Stored Service text is invalid.")
    external_code = normalized["external_code"]
    if external_code is not None and not isinstance(external_code, str):
        raise InvalidStoredServicePreview("Stored Service external code is invalid.")
    for field_name in ("is_active", "is_bookable_online", "requires_manual_confirmation"):
        if type(normalized[field_name]) is not bool:
            raise InvalidStoredServicePreview("Stored Service boolean is invalid.")
    for field_name in ("default_duration_minutes", "booking_buffer_minutes"):
        value = normalized[field_name]
        if value is not None and type(value) is not int:
            raise InvalidStoredServicePreview("Stored Service booking value is invalid.")
    try:
        normalized["unit_price"] = Decimal(normalized["unit_price"])
        normalized["tax_rate"] = Decimal(normalized["tax_rate"])
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidStoredServicePreview("Stored Service decimal is invalid.") from exc
    return normalized


def _trusted_rows(payload, job: ImportJob) -> tuple[TrustedServiceRow, ...]:
    metadata = payload.metadata
    if metadata.get("schema_version") != SERVICE_IMPORT_SCHEMA.version:
        raise InvalidStoredServicePreview("Stored Service preview schema does not match.")
    if metadata.get("ready") is not True:
        raise InvalidStoredServicePreview("Stored Service preview is not ready.")

    trusted: list[TrustedServiceRow] = []
    create_count = 0
    update_count = 0
    for stored in payload.normalized_rows:
        row_number = stored.get("row_number")
        if type(row_number) is not int or row_number < 1:
            raise InvalidStoredServicePreview("Stored Service row number is invalid.")
        try:
            status = ServicePreviewStatus(stored.get("status"))
        except ValueError as exc:
            raise InvalidStoredServicePreview("Stored Service action is invalid.") from exc
        if status not in {ServicePreviewStatus.CREATE, ServicePreviewStatus.UPDATE}:
            raise InvalidStoredServicePreview("Stored Service preview contains a blocking row.")

        existing_id = stored.get("existing_service_id")
        if existing_id is not None and type(existing_id) is not int:
            raise InvalidStoredServicePreview("Stored Service target is invalid.")
        if (status == ServicePreviewStatus.UPDATE) != (existing_id is not None):
            raise InvalidStoredServicePreview("Stored Service target does not match its action.")

        category = stored.get("category")
        if not isinstance(category, dict) or set(category) != TRUSTED_CATEGORY_FIELD_NAMES:
            raise InvalidStoredServicePreview("Stored Service category is invalid.")
        label = category["label"]
        category_id = category["existing_id"]
        will_create = category["will_create"]
        key = category["key"]
        if not isinstance(label, str) or not isinstance(key, str) or type(will_create) is not bool:
            raise InvalidStoredServicePreview("Stored Service category values are invalid.")
        if category_id is not None and type(category_id) is not int:
            raise InvalidStoredServicePreview("Stored Service category target is invalid.")
        if will_create and (not label or not key or category_id is not None):
            raise InvalidStoredServicePreview("Stored proposed Service category is invalid.")
        if not label and (category_id is not None or will_create or key):
            raise InvalidStoredServicePreview("Stored blank Service category is invalid.")

        trusted.append(
            TrustedServiceRow(
                row_number=row_number,
                status=status,
                service_fields=_validate_service_fields(stored.get("service_fields")),
                existing_service_id=existing_id,
                category_label=label,
                category_id=category_id,
                category_will_create=will_create,
                category_key=key,
            )
        )
        create_count += status == ServicePreviewStatus.CREATE
        update_count += status == ServicePreviewStatus.UPDATE

    summary = metadata.get("summary")
    if not isinstance(summary, dict):
        raise InvalidStoredServicePreview("Stored Service summary is missing.")
    if summary.get("create_count") != create_count or summary.get("update_count") != update_count:
        raise InvalidStoredServicePreview("Stored Service counts do not match.")
    if job.rows_valid != len(trusted):
        raise InvalidStoredServicePreview("Import job Service count does not match its preview.")
    return tuple(trusted)


def _locked_membership_allows_import(*, business, actor) -> bool:
    membership = (
        BusinessUser.objects.select_for_update()
        .filter(business=business, user=actor, is_active=True)
        .first()
    )
    return bool(membership and membership.role in SERVICE_MANAGEMENT_ROLES)


def _recheck_targets(rows: tuple[TrustedServiceRow, ...], *, business) -> None:
    for row in rows:
        external_code = row.service_fields["external_code"]
        matches = []
        if external_code:
            matches = list(
                BusinessService.objects.select_for_update()
                .filter(business=business, external_code__iexact=external_code)
                .order_by("pk")[:2]
            )
        if row.status == ServicePreviewStatus.UPDATE:
            if len(matches) != 1 or matches[0].pk != row.existing_service_id:
                raise ServiceStateChanged("Service match changed after preview.")
        elif matches:
            raise ServiceStateChanged("Service match changed after preview.")

    # Lock the tenant's current category namespace before resolving names/codes.
    list(
        ServiceCategory.objects.select_for_update()
        .filter(business=business)
        .values_list("pk", flat=True)
    )
    checked_category_keys: set[str] = set()
    for row in rows:
        if not row.category_label or row.category_key in checked_category_keys:
            continue
        checked_category_keys.add(row.category_key)
        try:
            category, will_create, key = resolve_service_category(
                business=business,
                label=row.category_label,
            )
        except ValidationError as exc:
            raise ServiceStateChanged("Service category changed after preview.") from exc
        current_id = category.pk if category is not None else None
        if (
            current_id != row.category_id
            or will_create != row.category_will_create
            or key != row.category_key
        ):
            raise ServiceStateChanged("Service category changed after preview.")


def _create_categories(rows: tuple[TrustedServiceRow, ...], *, business) -> dict[str, ServiceCategory]:
    categories: dict[str, ServiceCategory] = {}
    for row in rows:
        if not row.category_will_create or row.category_key in categories:
            continue
        category = ServiceCategory(
            business=business,
            name=row.category_label,
            code=row.category_key,
            is_active=True,
        )
        category.full_clean()
        category.save()
        categories[row.category_key] = category
    return categories


def _category_for_row(
    row: TrustedServiceRow,
    *,
    business,
    created_categories: dict[str, ServiceCategory],
) -> ServiceCategory | None:
    if row.category_will_create:
        return created_categories[row.category_key]
    if row.category_id is None:
        return None
    return ServiceCategory.objects.get(pk=row.category_id, business=business)


def _write_services(
    rows: tuple[TrustedServiceRow, ...],
    *,
    business,
    created_categories: dict[str, ServiceCategory],
) -> None:
    for row in rows:
        if row.status == ServicePreviewStatus.UPDATE:
            service = BusinessService.objects.select_for_update().get(
                pk=row.existing_service_id,
                business=business,
            )
        else:
            service = BusinessService(business=business)
        service.business = business
        service.category = _category_for_row(
            row,
            business=business,
            created_categories=created_categories,
        )
        for field_name, value in row.service_fields.items():
            setattr(service, field_name, value)
        service.full_clean()
        service.save()


def execute_service_import(
    *,
    job_id,
    business,
    actor,
    store: PreviewPayloadStore = database_preview_store,
) -> ServiceImportExecutionResult:
    """Commit a bound Service preview as one all-or-none transaction."""

    if (
        business is None
        or not getattr(actor, "is_authenticated", False)
        or not getattr(business, "is_active", False)
    ):
        raise PermissionDenied("Service import access denied.")

    with transaction.atomic():
        # Lock order is stable for concurrent Service imports: Business,
        # membership, ImportJob, then matching Services and Categories.
        locked_business = Business.objects.select_for_update().get(pk=business.pk)
        if not locked_business.is_active or not _locked_membership_allows_import(
            business=locked_business,
            actor=actor,
        ):
            raise PermissionDenied("Service import access denied.")

        job = ImportJob.objects.select_for_update().filter(pk=job_id).first()
        if (
            job is None
            or job.business_id != locked_business.pk
            or job.created_by_id != actor.pk
            or job.import_type != ImportType.SERVICES.value
            or job.schema_version != SERVICE_IMPORT_SCHEMA.version
        ):
            raise PermissionDenied("Import job access denied.")

        if job.status == ImportJob.Status.COMPLETED:
            previous = service_execution_result_from_job(job)
            result = _result(
                ServiceImportExecutionCode.ALREADY_COMPLETED,
                "This Service import was already completed.",
                services_created=job.rows_created,
                services_updated=job.rows_updated,
                rows_skipped=job.rows_skipped,
                categories_created=previous.categories_created,
                completed=True,
            )
            _record_execution_result(job, result)
            return result
        if job.expires_at <= timezone.now() or job.status == ImportJob.Status.EXPIRED:
            result = _result(
                ServiceImportExecutionCode.EXPIRED,
                "This Service import preview has expired. Create a new preview.",
            )
            _record_execution_result(job, result)
            if job.status == ImportJob.Status.READY:
                job.transition_to(ImportJob.Status.EXPIRED)
            return result
        if job.status != ImportJob.Status.READY:
            return _result(
                ServiceImportExecutionCode.NOT_READY,
                "This Service import is not ready. Create a new preview.",
            )

        try:
            with transaction.atomic():
                payload = store.load(preview_binding_for_job(job))
                if payload is None:
                    raise InvalidStoredServicePreview("Stored preview binding did not match.")
                rows = _trusted_rows(payload, job)
                _recheck_targets(rows, business=locked_business)
                created_categories = _create_categories(rows, business=locked_business)
                _write_services(
                    rows,
                    business=locked_business,
                    created_categories=created_categories,
                )
        except InvalidStoredServicePreview:
            return _fail_ready_job(
                job,
                ServiceImportExecutionCode.PREVIEW_INVALID,
                "The stored Service preview could not be verified. Create a new preview.",
            )
        except ServiceStateChanged:
            return _fail_ready_job(
                job,
                ServiceImportExecutionCode.STATE_CHANGED,
                "Service matches or categories changed after preview. Create a new preview.",
            )
        except Exception:
            return _fail_ready_job(
                job,
                ServiceImportExecutionCode.FAILED,
                "The Service import failed safely. No Services or categories were changed.",
            )

        create_count = sum(row.status == ServicePreviewStatus.CREATE for row in rows)
        update_count = sum(row.status == ServicePreviewStatus.UPDATE for row in rows)
        result = _result(
            ServiceImportExecutionCode.COMPLETED,
            "Service import complete.",
            services_created=create_count,
            services_updated=update_count,
            categories_created=len(created_categories),
            completed=True,
        )
        job.rows_created = result.services_created
        job.rows_updated = result.services_updated
        job.rows_skipped = result.rows_skipped
        job.save(
            update_fields=["rows_created", "rows_updated", "rows_skipped", "updated_at"]
        )
        _record_execution_result(job, result)
        job.transition_to(ImportJob.Status.COMPLETED)
        return result


def service_execution_result_from_job(job: ImportJob) -> ServiceImportExecutionResult:
    payload = job.preview_payload if isinstance(job.preview_payload, dict) else {}
    stored = payload.get("execution_result", {})
    try:
        return ServiceImportExecutionResult(
            code=ServiceImportExecutionCode(stored["code"]),
            message=str(stored["message"]),
            services_created=int(stored.get("services_created", 0)),
            services_updated=int(stored.get("services_updated", 0)),
            rows_skipped=int(stored.get("rows_skipped", 0)),
            categories_created=int(stored.get("categories_created", 0)),
            total_processed=int(stored.get("total_processed", 0)),
            completed=bool(stored.get("completed", False)),
        )
    except (KeyError, TypeError, ValueError):
        if job.status == ImportJob.Status.COMPLETED:
            return _result(
                ServiceImportExecutionCode.ALREADY_COMPLETED,
                "This Service import was already completed.",
                services_created=job.rows_created,
                services_updated=job.rows_updated,
                rows_skipped=job.rows_skipped,
                completed=True,
            )
        if job.status == ImportJob.Status.EXPIRED or job.is_expired:
            return _result(
                ServiceImportExecutionCode.EXPIRED,
                "This Service import preview has expired. Create a new preview.",
            )
        if job.status == ImportJob.Status.FAILED:
            return _result(
                ServiceImportExecutionCode.FAILED,
                "The Service import failed safely. No Services or categories were changed.",
            )
        return _result(
            ServiceImportExecutionCode.NOT_READY,
            "This Service import has not been completed.",
        )
