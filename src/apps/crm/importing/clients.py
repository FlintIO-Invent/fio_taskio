from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.businesses.localization import (
    PUBLIC_ADDRESS_COUNTRY_CHOICES,
    uses_sint_maarten_districts,
)
from apps.crm.forms import PrivateClientForm
from apps.crm.models import Client, ImportJob

from .parsing import parse_csv_upload
from .schemas import ImportSchema
from .types import CSVRow, ImportIssue, ImportPreviewSummary, ImportType, ParsedImportFile

CLIENT_REQUIRED_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "phone",
    "company_name",
    "street_address",
)

CLIENT_STANDARD_OPTIONAL_FIELDS = (
    "client_type",
    "client_status",
    "district",
    "country",
    "postal_code",
    "lead_source",
    "priority",
    "preferred_contact_method",
    "notes",
    "consent_to_contact",
)

CLIENT_ADVANCED_FIELDS = (
    "business_legal_name",
    "trade_name",
    "industry",
    "business_description",
    "website",
    "registration_number",
    "job_title",
    "department",
    "secondary_email",
    "secondary_phone",
    "whatsapp_number",
    "preferred_language",
    "interested_services",
    "message",
    "communication_notes",
)

CLIENT_STANDARD_TEMPLATE_FIELDS = CLIENT_REQUIRED_FIELDS + CLIENT_STANDARD_OPTIONAL_FIELDS

CLIENT_SERVER_DERIVED_FIELDS = (
    "business",
    "is_active",
)

CLIENT_FORBIDDEN_FIELDS = (
    "id",
    "business",
    "business_id",
    "created_by",
    "created_at",
    "updated_at",
    "assigned_to",
    "assigned_to_id",
    "last_contacted_at",
    "next_follow_up_at",
    "is_active",
)

CLIENT_IMPORT_DEFAULTS: dict[str, Any] = {
    "client_type": Client.ClientType.BUSINESS,
    "client_status": Client.ClientStatus.LEAD,
    "district": "",
    "country": "",
    "postal_code": "",
    "lead_source": "",
    "priority": Client.Priority.MEDIUM,
    "preferred_contact_method": Client.PreferredContactMethod.EMAIL,
    "notes": "",
    # Import-only privacy policy: missing CSV data must never manufacture consent.
    "consent_to_contact": False,
    **{field_name: "" for field_name in CLIENT_ADVANCED_FIELDS},
    "is_active": True,
}

CLIENT_IMPORT_SCHEMA = ImportSchema(
    import_type=ImportType.CLIENTS,
    version="1",
    required_columns=CLIENT_REQUIRED_FIELDS,
    optional_columns=CLIENT_STANDARD_OPTIONAL_FIELDS + CLIENT_ADVANCED_FIELDS,
    server_derived_fields=CLIENT_SERVER_DERIVED_FIELDS,
    forbidden_columns=CLIENT_FORBIDDEN_FIELDS,
    defaults=CLIENT_IMPORT_DEFAULTS,
)

CLIENT_SAMPLE_ROW = {
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com",
    "phone": "+1 721 555 0100",
    "company_name": "Example Consulting",
    "street_address": "12 Example Street",
    "client_type": Client.ClientType.BUSINESS,
    "client_status": Client.ClientStatus.LEAD,
    "district": Client.DistrictChoices.SIMPSON_BAY,
    "country": "Sint Maarten",
    "postal_code": "",
    "lead_source": Client.LeadSource.REFERRAL,
    "priority": Client.Priority.MEDIUM,
    "preferred_contact_method": Client.PreferredContactMethod.EMAIL,
    "notes": "Imported customer",
    "consent_to_contact": "false",
}

CLIENT_CHOICE_FIELDS = {
    "client_type": Client.ClientType.choices,
    "client_status": Client.ClientStatus.choices,
    "lead_source": Client.LeadSource.choices,
    "priority": Client.Priority.choices,
    "preferred_contact_method": Client.PreferredContactMethod.choices,
}


@dataclass(frozen=True)
class ValidatedClientRow:
    source_row_number: int
    first_name: str
    last_name: str
    email: str
    phone: str
    company_name: str
    street_address: str
    client_type: str
    client_status: str
    district: str
    country: str
    postal_code: str
    lead_source: str
    priority: str
    preferred_contact_method: str
    notes: str
    consent_to_contact: bool
    business_legal_name: str
    trade_name: str
    industry: str
    business_description: str
    website: str
    registration_number: str
    job_title: str
    department: str
    secondary_email: str
    secondary_phone: str
    whatsapp_number: str
    preferred_language: str
    interested_services: str
    message: str
    communication_notes: str
    is_active: bool = True

    def as_client_fields(self) -> dict[str, Any]:
        """Return the fixed future-executor allowlist, never arbitrary CSV keys."""

        return {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name != "source_row_number"
        }


@dataclass(frozen=True)
class ClientRowValidation:
    source_row_number: int
    validated_row: ValidatedClientRow | None
    issues: tuple[ImportIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(issue.severity.value == "error" for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity.value == "warning" for issue in self.issues)

    @property
    def is_valid(self) -> bool:
        return self.validated_row is not None and not self.has_errors


@dataclass(frozen=True)
class ClientImportValidationResult:
    parsed_file: ParsedImportFile
    row_results: tuple[ClientRowValidation, ...]
    summary: ImportPreviewSummary

    @property
    def issues(self) -> tuple[ImportIssue, ...]:
        return self.parsed_file.issues + tuple(
            issue for row_result in self.row_results for issue in row_result.issues
        )

    @property
    def has_errors(self) -> bool:
        return any(issue.severity.value == "error" for issue in self.issues)

    @property
    def validated_rows(self) -> tuple[ValidatedClientRow, ...]:
        return tuple(
            row_result.validated_row
            for row_result in self.row_results
            if row_result.validated_row is not None
        )


def _canonical_choice(value: str, choices) -> str:
    canonical_values = {
        str(choice_value).casefold(): str(choice_value) for choice_value, _ in choices
    }
    return canonical_values.get(value.casefold(), value)


def _canonical_country(value: str, business) -> str:
    choices = list(PUBLIC_ADDRESS_COUNTRY_CHOICES)
    business_country = (getattr(business, "country", "") or "").strip()
    if business_country:
        choices.append((business_country, business_country))
    return _canonical_choice(value, choices)


def _normalize_boolean(value: str, *, default: bool) -> bool:
    normalized = value.strip().casefold()
    if not normalized:
        return default
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    raise ValueError("Enter true, false, yes, no, 1, or 0.")


def normalize_client_row(
    row: CSVRow,
    *,
    business,
) -> tuple[dict[str, Any], tuple[ImportIssue, ...]]:
    """Apply only conservative CSV and import-policy normalization."""

    normalized: dict[str, Any] = {
        column: (row.values.get(column) or "").strip()
        for column in CLIENT_IMPORT_SCHEMA.allowed_columns
    }
    for field_name, default in CLIENT_IMPORT_DEFAULTS.items():
        if field_name == "is_active":
            continue
        if normalized.get(field_name, "") == "":
            normalized[field_name] = default

    normalized["country"] = _canonical_country(normalized["country"], business)
    if not normalized["country"]:
        normalized["country"] = (getattr(business, "country", "") or "").strip()

    for field_name, choices in CLIENT_CHOICE_FIELDS.items():
        value = str(normalized[field_name])
        if value:
            normalized[field_name] = _canonical_choice(value, choices)

    if uses_sint_maarten_districts(normalized["country"]):
        normalized["district"] = _canonical_choice(
            str(normalized["district"]), Client.DistrictChoices.choices
        )

    issues: list[ImportIssue] = []
    try:
        normalized["consent_to_contact"] = _normalize_boolean(
            str(normalized["consent_to_contact"]),
            default=False,
        )
    except ValueError as exc:
        issues.append(
            ImportIssue(
                row_number=row.row_number,
                column="consent_to_contact",
                code="invalid_boolean",
                message=str(exc),
            )
        )
        normalized["consent_to_contact"] = False

    return normalized, tuple(issues)


def _stable_issue_code(field_name: str, django_code: str | None) -> str:
    if field_name in {"email", "secondary_email"} and django_code == "invalid":
        return "invalid_email"
    if field_name == "website" and django_code == "invalid":
        return "invalid_url"
    if field_name == "country" and django_code == "invalid_choice":
        return "invalid_country"
    return django_code or "invalid"


def validate_client_row(row: CSVRow, *, business) -> ClientRowValidation:
    normalized, normalization_issues = normalize_client_row(row, business=business)

    # PrivateClientForm is used only as a read-only validation adapter. Neither
    # form.save() nor any Client persistence method is called in this block.
    form = PrivateClientForm(data=normalized, business=business)
    form.is_valid()

    issues = list(normalization_issues)
    for field_name, field_errors in form.errors.as_data().items():
        for error in field_errors:
            issues.append(
                ImportIssue(
                    row_number=row.row_number,
                    column=field_name,
                    code=_stable_issue_code(field_name, error.code),
                    message=error.messages[0],
                )
            )

    if any(issue.severity.value == "error" for issue in issues):
        return ClientRowValidation(
            source_row_number=row.row_number,
            validated_row=None,
            issues=tuple(issues),
        )

    cleaned = form.cleaned_data
    validated_row = ValidatedClientRow(
        source_row_number=row.row_number,
        first_name=cleaned["first_name"],
        last_name=cleaned["last_name"],
        email=cleaned["email"],
        phone=cleaned["phone"],
        company_name=cleaned["company_name"],
        street_address=cleaned["street_address"],
        client_type=cleaned["client_type"],
        client_status=cleaned["client_status"],
        district=cleaned["district"],
        country=cleaned["country"],
        postal_code=cleaned["postal_code"],
        lead_source=cleaned["lead_source"],
        priority=cleaned["priority"],
        preferred_contact_method=cleaned["preferred_contact_method"],
        notes=cleaned["notes"],
        consent_to_contact=cleaned["consent_to_contact"],
        business_legal_name=cleaned["business_legal_name"],
        trade_name=cleaned["trade_name"],
        industry=cleaned["industry"],
        business_description=cleaned["business_description"],
        website=cleaned["website"],
        registration_number=cleaned["registration_number"],
        job_title=cleaned["job_title"],
        department=cleaned["department"],
        secondary_email=cleaned["secondary_email"],
        secondary_phone=cleaned["secondary_phone"],
        whatsapp_number=cleaned["whatsapp_number"],
        preferred_language=cleaned["preferred_language"],
        interested_services=cleaned["interested_services"],
        message=cleaned["message"],
        communication_notes=cleaned["communication_notes"],
        is_active=True,
    )
    return ClientRowValidation(row.row_number, validated_row)


def validate_client_rows(rows: tuple[CSVRow, ...], *, business) -> tuple[ClientRowValidation, ...]:
    return tuple(validate_client_row(row, business=business) for row in rows)


def summarize_client_validation(
    parsed_file: ParsedImportFile,
    row_results: tuple[ClientRowValidation, ...],
) -> ImportPreviewSummary:
    return ImportPreviewSummary(
        rows_detected=parsed_file.rows_detected,
        rows_valid=sum(row_result.is_valid for row_result in row_results),
        rows_warning=sum(row_result.has_warnings for row_result in row_results),
        rows_error=sum(row_result.has_errors for row_result in row_results),
    )


def _update_import_job(job: ImportJob, result: ClientImportValidationResult, *, business) -> None:
    with transaction.atomic():
        locked_job = ImportJob.objects.select_for_update().get(pk=job.pk)
        if locked_job.business_id != business.pk:
            raise ValidationError("Import job does not belong to the current business.")
        if locked_job.import_type != ImportType.CLIENTS.value:
            raise ValidationError("Import job type does not match the Client schema.")
        if locked_job.schema_version != CLIENT_IMPORT_SCHEMA.version:
            raise ValidationError("Import job schema version does not match the Client schema.")
        if locked_job.file_digest != result.parsed_file.file_digest:
            raise ValidationError("Import job file digest does not match the uploaded CSV.")
        locked_job.assert_usable()

        locked_job.rows_detected = result.summary.rows_detected
        locked_job.rows_valid = result.summary.rows_valid
        locked_job.rows_warning = result.summary.rows_warning
        locked_job.rows_error = result.summary.rows_error
        locked_job.save(
            update_fields=[
                "rows_detected",
                "rows_valid",
                "rows_warning",
                "rows_error",
                "updated_at",
            ]
        )
        locked_job.transition_to(ImportJob.Status.VALIDATED)
        if not result.has_errors:
            locked_job.transition_to(ImportJob.Status.READY)


def validate_client_import(uploaded_file, *, business, job=None) -> ClientImportValidationResult:
    """Run the complete non-writing Client CSV validation pipeline."""

    parsed_file = parse_csv_upload(uploaded_file, CLIENT_IMPORT_SCHEMA)
    row_results = (
        () if parsed_file.has_errors else validate_client_rows(parsed_file.rows, business=business)
    )
    result = ClientImportValidationResult(
        parsed_file=parsed_file,
        row_results=row_results,
        summary=summarize_client_validation(parsed_file, row_results),
    )
    if job is not None:
        _update_import_job(job, result, business=business)
    return result
