from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ImportType(StrEnum):
    CLIENTS = "clients"
    LEADS = "leads"
    SERVICES = "services"


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ImportIssue:
    code: str
    message: str
    severity: IssueSeverity = IssueSeverity.ERROR
    row_number: int | None = None
    column: str | None = None


@dataclass(frozen=True)
class CSVRow:
    row_number: int
    values: dict[str, str]


@dataclass(frozen=True)
class ParsedImportFile:
    original_filename: str
    byte_size: int
    file_digest: str
    rows_detected: int = 0
    headers: tuple[str, ...] = ()
    rows: tuple[CSVRow, ...] = ()
    issues: tuple[ImportIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == IssueSeverity.ERROR for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == IssueSeverity.WARNING for issue in self.issues)


@dataclass(frozen=True)
class ImportPreviewSummary:
    rows_detected: int = 0
    rows_valid: int = 0
    rows_warning: int = 0
    rows_error: int = 0


@dataclass(frozen=True)
class ImportAccessDecision:
    allowed: bool
    code: str
    message: str = ""


@dataclass(frozen=True)
class ImportPreviewBinding:
    """Trusted metadata that a future server-side preview payload must match."""

    job_id: str
    business_id: int
    actor_id: int
    schema_version: str
    file_digest: str
    expires_at: Any


@dataclass(frozen=True)
class StoredPreviewPayload:
    binding: ImportPreviewBinding
    normalized_rows: tuple[dict[str, Any], ...] = field(default_factory=tuple)
