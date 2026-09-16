from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.text import slugify

from apps.crm.forms import PrivateLeadForm
from apps.crm.models import Lead, ServiceCategory

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

LEAD_REQUIRED_FIELDS = (
    "lead_type",
    "first_name",
    "last_name",
    "email",
    "phone",
    "company_name",
)
LEAD_OPTIONAL_FIELDS = (
    "status",
    "category",
    "street_address",
    "district",
    "country",
    "postal_code",
    "message",
    "notes",
    "consent_to_contact",
)
LEAD_TEMPLATE_FIELDS = LEAD_REQUIRED_FIELDS + LEAD_OPTIONAL_FIELDS
LEAD_SERVER_DERIVED_FIELDS = ("business", "is_active", "request_source")
LEAD_FORBIDDEN_FIELDS = (
    "id",
    "business",
    "business_id",
    "category_id",
    "requested_service",
    "requested_service_id",
    "preferred_start_time",
    "preferred_end_time",
    "request_source",
    "appointment",
    "appointment_id",
    "invoice",
    "invoice_id",
    "client",
    "client_id",
    "converted_client",
    "converted_client_id",
    "created_by",
    "created_at",
    "updated_at",
    "is_active",
)
LEAD_IMPORT_DEFAULTS: dict[str, Any] = {
    "status": Lead.Status.NEW,
    "category": "",
    "street_address": "",
    "district": "",
    "country": "",
    "postal_code": "",
    "message": "",
    "notes": "",
    # Import-only privacy policy: missing data cannot manufacture consent.
    "consent_to_contact": False,
    "is_active": True,
    "request_source": Lead.RequestSource.OTHER,
}

LEAD_IMPORT_SCHEMA = ImportSchema(
    import_type=ImportType.LEADS,
    version="1",
    required_columns=LEAD_REQUIRED_FIELDS,
    optional_columns=LEAD_OPTIONAL_FIELDS,
    server_derived_fields=LEAD_SERVER_DERIVED_FIELDS,
    forbidden_columns=LEAD_FORBIDDEN_FIELDS,
    defaults=LEAD_IMPORT_DEFAULTS,
)

LEAD_SAMPLE_ROW = {
    "lead_type": Lead.LeadType.REQUEST,
    "first_name": "Jamie",
    "last_name": "Requester",
    "email": "jamie@example.com",
    "phone": "+1 721 555 0100",
    "company_name": "Example Customer",
    "status": Lead.Status.NEW,
    "category": "Maintenance",
    "street_address": "12 Example Street",
    "district": Lead.DistrictChoices.SIMPSON_BAY,
    "country": "Sint Maarten",
    "postal_code": "",
    "message": "Historical service request",
    "notes": "Imported from the previous CRM",
    "consent_to_contact": "false",
}

LEAD_ALLOWED_STATUSES = (
    Lead.Status.NEW,
    Lead.Status.CONTACTED,
    Lead.Status.CLOSED,
)


@dataclass(frozen=True)
class ValidatedLeadRow:
    source_row_number: int
    lead_type: str
    first_name: str
    last_name: str
    email: str
    phone: str
    company_name: str
    status: str
    street_address: str
    district: str
    country: str
    postal_code: str
    message: str
    notes: str
    consent_to_contact: bool
    category_label: str
    category_id: int | None

    def as_lead_fields(self) -> dict[str, Any]:
        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name
            not in {
                "source_row_number",
                "category_label",
                "category_id",
            }
        }


@dataclass(frozen=True)
class LeadRowValidation:
    source_row_number: int
    display: dict[str, str]
    validated_row: ValidatedLeadRow | None
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
class LeadImportValidationResult:
    parsed_file: ParsedImportFile
    row_results: tuple[LeadRowValidation, ...]
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


def _canonical_choice(value: str, choices) -> str:
    canonical = {str(choice_value).casefold(): str(choice_value) for choice_value, _ in choices}
    return canonical.get(value.casefold(), value)


def _normalize_boolean(value: str, *, default: bool) -> bool:
    normalized = value.strip().casefold()
    if not normalized:
        return default
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    raise ValueError("Enter true, false, yes, no, 1, or 0.")


def _allowed_category_queryset(business):
    return ServiceCategory.objects.filter(
        Q(business=business) | Q(business__isnull=True),
        is_active=True,
    )


def lead_category_key(label: str) -> str:
    return slugify(label.strip()).replace("-", "_")


def resolve_lead_category(*, business, label: str) -> ServiceCategory | None:
    """Resolve an active tenant or legacy-global category without accepting IDs."""

    normalized_label = label.strip()
    if not normalized_label:
        return None
    key = lead_category_key(normalized_label)
    matches = list(
        _allowed_category_queryset(business)
        .filter(Q(name__iexact=normalized_label) | Q(code=key))
        .order_by("business_id", "name", "pk")[:2]
    )
    if len(matches) > 1:
        raise ValidationError(
            "Category matches more than one allowed category and requires review.",
            code="ambiguous_category",
        )
    if not matches:
        raise ValidationError(
            "Category does not match an active category available to this workspace.",
            code="unknown_category",
        )
    return matches[0]


def _display(row: CSVRow) -> dict[str, str]:
    return {
        "lead_type": (row.values.get("lead_type") or "").strip(),
        "first_name": (row.values.get("first_name") or "").strip(),
        "last_name": (row.values.get("last_name") or "").strip(),
        "email": (row.values.get("email") or "").strip(),
        "phone": (row.values.get("phone") or "").strip(),
        "category": (row.values.get("category") or "").strip(),
    }


def _form_issues(form: PrivateLeadForm, *, row_number: int) -> list[ImportIssue]:
    issues: list[ImportIssue] = []
    for field_name, field_errors in form.errors.as_data().items():
        for error in field_errors:
            code = error.code or "invalid"
            if field_name == "email" and code == "invalid":
                code = "invalid_email"
            issues.append(
                _issue(
                    row_number=row_number,
                    column=field_name,
                    code=code,
                    message=error.messages[0],
                )
            )
    return issues


def validate_lead_row(row: CSVRow, *, business) -> LeadRowValidation:
    values = {
        column: (row.values.get(column) or "").strip()
        for column in LEAD_IMPORT_SCHEMA.allowed_columns
    }
    for field_name, default in LEAD_IMPORT_DEFAULTS.items():
        if field_name in LEAD_SERVER_DERIVED_FIELDS:
            continue
        if not values.get(field_name):
            values[field_name] = default

    values["lead_type"] = _canonical_choice(str(values["lead_type"]), Lead.LeadType.choices)
    values["status"] = _canonical_choice(str(values["status"]), Lead.Status.choices)
    if values["country"] == "":
        values["country"] = (business.country or "").strip()
    if values["district"]:
        values["district"] = _canonical_choice(
            str(values["district"]),
            Lead.DistrictChoices.choices,
        )

    issues: list[ImportIssue] = []
    if values["status"] == Lead.Status.INVOICED:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="status",
                code="unsafe_invoiced_status",
                message="INVOICED is not supported by the historical Lead V1 import.",
            )
        )

    try:
        values["consent_to_contact"] = _normalize_boolean(
            str(values["consent_to_contact"]),
            default=False,
        )
    except ValueError as exc:
        issues.append(
            _issue(
                row_number=row.row_number,
                column="consent_to_contact",
                code="invalid_boolean",
                message=str(exc),
            )
        )
        values["consent_to_contact"] = False

    category_label = str(values["category"])
    category = None
    category_ambiguous = False
    if category_label:
        try:
            category = resolve_lead_category(business=business, label=category_label)
        except ValidationError as exc:
            category_ambiguous = exc.code == "ambiguous_category"
            issues.append(
                _issue(
                    row_number=row.row_number,
                    column="category",
                    code=exc.code or "invalid_category",
                    message=exc.messages[0],
                    severity=(
                        IssueSeverity.WARNING if category_ambiguous else IssueSeverity.ERROR
                    ),
                )
            )

    form_data = {
        "lead_type": values["lead_type"],
        "status": values["status"],
        "category": category.pk if category is not None else "",
        "first_name": values["first_name"],
        "last_name": values["last_name"],
        "company_name": values["company_name"],
        "email": values["email"],
        "phone": values["phone"],
        "street_address": values["street_address"],
        "district": values["district"],
        "country": values["country"],
        "postal_code": values["postal_code"],
        "message": values["message"],
        "notes": values["notes"],
        "consent_to_contact": values["consent_to_contact"],
        "is_active": True,
    }
    form = PrivateLeadForm(data=form_data, business=business)
    form.fields["category"].queryset = _allowed_category_queryset(business)
    form.is_valid()
    issues.extend(_form_issues(form, row_number=row.row_number))

    if category_ambiguous or any(issue.severity == IssueSeverity.ERROR for issue in issues):
        return LeadRowValidation(row.row_number, _display(row), None, tuple(issues))

    cleaned = form.cleaned_data
    validated = ValidatedLeadRow(
        source_row_number=row.row_number,
        lead_type=cleaned["lead_type"],
        first_name=cleaned["first_name"],
        last_name=cleaned["last_name"],
        email=cleaned["email"],
        phone=cleaned["phone"],
        company_name=cleaned["company_name"],
        status=cleaned["status"],
        street_address=cleaned["street_address"],
        district=cleaned["district"],
        country=cleaned["country"],
        postal_code=cleaned["postal_code"],
        message=cleaned["message"],
        notes=cleaned["notes"],
        consent_to_contact=cleaned["consent_to_contact"],
        category_label=category_label,
        category_id=category.pk if category is not None else None,
    )
    return LeadRowValidation(row.row_number, _display(row), validated, tuple(issues))


def validate_lead_import(uploaded_file, *, business) -> LeadImportValidationResult:
    """Run the complete non-writing historical Lead validation pipeline."""

    parsed_file = parse_csv_upload(uploaded_file, LEAD_IMPORT_SCHEMA)
    row_results = (
        ()
        if parsed_file.has_errors
        else tuple(validate_lead_row(row, business=business) for row in parsed_file.rows)
    )
    summary = ImportPreviewSummary(
        rows_detected=parsed_file.rows_detected,
        rows_valid=sum(row.is_valid for row in row_results),
        rows_warning=sum(row.has_warnings for row in row_results),
        rows_error=sum(row.has_errors for row in row_results),
    )
    return LeadImportValidationResult(
        parsed_file=parsed_file,
        row_results=row_results,
        summary=summary,
    )
