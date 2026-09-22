from dataclasses import dataclass


@dataclass(frozen=True)
class CSVLimits:
    maximum_upload_bytes: int = 2 * 1024 * 1024
    maximum_data_rows: int = 500
    maximum_columns: int = 50
    maximum_cell_characters: int = 10_000


DEFAULT_CSV_LIMITS = CSVLimits()

# These fields may only come from trusted server context, never from CSV input.
FORBIDDEN_CSV_COLUMNS = frozenset(
    {
        "business",
        "business_id",
        "tenant",
        "tenant_id",
        "workspace",
        "workspace_id",
        "created_by",
        "user",
        "user_id",
        "owner",
    }
)
