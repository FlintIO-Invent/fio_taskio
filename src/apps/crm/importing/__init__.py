"""Shared, side-effect-free foundations for CRM CSV imports.

KNOWN IMPORT COMPATIBILITY ISSUE: the historical Service CSV importer remains in
``apps.crm.views`` until its deliberate migration block. It does not yet use the
new size/row/cell limits or strict duplicate, unknown-header, and row-width checks.
Its explicit field mapping and tenant-scoped model queries remain unchanged.
"""

from .constants import DEFAULT_CSV_LIMITS, CSVLimits
from .parsing import parse_csv_upload
from .schemas import ImportSchema
from .types import CSVRow, ImportIssue, ImportType, IssueSeverity, ParsedImportFile

__all__ = [
    "CSVLimits",
    "CSVRow",
    "DEFAULT_CSV_LIMITS",
    "ImportIssue",
    "ImportSchema",
    "ImportType",
    "IssueSeverity",
    "ParsedImportFile",
    "parse_csv_upload",
]
