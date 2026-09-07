from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter
from pathlib import PurePath
from typing import BinaryIO

from .constants import DEFAULT_CSV_LIMITS, FORBIDDEN_CSV_COLUMNS, CSVLimits
from .schemas import ImportSchema, normalize_header
from .types import CSVRow, ImportIssue, IssueSeverity, ParsedImportFile


def _issue(
    code: str,
    message: str,
    *,
    row_number: int | None = None,
    column: str | None = None,
) -> ImportIssue:
    return ImportIssue(
        code=code,
        message=message,
        severity=IssueSeverity.ERROR,
        row_number=row_number,
        column=column,
    )


def _read_limited_payload(uploaded_file: BinaryIO, maximum_bytes: int) -> bytes:
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    payload = uploaded_file.read(maximum_bytes + 1)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    return payload


def _result(
    *,
    filename: str,
    payload: bytes,
    rows_detected: int = 0,
    headers: tuple[str, ...] = (),
    rows: tuple[CSVRow, ...] = (),
    issues: list[ImportIssue] | tuple[ImportIssue, ...] = (),
) -> ParsedImportFile:
    return ParsedImportFile(
        original_filename=filename,
        byte_size=len(payload),
        file_digest=hashlib.sha256(payload).hexdigest(),
        rows_detected=rows_detected,
        headers=headers,
        rows=rows,
        issues=tuple(issues),
    )


def parse_csv_upload(
    uploaded_file: BinaryIO,
    schema: ImportSchema,
    *,
    limits: CSVLimits = DEFAULT_CSV_LIMITS,
) -> ParsedImportFile:
    """Parse CSV structure without touching models or causing application side effects."""

    filename = PurePath(str(getattr(uploaded_file, "name", "upload.csv"))).name
    payload = _read_limited_payload(uploaded_file, limits.maximum_upload_bytes)

    if not filename.lower().endswith(".csv"):
        return _result(
            filename=filename,
            payload=payload,
            issues=[_issue("invalid_file_type", "Upload a CSV file with a .csv extension.")],
        )
    if not payload:
        return _result(
            filename=filename,
            payload=payload,
            issues=[_issue("empty_upload", "The uploaded CSV file is empty.")],
        )
    if len(payload) > limits.maximum_upload_bytes:
        return _result(
            filename=filename,
            payload=payload,
            issues=[
                _issue(
                    "file_too_large",
                    f"CSV files cannot exceed {limits.maximum_upload_bytes} bytes.",
                )
            ],
        )

    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _result(
            filename=filename,
            payload=payload,
            issues=[_issue("invalid_encoding", "CSV files must be UTF-8 encoded.")],
        )

    if "\x00" in decoded:
        return _result(
            filename=filename,
            payload=payload,
            issues=[_issue("malformed_csv", "The CSV file contains invalid null characters.")],
        )

    parsed_rows: list[tuple[int, list[str]]] = []
    nonblank_row_count = 0
    reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
    try:
        for raw_row in reader:
            parsed_rows.append((reader.line_num, raw_row))
            if any(cell.strip() for cell in raw_row):
                nonblank_row_count += 1
                # One nonblank row is the header; retain only the first row over
                # the data limit so the caller receives a bounded error result.
                if nonblank_row_count >= limits.maximum_data_rows + 2:
                    break
    except csv.Error:
        return _result(
            filename=filename,
            payload=payload,
            issues=[
                _issue(
                    "malformed_csv",
                    "The CSV structure is malformed and could not be read.",
                    row_number=max(reader.line_num, 1),
                )
            ],
        )

    nonblank_rows = [
        (row_number, row) for row_number, row in parsed_rows if any(cell.strip() for cell in row)
    ]
    if not nonblank_rows:
        return _result(
            filename=filename,
            payload=payload,
            issues=[_issue("missing_header", "The CSV file must include a header row.")],
        )

    header_row_number, raw_headers = nonblank_rows[0]
    headers = tuple(normalize_header(header) for header in raw_headers)
    issues: list[ImportIssue] = []

    if len(headers) > limits.maximum_columns:
        issues.append(
            _issue(
                "too_many_columns",
                f"CSV files cannot contain more than {limits.maximum_columns} columns.",
                row_number=header_row_number,
            )
        )

    for position, raw_header in enumerate(raw_headers, start=1):
        if len(raw_header) > limits.maximum_cell_characters:
            issues.append(
                _issue(
                    "cell_too_long",
                    (
                        f"Header column {position} exceeds the "
                        f"{limits.maximum_cell_characters}-character limit."
                    ),
                    row_number=header_row_number,
                )
            )

    for position, header in enumerate(headers, start=1):
        if not header:
            issues.append(
                _issue(
                    "blank_header",
                    f"Column {position} has a blank header.",
                    row_number=header_row_number,
                )
            )

    for header, count in Counter(headers).items():
        if header and count > 1:
            issues.append(
                _issue(
                    "duplicate_header",
                    f"The CSV header {header!r} appears more than once.",
                    row_number=header_row_number,
                    column=header,
                )
            )

    header_set = set(headers)
    for required_column in sorted(set(schema.required_columns) - header_set):
        issues.append(
            _issue(
                "missing_required_header",
                f"Missing required CSV column: {required_column}.",
                column=required_column,
            )
        )

    forbidden_headers = sorted(header_set & (FORBIDDEN_CSV_COLUMNS | set(schema.forbidden_columns)))
    for header in forbidden_headers:
        issues.append(
            _issue(
                "forbidden_header",
                f"The CSV column {header!r} cannot be imported.",
                column=header,
            )
        )

    if schema.strict_headers:
        unknown_headers = sorted(
            header_set
            - set(schema.allowed_columns)
            - FORBIDDEN_CSV_COLUMNS
            - set(schema.forbidden_columns)
            - {""}
        )
        for header in unknown_headers:
            issues.append(
                _issue(
                    "unexpected_header",
                    f"Unexpected CSV column: {header}.",
                    column=header,
                )
            )

    data_rows = nonblank_rows[1:]
    if not data_rows:
        issues.append(_issue("no_data_rows", "The CSV file does not contain any data rows."))
        return _result(filename=filename, payload=payload, headers=headers, issues=issues)

    rows: list[CSVRow] = []
    for data_index, (row_number, raw_row) in enumerate(data_rows, start=1):
        if data_index > limits.maximum_data_rows:
            issues.append(
                _issue(
                    "too_many_rows",
                    f"CSV files cannot contain more than {limits.maximum_data_rows} data rows.",
                    row_number=row_number,
                )
            )
            break

        if len(raw_row) < len(headers):
            issues.append(
                _issue(
                    "too_few_values",
                    f"Row {row_number} has fewer values than the header row.",
                    row_number=row_number,
                )
            )
            continue
        if len(raw_row) > len(headers):
            issues.append(
                _issue(
                    "too_many_values",
                    f"Row {row_number} has more values than the header row.",
                    row_number=row_number,
                )
            )
            if len(raw_row) > limits.maximum_columns:
                issues.append(
                    _issue(
                        "too_many_columns",
                        f"Row {row_number} exceeds the {limits.maximum_columns}-column limit.",
                        row_number=row_number,
                    )
                )
            continue

        row_values: dict[str, str] = {}
        row_has_cell_error = False
        for header, raw_value in zip(headers, raw_row, strict=True):
            if len(raw_value) > limits.maximum_cell_characters:
                issues.append(
                    _issue(
                        "cell_too_long",
                        (
                            f"Row {row_number}, column {header or '(blank)'} exceeds the "
                            f"{limits.maximum_cell_characters}-character limit."
                        ),
                        row_number=row_number,
                        column=header or None,
                    )
                )
                row_has_cell_error = True
            if header:
                row_values[header] = raw_value.strip()

        if not row_has_cell_error:
            rows.append(CSVRow(row_number=row_number, values=row_values))

    return _result(
        filename=filename,
        payload=payload,
        rows_detected=len(data_rows),
        headers=headers,
        rows=tuple(rows),
        issues=issues,
    )
