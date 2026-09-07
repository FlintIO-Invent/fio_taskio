from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import TaskIOUser
from apps.appointments.models import Appointment
from apps.billings.models import Invoice
from apps.businesses.models import Business, BusinessUser

from .importing.clients import (
    CLIENT_ADVANCED_FIELDS,
    CLIENT_FORBIDDEN_FIELDS,
    CLIENT_IMPORT_DEFAULTS,
    CLIENT_IMPORT_SCHEMA,
    CLIENT_REQUIRED_FIELDS,
    CLIENT_SAMPLE_ROW,
    CLIENT_SERVER_DERIVED_FIELDS,
    CLIENT_STANDARD_OPTIONAL_FIELDS,
    CLIENT_STANDARD_TEMPLATE_FIELDS,
    ValidatedClientRow,
    normalize_client_row,
    summarize_client_validation,
    validate_client_import,
    validate_client_row,
)
from .importing.jobs import create_import_job
from .importing.parsing import parse_csv_upload
from .importing.types import CSVRow, ImportIssue, ImportType, IssueSeverity
from .models import ActivityLog, BusinessService, Client, ImportJob, Lead, ServiceCategory


class ClientImportValidationTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Client Import Workspace",
            slug="client-import-workspace",
            country="Sint Maarten",
        )
        self.valid_values = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@example.com",
            "phone": "+1 721 555 0100",
            "company_name": "Example Consulting",
            "street_address": "12 Example Street",
        }

    def row(self, **overrides):
        row_number = overrides.pop("row_number", 2)
        values = {**self.valid_values, **overrides}
        return CSVRow(row_number=row_number, values=values)

    def upload(self, rows, *, headers=CLIENT_STANDARD_TEMPLATE_FIELDS, name="clients.csv"):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return SimpleUploadedFile(name, output.getvalue().encode("utf-8"), content_type="text/csv")

    def issue_codes(self, result):
        return {issue.code for issue in result.issues}

    def test_schema_v1_has_explicit_standard_advanced_and_server_fields(self):
        self.assertEqual(CLIENT_IMPORT_SCHEMA.import_type, ImportType.CLIENTS)
        self.assertEqual(CLIENT_IMPORT_SCHEMA.version, "1")
        self.assertEqual(CLIENT_IMPORT_SCHEMA.required_columns, CLIENT_REQUIRED_FIELDS)
        self.assertEqual(
            CLIENT_IMPORT_SCHEMA.optional_columns,
            CLIENT_STANDARD_OPTIONAL_FIELDS + CLIENT_ADVANCED_FIELDS,
        )
        self.assertEqual(CLIENT_IMPORT_SCHEMA.server_derived_fields, CLIENT_SERVER_DERIVED_FIELDS)
        self.assertEqual(CLIENT_IMPORT_SCHEMA.forbidden_columns, CLIENT_FORBIDDEN_FIELDS)
        self.assertIs(CLIENT_IMPORT_DEFAULTS["consent_to_contact"], False)
        self.assertIs(CLIENT_IMPORT_DEFAULTS["is_active"], True)

    def test_standard_template_has_fictional_sample_and_expected_header(self):
        self.assertEqual(
            CLIENT_STANDARD_TEMPLATE_FIELDS,
            (
                "first_name",
                "last_name",
                "email",
                "phone",
                "company_name",
                "street_address",
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
            ),
        )
        self.assertEqual(set(CLIENT_SAMPLE_ROW), set(CLIENT_STANDARD_TEMPLATE_FIELDS))
        self.assertEqual(CLIENT_SAMPLE_ROW["email"], "jane@example.com")

    def test_valid_standard_row_returns_trusted_normalized_record(self):
        result = validate_client_import(
            self.upload(
                [
                    {
                        **self.valid_values,
                        "client_type": "business",
                        "client_status": "lead",
                        "district": "simpson_bay",
                        "country": "sint maarten",
                        "lead_source": "referral",
                        "priority": "medium",
                        "preferred_contact_method": "email",
                        "notes": "Imported customer",
                        "consent_to_contact": "false",
                    }
                ]
            ),
            business=self.business,
        )

        self.assertFalse(result.has_errors)
        self.assertEqual(result.summary.rows_detected, 1)
        self.assertEqual(result.summary.rows_valid, 1)
        validated = result.validated_rows[0]
        self.assertIsInstance(validated, ValidatedClientRow)
        self.assertEqual(validated.source_row_number, 2)
        self.assertEqual(validated.client_type, Client.ClientType.BUSINESS)
        self.assertEqual(validated.client_status, Client.ClientStatus.LEAD)
        self.assertEqual(validated.district, Client.DistrictChoices.SIMPSON_BAY)
        self.assertEqual(validated.country, "Sint Maarten")
        self.assertEqual(validated.lead_source, Client.LeadSource.REFERRAL)
        self.assertFalse(validated.consent_to_contact)
        self.assertTrue(validated.is_active)

    def test_each_required_value_has_row_level_blocking_issue(self):
        for field_name in CLIENT_REQUIRED_FIELDS:
            with self.subTest(field_name=field_name):
                validation = validate_client_row(
                    CSVRow(2, {**self.valid_values, field_name: ""}),
                    business=self.business,
                )
                matching = [issue for issue in validation.issues if issue.column == field_name]
                self.assertTrue(matching)
                self.assertEqual(matching[0].code, "required")
                self.assertEqual(matching[0].row_number, 2)
                self.assertTrue(validation.has_errors)

    def test_missing_optional_values_use_explicit_import_defaults(self):
        validation = validate_client_row(self.row(), business=self.business)

        self.assertTrue(validation.is_valid, validation.issues)
        validated = validation.validated_row
        self.assertEqual(validated.client_type, Client.ClientType.BUSINESS)
        self.assertEqual(validated.client_status, Client.ClientStatus.LEAD)
        self.assertEqual(validated.priority, Client.Priority.MEDIUM)
        self.assertEqual(
            validated.preferred_contact_method,
            Client.PreferredContactMethod.EMAIL,
        )
        self.assertFalse(validated.consent_to_contact)
        self.assertTrue(validated.is_active)
        self.assertEqual(validated.country, self.business.country)
        self.assertEqual(validated.postal_code, "")

    def test_consent_accepts_only_bounded_boolean_values(self):
        accepted = {
            "true": True,
            "TRUE": True,
            "yes": True,
            "1": True,
            "false": False,
            "FALSE": False,
            "no": False,
            "0": False,
            "": False,
        }
        for raw_value, expected in accepted.items():
            with self.subTest(raw_value=raw_value):
                validation = validate_client_row(
                    self.row(consent_to_contact=raw_value), business=self.business
                )
                self.assertTrue(validation.is_valid, validation.issues)
                self.assertEqual(validation.validated_row.consent_to_contact, expected)

        for raw_value in ("maybe", "yep", "enabled", "sure"):
            with self.subTest(raw_value=raw_value):
                validation = validate_client_row(
                    self.row(consent_to_contact=raw_value), business=self.business
                )
                self.assertIn("invalid_boolean", {issue.code for issue in validation.issues})
                self.assertFalse(validation.is_valid)

    def test_choice_fields_accept_canonical_and_case_normalized_values(self):
        values = {
            "client_type": "individual",
            "client_status": "active",
            "lead_source": "walk_in",
            "priority": "high",
            "preferred_contact_method": "whatsapp",
        }
        validation = validate_client_row(self.row(**values), business=self.business)

        self.assertTrue(validation.is_valid, validation.issues)
        validated = validation.validated_row
        self.assertEqual(validated.client_type, Client.ClientType.INDIVIDUAL)
        self.assertEqual(validated.client_status, Client.ClientStatus.ACTIVE)
        self.assertEqual(validated.lead_source, Client.LeadSource.WALK_IN)
        self.assertEqual(validated.priority, Client.Priority.HIGH)
        self.assertEqual(
            validated.preferred_contact_method,
            Client.PreferredContactMethod.WHATSAPP,
        )

    def test_each_invalid_choice_is_reported(self):
        for field_name in (
            "client_type",
            "client_status",
            "lead_source",
            "priority",
            "preferred_contact_method",
        ):
            with self.subTest(field_name=field_name):
                validation = validate_client_row(
                    self.row(**{field_name: "not-a-choice"}), business=self.business
                )
                issue = next(issue for issue in validation.issues if issue.column == field_name)
                self.assertEqual(issue.code, "invalid_choice")
                self.assertEqual(issue.row_number, 2)

    def test_preferred_language_is_free_text_not_a_choice(self):
        validation = validate_client_row(
            self.row(preferred_language="English / Dutch"), business=self.business
        )
        self.assertTrue(validation.is_valid, validation.issues)
        self.assertEqual(validation.validated_row.preferred_language, "English / Dutch")

    def test_email_and_secondary_email_use_django_validation(self):
        validation = validate_client_row(
            self.row(secondary_email="other@example.com"), business=self.business
        )
        self.assertTrue(validation.is_valid, validation.issues)
        self.assertEqual(validation.validated_row.secondary_email, "other@example.com")

        for field_name in ("email", "secondary_email"):
            with self.subTest(field_name=field_name):
                invalid = validate_client_row(
                    self.row(**{field_name: "not-an-email"}), business=self.business
                )
                issue = next(issue for issue in invalid.issues if issue.column == field_name)
                self.assertEqual(issue.code, "invalid_email")

    def test_website_validation_accepts_url_and_blank_but_rejects_invalid(self):
        for value in ("https://example.com/path", ""):
            with self.subTest(value=value):
                validation = validate_client_row(self.row(website=value), business=self.business)
                self.assertTrue(validation.is_valid, validation.issues)

        invalid = validate_client_row(self.row(website="not a valid URL"), business=self.business)
        issue = next(issue for issue in invalid.issues if issue.column == "website")
        self.assertEqual(issue.code, "invalid_url")

    def test_model_field_max_lengths_are_enforced(self):
        field_names = (
            "first_name",
            "last_name",
            "phone",
            "company_name",
            "street_address",
            "job_title",
        )
        for field_name in field_names:
            with self.subTest(field_name=field_name):
                maximum = Client._meta.get_field(field_name).max_length
                invalid = validate_client_row(
                    self.row(**{field_name: "x" * (maximum + 1)}), business=self.business
                )
                issue = next(issue for issue in invalid.issues if issue.column == field_name)
                self.assertEqual(issue.code, "max_length")

    def test_phone_values_remain_text_without_destructive_normalization(self):
        phone_values = (
            "+1 721 555 0123",
            "0698765432",
            "(721) 555-0123",
        )
        for phone in phone_values:
            with self.subTest(phone=phone):
                validation = validate_client_row(self.row(phone=phone), business=self.business)
                self.assertTrue(validation.is_valid, validation.issues)
                self.assertEqual(validation.validated_row.phone, phone)

    def test_surrounding_whitespace_is_trimmed_and_internal_spacing_preserved(self):
        validation = validate_client_row(
            self.row(
                first_name="  Jane  ",
                company_name="  Example   Consulting, N.V.  ",
                phone="  +1 (721) 555-0100  ",
                notes="  Keep  internal   spacing.  ",
            ),
            business=self.business,
        )

        self.assertTrue(validation.is_valid, validation.issues)
        validated = validation.validated_row
        self.assertEqual(validated.first_name, "Jane")
        self.assertEqual(validated.company_name, "Example   Consulting, N.V.")
        self.assertEqual(validated.phone, "+1 (721) 555-0100")
        self.assertEqual(validated.notes, "Keep  internal   spacing.")

    def test_address_rules_reuse_country_and_postal_normalization(self):
        dutch_business = Business.objects.create(
            name="Dutch Import Workspace",
            slug="dutch-import-workspace",
            country="Netherlands",
        )
        validation = validate_client_row(
            self.row(country="netherlands", district="Amsterdam", postal_code="1015bj"),
            business=dutch_business,
        )

        self.assertTrue(validation.is_valid, validation.issues)
        self.assertEqual(validation.validated_row.country, "Netherlands")
        self.assertEqual(validation.validated_row.district, "Amsterdam")
        self.assertEqual(validation.validated_row.postal_code, "1015 BJ")

        invalid_country = validate_client_row(self.row(country="Atlantis"), business=self.business)
        issue = next(issue for issue in invalid_country.issues if issue.column == "country")
        self.assertEqual(issue.code, "invalid_country")

    def test_advanced_fields_are_supported_without_aliases(self):
        validation = validate_client_row(
            self.row(
                business_legal_name="Example Consulting N.V.",
                trade_name="Example Co",
                website="https://example.com",
                job_title="Operations Manager",
                secondary_email="jane.secondary@example.com",
                communication_notes="Prefers morning calls.",
            ),
            business=self.business,
        )

        self.assertTrue(validation.is_valid, validation.issues)
        self.assertEqual(validation.validated_row.trade_name, "Example Co")
        self.assertEqual(
            validation.validated_row.secondary_email,
            "jane.secondary@example.com",
        )

    def test_non_importable_headers_are_rejected_before_client_validation(self):
        for forbidden_field in ("business_id", "assigned_to", "is_active"):
            with self.subTest(forbidden_field=forbidden_field):
                headers = CLIENT_STANDARD_TEMPLATE_FIELDS + (forbidden_field,)
                upload = self.upload(
                    [{**self.valid_values, forbidden_field: "unsafe"}], headers=headers
                )
                with mock.patch("apps.crm.importing.clients.validate_client_rows") as row_validator:
                    result = validate_client_import(upload, business=self.business)
                self.assertIn("forbidden_header", self.issue_codes(result))
                row_validator.assert_not_called()

    def test_row_numbers_match_original_csv_lines(self):
        result = validate_client_import(
            self.upload(
                [
                    self.valid_values,
                    {**self.valid_values, "email": "invalid"},
                ]
            ),
            business=self.business,
        )

        invalid_issue = next(issue for issue in result.issues if issue.code == "invalid_email")
        self.assertEqual(invalid_issue.row_number, 3)
        self.assertEqual(invalid_issue.column, "email")

    def test_validated_row_exposes_fixed_executor_allowlist_only(self):
        validation = validate_client_row(self.row(), business=self.business)

        client_fields = validation.validated_row.as_client_fields()
        self.assertNotIn("source_row_number", client_fields)
        for forbidden in set(CLIENT_FORBIDDEN_FIELDS) - {"is_active"}:
            self.assertNotIn(forbidden, client_fields)
        self.assertEqual(client_fields["is_active"], True)
        self.assertEqual(
            set(client_fields),
            set(ValidatedClientRow.__dataclass_fields__) - {"source_row_number"},
        )

    def test_validation_has_no_model_or_email_side_effects(self):
        tracked_models = (
            Client,
            Lead,
            BusinessService,
            ServiceCategory,
            Appointment,
            Invoice,
            ActivityLog,
        )
        before = {model: model.objects.count() for model in tracked_models}
        mail_count = len(mail.outbox)

        result = validate_client_import(
            self.upload([{**self.valid_values, "consent_to_contact": "true"}]),
            business=self.business,
        )

        self.assertFalse(result.has_errors)
        for model, count in before.items():
            self.assertEqual(model.objects.count(), count)
        self.assertEqual(len(mail.outbox), mail_count)

    def test_all_valid_pipeline_summary(self):
        rows = [{**self.valid_values, "email": f"client{index}@example.com"} for index in range(10)]
        result = validate_client_import(self.upload(rows), business=self.business)

        self.assertEqual(result.summary.rows_detected, 10)
        self.assertEqual(result.summary.rows_valid, 10)
        self.assertEqual(result.summary.rows_warning, 0)
        self.assertEqual(result.summary.rows_error, 0)

    def test_mixed_pipeline_summary_counts_error_rows_not_issue_count(self):
        rows = [
            {**self.valid_values, "email": "one@example.com"},
            {**self.valid_values, "email": "invalid", "phone": ""},
            {**self.valid_values, "email": "three@example.com"},
            {**self.valid_values, "first_name": "", "last_name": ""},
            {**self.valid_values, "email": "five@example.com"},
        ]
        result = validate_client_import(self.upload(rows), business=self.business)

        self.assertEqual(result.summary.rows_detected, 5)
        self.assertEqual(result.summary.rows_valid, 3)
        self.assertEqual(result.summary.rows_warning, 0)
        self.assertEqual(result.summary.rows_error, 2)
        self.assertEqual(len(result.validated_rows), 3)

    def test_warning_row_remains_valid_and_counts_in_both_columns(self):
        result = validate_client_import(self.upload([self.valid_values]), business=self.business)
        warned_row = replace(
            result.row_results[0],
            issues=(
                ImportIssue(
                    row_number=2,
                    column="notes",
                    severity=IssueSeverity.WARNING,
                    code="example_warning",
                    message="A non-blocking warning.",
                ),
            ),
        )

        summary = summarize_client_validation(result.parsed_file, (warned_row,))

        self.assertEqual(summary.rows_valid, 1)
        self.assertEqual(summary.rows_warning, 1)
        self.assertEqual(summary.rows_error, 0)

    def test_structural_errors_skip_client_field_validation(self):
        headers = tuple(field for field in CLIENT_STANDARD_TEMPLATE_FIELDS if field != "email")
        with mock.patch("apps.crm.importing.clients.validate_client_rows") as validator:
            result = validate_client_import(
                self.upload([self.valid_values], headers=headers), business=self.business
            )

        self.assertIn("missing_required_header", self.issue_codes(result))
        self.assertEqual(result.row_results, ())
        validator.assert_not_called()

    def test_normalize_client_row_does_not_retain_arbitrary_keys(self):
        normalized, issues = normalize_client_row(
            CSVRow(2, {**self.valid_values, "arbitrary_model_field": "unsafe"}),
            business=self.business,
        )
        self.assertNotIn("arbitrary_model_field", normalized)
        self.assertFalse(issues)


class ClientImportJobIntegrationTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(
            name="Job Client Import",
            slug="job-client-import",
            country="Sint Maarten",
        )
        self.user = TaskIOUser.objects.create_user(
            email="client-import-owner@example.com",
            password="testpass123",
        )
        BusinessUser.objects.create(
            business=self.business,
            user=self.user,
            role=BusinessUser.Role.OWNER,
        )
        self.valid_values = {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@example.com",
            "phone": "+1 721 555 0100",
            "company_name": "Example Consulting",
            "street_address": "12 Example Street",
        }

    def upload(self, rows, *, headers=CLIENT_STANDARD_TEMPLATE_FIELDS):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return SimpleUploadedFile("clients.csv", output.getvalue().encode("utf-8"))

    def create_job(self, upload):
        parsed_file = parse_csv_upload(upload, CLIENT_IMPORT_SCHEMA)
        return create_import_job(
            business=self.business,
            actor=self.user,
            import_type=ImportType.CLIENTS,
            schema_version=CLIENT_IMPORT_SCHEMA.version,
            parsed_file=parsed_file,
            lifetime=timedelta(hours=1),
        )

    def test_valid_file_moves_uploaded_through_validated_to_ready(self):
        upload = self.upload([self.valid_values, self.valid_values])
        job = self.create_job(upload)

        result = validate_client_import(upload, business=self.business, job=job)
        job.refresh_from_db()

        self.assertFalse(result.has_errors)
        self.assertEqual(job.status, ImportJob.Status.READY)
        self.assertEqual(job.rows_detected, 2)
        self.assertEqual(job.rows_valid, 2)
        self.assertEqual(job.rows_warning, 0)
        self.assertEqual(job.rows_error, 0)

    def test_invalid_rows_stop_at_validated_and_are_not_confirmable(self):
        upload = self.upload(
            [
                self.valid_values,
                {**self.valid_values, "email": "invalid", "phone": ""},
            ]
        )
        job = self.create_job(upload)

        result = validate_client_import(upload, business=self.business, job=job)
        job.refresh_from_db()

        self.assertTrue(result.has_errors)
        self.assertEqual(job.status, ImportJob.Status.VALIDATED)
        self.assertEqual(job.rows_detected, 2)
        self.assertEqual(job.rows_valid, 1)
        self.assertEqual(job.rows_error, 1)
        with self.assertRaisesMessage(ValidationError, "not ready"):
            job.assert_confirmable(at=timezone.now())

    def test_structurally_invalid_file_never_becomes_ready(self):
        headers = tuple(field for field in CLIENT_STANDARD_TEMPLATE_FIELDS if field != "email")
        upload = self.upload([self.valid_values], headers=headers)
        job = self.create_job(upload)

        result = validate_client_import(upload, business=self.business, job=job)
        job.refresh_from_db()

        self.assertTrue(result.has_errors)
        self.assertEqual(job.status, ImportJob.Status.VALIDATED)
        self.assertEqual(job.rows_valid, 0)
        self.assertEqual(job.rows_error, 0)

    def test_job_must_match_current_business_type_and_schema(self):
        upload = self.upload([self.valid_values])
        job = self.create_job(upload)
        other_business = Business.objects.create(name="Other", slug="other-client-job")

        with self.assertRaisesMessage(ValidationError, "current business"):
            validate_client_import(upload, business=other_business, job=job)

        job.import_type = ImportJob.ImportType.LEADS
        job.save(update_fields=["import_type"])
        with self.assertRaisesMessage(ValidationError, "Client schema"):
            validate_client_import(upload, business=self.business, job=job)

        job.import_type = ImportJob.ImportType.CLIENTS
        job.schema_version = "other"
        job.save(update_fields=["import_type", "schema_version"])
        with self.assertRaisesMessage(ValidationError, "schema version"):
            validate_client_import(upload, business=self.business, job=job)

    def test_job_digest_and_expiry_are_enforced_before_metadata_update(self):
        upload = self.upload([self.valid_values])
        job = self.create_job(upload)
        different_upload = self.upload([{**self.valid_values, "email": "different@example.com"}])

        with self.assertRaisesMessage(ValidationError, "file digest"):
            validate_client_import(different_upload, business=self.business, job=job)

        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["expires_at"])
        with self.assertRaisesMessage(ValidationError, "expired"):
            validate_client_import(upload, business=self.business, job=job)
