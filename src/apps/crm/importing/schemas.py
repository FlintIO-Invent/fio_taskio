from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .constants import FORBIDDEN_CSV_COLUMNS
from .types import ImportType


def normalize_header(value: str | None) -> str:
    return (value or "").strip().lower()


@dataclass(frozen=True)
class ImportSchema:
    """An explicit allowlist for one version of an entity import."""

    import_type: ImportType | str
    version: str
    required_columns: tuple[str, ...]
    optional_columns: tuple[str, ...] = ()
    server_derived_fields: tuple[str, ...] = ()
    forbidden_columns: tuple[str, ...] = ()
    defaults: Mapping[str, Any] = field(default_factory=dict)
    strict_headers: bool = True

    def __post_init__(self) -> None:
        import_type = ImportType(self.import_type)
        required = tuple(normalize_header(column) for column in self.required_columns)
        optional = tuple(normalize_header(column) for column in self.optional_columns)
        server_derived = tuple(normalize_header(column) for column in self.server_derived_fields)
        forbidden_columns = tuple(normalize_header(column) for column in self.forbidden_columns)

        declared_csv_columns = required + optional
        duplicates = [
            column
            for column, count in Counter(declared_csv_columns).items()
            if column and count > 1
        ]
        if not self.version.strip():
            raise ValueError("Import schema version cannot be blank.")
        if not required:
            raise ValueError("Import schemas must declare at least one required column.")
        if any(not column for column in declared_csv_columns + server_derived + forbidden_columns):
            raise ValueError("Import schema columns cannot be blank.")
        if duplicates:
            raise ValueError(f"Import schema contains duplicate columns: {', '.join(duplicates)}")

        forbidden = sorted(set(declared_csv_columns) & FORBIDDEN_CSV_COLUMNS)
        if forbidden:
            raise ValueError(
                "Tenant and ownership fields cannot be accepted from CSV: " + ", ".join(forbidden)
            )

        overlapping_server_fields = sorted(set(declared_csv_columns) & set(server_derived))
        if overlapping_server_fields:
            raise ValueError(
                "Server-derived fields cannot also be CSV columns: "
                + ", ".join(overlapping_server_fields)
            )

        overlapping_forbidden_fields = sorted(set(declared_csv_columns) & set(forbidden_columns))
        if overlapping_forbidden_fields:
            raise ValueError(
                "Forbidden fields cannot also be CSV columns: "
                + ", ".join(overlapping_forbidden_fields)
            )

        normalized_defaults = {
            normalize_header(column): value for column, value in self.defaults.items()
        }
        allowed_default_fields = set(optional) | set(server_derived)
        unknown_defaults = sorted(set(normalized_defaults) - allowed_default_fields)
        if unknown_defaults:
            raise ValueError(
                "Defaults must target optional or server-derived fields: "
                + ", ".join(unknown_defaults)
            )

        object.__setattr__(self, "import_type", import_type)
        object.__setattr__(self, "version", self.version.strip())
        object.__setattr__(self, "required_columns", required)
        object.__setattr__(self, "optional_columns", optional)
        object.__setattr__(self, "server_derived_fields", server_derived)
        object.__setattr__(self, "forbidden_columns", forbidden_columns)
        object.__setattr__(self, "defaults", MappingProxyType(normalized_defaults))

    @property
    def allowed_columns(self) -> tuple[str, ...]:
        return self.required_columns + self.optional_columns
