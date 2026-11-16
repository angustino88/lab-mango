"""Types exchanged by the workbook import: sheets read from a file, and the report about them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ERROR = "error"
WARNING = "warning"

# Import modes. ``create``: every asset tag must be new. ``upsert``: an asset tag that exists updates that
# record (blank cells keep the stored value; the asset tag itself never changes).
MODE_CREATE = "create"
MODE_UPSERT = "upsert"
MODES = (MODE_CREATE, MODE_UPSERT)
# (value, label) pairs; the OpenAPI enum name is pinned to these in config/openapi.py.
MODE_CHOICES = ((MODE_CREATE, "Create new"), (MODE_UPSERT, "Update existing"))


@dataclass(frozen=True, slots=True)
class SheetRows:
    """One sheet of an uploaded workbook: its column names (row 2) and non-empty data rows."""

    name: str
    headers: tuple[str | None, ...]
    rows: tuple[tuple[int, tuple[Any, ...]], ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ImportProblem:
    """A row or sheet problem. ``row`` is the Excel row number; ``column`` the template column name."""

    sheet: str
    severity: str
    code: str
    message: str
    row: int | None = None
    column: str | None = None


@dataclass(slots=True)
class SheetOutcome:
    """What one sheet did: rows read, created, updated, already present and unchanged, and failed."""

    key: str
    name: str
    rows: int = 0
    created: int = 0
    updated: int = 0
    existing: int = 0
    failed: int = 0
    ignored_columns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImportReport:
    dry_run: bool
    template_version: str | None
    mode: str = MODE_CREATE
    sheets: list[SheetOutcome] = field(default_factory=list)
    problems: list[ImportProblem] = field(default_factory=list)
    unknown_sheets: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(problem.severity == ERROR for problem in self.problems)

    @property
    def error_count(self) -> int:
        return sum(1 for problem in self.problems if problem.severity == ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for problem in self.problems if problem.severity == WARNING)

    @property
    def created_count(self) -> int:
        return sum(sheet.created for sheet in self.sheets)

    @property
    def updated_count(self) -> int:
        return sum(sheet.updated for sheet in self.sheets)

    @property
    def existing_count(self) -> int:
        return sum(sheet.existing for sheet in self.sheets)


__all__ = [
    "ERROR",
    "MODES",
    "MODE_CHOICES",
    "MODE_CREATE",
    "MODE_UPSERT",
    "WARNING",
    "ImportProblem",
    "ImportReport",
    "SheetOutcome",
    "SheetRows",
]
