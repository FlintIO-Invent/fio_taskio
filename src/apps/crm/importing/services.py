from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.text import slugify

from apps.businesses.localization import parse_localized_decimal
from apps.crm.forms import BusinessServiceForm
from apps.crm.models import BusinessService, ServiceCategory

from .parsing import parse_csv_upload
from .schemas import ImportSchema
from .types import (
    CSVRow,
    ImportIssue,
    ImportPreviewSummary,
    ImportType,
    IssueSeverity,
    ParsedImportFile,
)

SERVICE_REQUIRED_FIELDS = ("name", "unit_price")
SERVICE_OPTIONAL_FIELDS = (
    "description",
    "tax_rate",
    "category",
    "is_active",
    "external_code",
    "is_bookable_online",
    "default_duration_minutes",
    "booking_buffer_minutes",
    "public_description",
    "requires_manual_confirmation",
)
SERVICE_TEMPLATE_FIELDS = SERVICE_REQUIRED_FIELDS + SERVICE_OPTIONAL_FIELDS
SERVICE_BOOKING_FIELDS = (
    "is_bookable_online",
    "default_duration_minutes",
    "booking_buffer_minutes",
    "public_description",
    "requires_manual_confirmation",
)
SERVICE_SERVER_DERIVED_FIELDS = ("business",)
SERVICE_FORBIDDEN_FIELDS = (
    "id",
    "business",
    "business_id",
    "created_at",
    "updated_at",
    "category_id",
)

SERVICE_IMPORT_SCHEMA = ImportSchema(
    import_type=ImportType.SERVICES,
    version="1",
    required_columns=SERVICE_REQUIRED_FIELDS,
    optional_columns=SERVICE_OPTIONAL_FIELDS,
    server_derived_fields=SERVICE_SERVER_DERIVED_FIELDS,
    forbidden_columns=SERVICE_FORBIDDEN_FIELDS,
)


@dataclass(frozen=True)
class ValidatedServiceRow:
    source_row_number: int
    name: str
    unit_price: Decimal
    description: str
    tax_rate: Decimal
    is_active: bool
    external_code: str | None
    is_bookable_online: bool
    default_duration_minutes: int | None
    booking_buffer_minutes: int | None
    public_description: str
    requires_manual_confirmation: bool
    present_fields: tuple[str, ...]
    blank_fields: tuple[str, ...]
    existing_service_id: int | None
    category_label: str
    category_id: int | None
    category_will_create: bool
    category_key: str

    @property
    def action(self) -> str:
        return "UPDATE" if self.existing_service_id is not None else "CREATE"

    def as_service_fields(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit_price": str(self.unit_price),
            "description": self.description,
            "tax_rate": str(self.tax_rate),
            "is_active": self.is_active,
            "external_code": self.external_code,
            "is_bookable_online": self.is_bookable_online,
            "default_duration_minutes": self.default_duration_minutes,
            "booking_buffer_minutes": self.booking_buffer_minutes,
            "public_description": self.public_description,
            "requires_manual_confirmation": self.requires_manual_confirmation,
        }


@dataclass(frozen=True)
class ServiceRowValidation:
    source_row_number: int
    display: dict[str, str]
    validated_row: ValidatedServiceRow | None
    issues: tuple[ImportIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == IssueSeverity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity == IssueSeverity.WARNING for issue in self.issues)

    @property
    def is_valid(self) -> bool:
        return self.validated_row is not None and not self.has_errors


@dataclass(frozen=True)
class ServiceImportValidationResult:
    parsed_file: ParsedImportFile
    row_results: tuple[ServiceRowValidation, ...]
    summary: ImportPreviewSummary

    @property
    def issues(self) -> tuple[ImportIssue, ...]:
        return self.parsed_file.issues + tuple(
            issue for row_result in self.row_results for issue in row_result.issues
        )

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == IssueSeverity.ERROR for issue in self.issues)


def _issue(
    *,
    row_number: int,
    column: str,
    code: str,
    message: str,
    severity: IssueSeverity = IssueSeverity.ERROR,
) -> ImportIssue:
    return ImportIssue(
        row_number=row_number,
        column=column,
        code=code,
        message=message,
        severity=severity,
    )


def _parse_decimal(value: str, *, row_number: int, field_name: str, business) -> Decimal:
    if not value.strip():
        raise ValueError(f"{field_name} is required.")
    try:
        return parse_localized_decimal(value.strip(), business)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a valid decimal number.") from exc


def _parse_boolean(value: str, *, default: bool) -> bool:
    normalized = value.strip().casefold()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError("Enter true/false, yes/no, or 1/0.")


def _parse_optional_integer(value: str, *, minimum: int) -> int | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = int(normalized)
    except ValueError as exc:
        raise ValueError("Enter a whole number.") from exc
    if parsed < minimum:
        if minimum == 1:
            raise ValueError("Enter a whole number greater than zero.")
        raise ValueError("Enter a whole number that is zero or greater.")
    return parsed


def service_category_key(label: str) -> str:
    return slugify(label.strip()).replace("-", "_")


def resolve_service_category(*, business, label: str) -> tuple[ServiceCategory | None, bool, str]:
    """Resolve only current-business categories without creating one."""

    normalized_label = label.strip()
    if not normalized_label:
        return None, False, ""
    key = service_category_key(normalized_label)
    matches = list(
        ServiceCategory.objects.filter(business=business)
        .filter(Q(name__iexact=normalized_label) | Q(code=key))
        .order_by("name", "pk")[:2]
    )
    if len(matches) > 1:
        raise ValidationError(
            "Category matches more than one category in this workspace.",
            code="ambiguous_category",
        )
    if matches:
        return matches[0], False, key
    return None, True, key


def _display_for_row(row: CSVRow) -> dict[str, str]:
    return {
        "name": (row.values.get("name") or "").strip(),
        "unit_price": (row.values.get("unit_price") or "").strip(),
        "external_code": (row.values.get("external_code") or "").strip(),
        "category": (row.values.get("category") or "").strip(),
    }


def _model_form_issues(form: BusinessServiceForm, *, row_number: int) -> list[ImportIssue]:
    issues: list[ImportIssue] = []
    for field_name, field_errors in form.errors.as_data().items():
        for error in field_errors:
            issues.append(
                _issue(
                    row_number=row_number,
                    column=field_name,
                    code=error.code or "invalid",
                    message=error.messages[0],
                )
            )
    return issues


def validate_service_row(row: CSVRow, *, business) -> ServiceRowValidation:
    values = {key: (value or "").strip() for key, value in row.values.items()}
    present_fields = tuple(column for column in SERVICE_TEMPLATE_FIELDS if column in values)
    blank_fields = tuple(column for column in present_fields if values.get(column, "") == "")
    display = _display_for_row(row)
    issues: list[ImportIssue] = []

    name = values.get("name", "")
    external_code = values.get("external_code", "") or None
    description = values.get("description", "")
    category_label = values.get("category", "")

    try:
        unit_price = _parse_decimal(
            values.get("unit_price", ""),
            row_number=row.row_number,
            field_name="unit_price",
            business=business,
        )
    except ValueError as exc:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="unit_price",
                code="invalid_decimal",
                message=str(exc),
            )
        )
        unit_price = Decimal("0")

    tax_value = values.get("tax_rate", "")
    if tax_value:
        try:
            tax_rate = _parse_decimal(
                tax_value,
                row_number=row.row_number,
                field_name="tax_rate",
                business=business,
            )
        except ValueError as exc:
            issues.append(
                _issue(
                    row_number=row.row_number,
                    column="tax_rate",
                    code="invalid_decimal",
                    message=str(exc),
                )
            )
            tax_rate = Decimal("0")
    else:
        tax_rate = business.tax_rate or Decimal("0")

    try:
        is_active = _parse_boolean(values.get("is_active", ""), default=True)
    except ValueError as exc:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="is_active",
                code="invalid_boolean",
                message=str(exc),
            )
        )
        is_active = True

    service_matches = []
    if external_code:
        service_matches = list(
            BusinessService.objects.filter(
                business=business,
                external_code__iexact=external_code,
            ).order_by("pk")[:2]
        )
    if len(service_matches) > 1:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="external_code",
                code="ambiguous_external_code",
                message=(
                    "External code matches more than one service in this workspace and "
                    "requires review."
                ),
                severity=IssueSeverity.WARNING,
            )
        )
        return ServiceRowValidation(row.row_number, display, None, tuple(issues))
    existing_service = service_matches[0] if service_matches else None

    try:
        category, category_will_create, category_key = resolve_service_category(
            business=business,
            label=category_label,
        )
    except ValidationError as exc:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="category",
                code="ambiguous_category",
                message=exc.messages[0],
            )
        )
        return ServiceRowValidation(row.row_number, display, None, tuple(issues))

    if category_will_create:
        category_candidate = ServiceCategory(
            business=business,
            name=category_label,
            code=category_key,
            is_active=True,
        )
        try:
            category_candidate.full_clean()
        except ValidationError as exc:
            for field_name, field_errors in exc.error_dict.items():
                for error in field_errors:
                    issues.append(
                        _issue(
                            row_number=row.row_number,
                            column="category" if field_name == "name" else field_name,
                            code=error.code or "invalid_category",
                            message=error.messages[0],
                        )
                    )

    def projected(field_name: str, parsed_value, create_default):
        if field_name in values:
            return parsed_value
        if existing_service is not None:
            return getattr(existing_service, field_name)
        return create_default

    try:
        parsed_bookable = _parse_boolean(values.get("is_bookable_online", ""), default=False)
    except ValueError as exc:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="is_bookable_online",
                code="invalid_boolean",
                message=str(exc),
            )
        )
        parsed_bookable = False
    try:
        parsed_duration = _parse_optional_integer(
            values.get("default_duration_minutes", ""), minimum=1
        )
    except ValueError as exc:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="default_duration_minutes",
                code="invalid_integer",
                message=str(exc),
            )
        )
        parsed_duration = None
    try:
        parsed_buffer = _parse_optional_integer(
            values.get("booking_buffer_minutes", ""), minimum=0
        )
    except ValueError as exc:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="booking_buffer_minutes",
                code="invalid_integer",
                message=str(exc),
            )
        )
        parsed_buffer = None
    try:
        parsed_manual = _parse_boolean(
            values.get("requires_manual_confirmation", ""), default=True
        )
    except ValueError as exc:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="requires_manual_confirmation",
                code="invalid_boolean",
                message=str(exc),
            )
        )
        parsed_manual = True

    is_bookable_online = projected("is_bookable_online", parsed_bookable, False)
    default_duration_minutes = projected(
        "default_duration_minutes", parsed_duration, None
    )
    booking_buffer_minutes = projected("booking_buffer_minutes", parsed_buffer, None)
    public_description = projected(
        "public_description", values.get("public_description", ""), ""
    )
    requires_manual_confirmation = projected(
        "requires_manual_confirmation", parsed_manual, True
    )

    form_data = {
        "category": category.pk if category is not None else "",
        "new_category_name": category_label if category_will_create else "",
        "name": name,
        "external_code": external_code or "",
        "description": description,
        "unit_price": str(unit_price),
        "tax_rate": str(tax_rate),
        "is_active": is_active,
        "is_bookable_online": is_bookable_online,
        "default_duration_minutes": default_duration_minutes,
        "booking_buffer_minutes": booking_buffer_minutes,
        "public_description": public_description,
        "requires_manual_confirmation": requires_manual_confirmation,
    }
    form = BusinessServiceForm(
        data=form_data,
        instance=existing_service or BusinessService(),
        business=business,
    )
    # The legacy CSV path could resolve inactive categories. Keep that import
    # compatibility while retaining the form's tenant-safe queryset.
    form.fields["category"].queryset = ServiceCategory.objects.filter(business=business)
    form.is_valid()
    issues.extend(_model_form_issues(form, row_number=row.row_number))

    if any(issue.severity == IssueSeverity.ERROR for issue in issues):
        return ServiceRowValidation(row.row_number, display, None, tuple(issues))

    cleaned = form.cleaned_data
    validated = ValidatedServiceRow(
        source_row_number=row.row_number,
        name=cleaned["name"],
        unit_price=cleaned["unit_price"],
        description=cleaned["description"],
        tax_rate=cleaned["tax_rate"],
        is_active=cleaned["is_active"],
        external_code=cleaned["external_code"],
        is_bookable_online=cleaned["is_bookable_online"],
        default_duration_minutes=cleaned["default_duration_minutes"],
        booking_buffer_minutes=cleaned["booking_buffer_minutes"],
        public_description=cleaned["public_description"],
        requires_manual_confirmation=cleaned["requires_manual_confirmation"],
        present_fields=present_fields,
        blank_fields=blank_fields,
        existing_service_id=existing_service.pk if existing_service is not None else None,
        category_label=category_label,
        category_id=category.pk if category is not None else None,
        category_will_create=category_will_create,
        category_key=category_key,
    )
    return ServiceRowValidation(row.row_number, display, validated, tuple(issues))


def _mark_duplicate_external_codes(
    row_results: tuple[ServiceRowValidation, ...],
) -> tuple[ServiceRowValidation, ...]:
    counts = Counter(
        result.validated_row.external_code.casefold()
        for result in row_results
        if result.validated_row is not None and result.validated_row.external_code
    )
    duplicate_codes = {code for code, count in counts.items() if count > 1}
    if not duplicate_codes:
        return row_results

    updated: list[ServiceRowValidation] = []
    for result in row_results:
        validated = result.validated_row
        if validated is None or not validated.external_code:
            updated.append(result)
            continue
        if validated.external_code.casefold() not in duplicate_codes:
            updated.append(result)
            continue
        issue = _issue(
            row_number=result.source_row_number,
            column="external_code",
            code="duplicate_uploaded_external_code",
            message="External code appears more than once in this CSV and requires review.",
            severity=IssueSeverity.WARNING,
        )
        updated.append(
            ServiceRowValidation(
                source_row_number=result.source_row_number,
                display=result.display,
                validated_row=validated,
                issues=result.issues + (issue,),
            )
        )
    return tuple(updated)


def validate_service_import(uploaded_file, *, business) -> ServiceImportValidationResult:
    """Parse and validate a Service CSV without writing application data."""

    parsed_file = parse_csv_upload(uploaded_file, SERVICE_IMPORT_SCHEMA)
    row_results = (
        ()
        if parsed_file.has_errors
        else tuple(validate_service_row(row, business=business) for row in parsed_file.rows)
    )
    row_results = _mark_duplicate_external_codes(row_results)
    summary = ImportPreviewSummary(
        rows_detected=parsed_file.rows_detected,
        rows_valid=sum(result.is_valid for result in row_results),
        rows_warning=sum(result.has_warnings for result in row_results),
        rows_error=sum(result.has_errors for result in row_results),
    )
    return ServiceImportValidationResult(
        parsed_file=parsed_file,
        row_results=row_results,
        summary=summary,
    )
