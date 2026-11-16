"""State of one import run: parsed rows, the report, and per-row error capture."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction

from core.common.domain.errors import DomainError

from ..contracts import ERROR, MODE_CREATE, MODE_UPSERT, WARNING, ImportProblem, ImportReport, SheetOutcome, SheetRows
from ..queries.sheets import (
    NOT_YET_IMPORTED,
    TEMPLATE_ONLY,
    TEMPLATE_ONLY_COLUMNS,
    Column,
    Sheet,
    find_sheet,
    normalize_header,
)
from .cells import CellError, parse, text

_SKIPPED_HEADERS = frozenset(normalize_header(name) for name in TEMPLATE_ONLY_COLUMNS)

# Model field names that differ from the column key that carries them.
_FIELD_ALIASES = {
    "setup_location": "station",
    "setup_location_id": "station",
    "station_slot_id": "station_slot",
    "slot_id": "slot",
    "kind_id": "kind",
    "position": "position_x",
}


# Sheet key → model label of the records its rows create, for "depends on a failed row" messages.
_SHEET_MODELS = {
    "departments": "labs.department",
    "groups": "labs.group",
    "countries": "labs.country",
    "cities": "labs.city",
    "buildings": "labs.building",
    "station_types": "labs.stationtype",
    "bench_groups": "labs.benchgroup",
    "bench_types": "labs.benchtype",
    "screen_sizes": "labs.displaysize",
    "resolutions": "labs.displayresolution",
    "manufacturers": "labs.equipmentmanufacturer",
    "rooms": "labs.room",
    "stations": "labs.station",
    "benches": "labs.bench",
    "equipment": "labs.equipment",
}


@dataclass(slots=True)
class Row:
    sheet: Sheet
    number: int
    values: dict[str, Any]
    failed: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        value = self.values.get(key)
        return default if value is None or value == [] else value


@dataclass(slots=True)
class BoundSheet:
    sheet: Sheet
    outcome: SheetOutcome
    rows: list[Row] = field(default_factory=list)


class RowFailed(Exception):
    """Stop processing the current row; its problems are already recorded."""


class ImportRun:
    def __init__(self, *, actor: Any, report: ImportReport, file_digest: str, mode: str = MODE_CREATE) -> None:
        self.actor = actor
        self.mode = mode
        self.report = report
        self.file_digest = file_digest
        self.bound: dict[str, BoundSheet] = {}
        # Natural keys of rows that failed, by model label, so dependent rows can point at the cause.
        self.failed_keys: dict[tuple[str, str], tuple[str, int]] = {}
        # Files written by commands (computing .rdp files); deleted again when the run is rolled back.
        self.written_files: list[tuple[Any, str]] = []

    @property
    def upsert(self) -> bool:
        return self.mode == MODE_UPSERT

    def existing(self, model: Any, row: Row, *, select_related: tuple[str, ...] = ()) -> Any | None:
        """The active record with the row's asset tag, or ``None``.

        Create mode refuses an existing asset tag with a clear message instead of a constraint conflict.
        The owner's update command locks the row; the active-SKU constraint fails the whole import when a
        concurrent import creates the same tag.
        """
        sku = row.get("sku")
        if sku is None:
            return None
        found = model._default_manager.select_related(*select_related).filter(sku=sku, deleted_at__isnull=True).first()
        if found is not None and not self.upsert:
            raise self.fail(
                row,
                f"Asset tag '{sku}' already exists. Import with mode Update existing (upsert) to change it.",
                key="sku",
                code="already_exists",
            )
        return found

    def failed_row(self, model: Any, value: Any) -> tuple[str, int] | None:
        return self.failed_keys.get((model._meta.label_lower, str(value).casefold()))

    def _remember_failure(self, bound: BoundSheet, row: Row, natural_key: str) -> None:
        model = _SHEET_MODELS.get(bound.sheet.key)
        value = row.get(natural_key)
        if model is not None and value is not None:
            self.failed_keys.setdefault((model, str(value).casefold()), (bound.sheet.name, row.number))

    def remember_file(self, storage: Any, name: str | None) -> None:
        if name:
            self.written_files.append((storage, name))

    def discard_written_files(self) -> None:
        for storage, name in self.written_files:
            try:
                storage.delete(name)
            except Exception:  # noqa: BLE001 - a leftover file must not hide the import report.
                pass
        self.written_files.clear()

    # ---- problems ----------------------------------------------------------------------------
    def problem(
        self,
        sheet: Sheet | str,
        message: str,
        *,
        row: int | None = None,
        column: str | None = None,
        code: str = "invalid",
        severity: str = ERROR,
    ) -> None:
        name = sheet if isinstance(sheet, str) else sheet.name
        self.report.problems.append(
            ImportProblem(sheet=name, severity=severity, code=code, message=message, row=row, column=column)
        )

    def header_for(self, sheet: Sheet, key: str | None) -> str | None:
        if key is None:
            return None
        key = _FIELD_ALIASES.get(key, key)
        if key.endswith("_id") and not any(column.key == key for column in sheet.columns):
            key = key[:-3]
        for column in sheet.columns:
            if column.key == key:
                return column.header
        return None

    def row_error(self, row: Row, message: str, *, key: str | None = None, code: str = "invalid") -> None:
        row.failed = True
        self.problem(row.sheet, message, row=row.number, column=self.header_for(row.sheet, key), code=code)

    def row_warning(self, row: Row, message: str, *, key: str | None = None, code: str = "not_imported") -> None:
        self.problem(
            row.sheet, message, row=row.number, column=self.header_for(row.sheet, key), code=code, severity=WARNING
        )

    def fail(self, row: Row, message: str, *, key: str | None = None, code: str = "invalid") -> RowFailed:
        self.row_error(row, message, key=key, code=code)
        return RowFailed()

    @contextmanager
    def capture(self, row: Row) -> Iterator[None]:
        """Run one row's writes in a savepoint; a failure records problems and undoes only this row."""
        try:
            with transaction.atomic():
                yield
        except RowFailed:
            row.failed = True
        except ValidationError as error:
            details = error.message_dict if hasattr(error, "message_dict") else {None: error.messages}
            for name, messages in details.items():
                key = None if name in (None, "__all__", "non_field_errors") else name
                for message in messages:
                    self.row_error(row, str(message), key=key, code="validation_failed")
        except DomainError as error:
            self.row_error(row, str(error), code=getattr(error, "code", "conflict"))
        except IntegrityError:
            self.row_error(
                row, "The row conflicts with an existing record (duplicate or missing reference).", code="conflict"
            )
        except ObjectDoesNotExist:
            self.row_error(row, "A referenced record does not exist.", code="not_found")

    # ---- binding -----------------------------------------------------------------------------
    def bind(self, uploaded: tuple[SheetRows, ...], order: tuple[Sheet, ...]) -> None:
        by_key: dict[str, SheetRows] = {}
        ignored = {normalize_header(name) for name in (*TEMPLATE_ONLY,)}
        later = {normalize_header(name) for name in NOT_YET_IMPORTED}
        for data in uploaded:
            spec = find_sheet(data.name)
            if spec is None:
                normalized = normalize_header(data.name)
                if normalized in later:
                    if data.rows:
                        self.problem(
                            data.name,
                            "This sheet is not imported yet; its rows were not read.",
                            code="sheet_not_imported",
                            severity=WARNING,
                        )
                elif normalized not in ignored:
                    self.report.unknown_sheets.append(data.name)
                continue
            if spec.key in by_key:
                self.problem(data.name, f"The workbook has the {spec.name} sheet twice.", code="duplicate_sheet")
                continue
            by_key[spec.key] = data
        for spec in order:
            found = by_key.get(spec.key)
            if found is None:
                continue
            outcome = SheetOutcome(key=spec.key, name=spec.name)
            self.report.sheets.append(outcome)
            bound = BoundSheet(sheet=spec, outcome=outcome)
            self.bound[spec.key] = bound
            if spec.read_only:
                continue
            self._bind_rows(bound, found)

    def _bind_rows(self, bound: BoundSheet, data: SheetRows) -> None:
        spec = bound.sheet
        columns: list[Column | None] = []
        for header in data.headers:
            if header is None:
                columns.append(None)
                continue
            wanted = normalize_header(header)
            match = next(
                (
                    column
                    for column in spec.columns
                    if wanted in {normalize_header(column.header), *(normalize_header(a) for a in column.aliases)}
                ),
                None,
            )
            columns.append(match)
        present = {column.key for column in columns if column is not None}
        missing = [c.header for c in spec.columns if c.required and c.key not in present]
        if missing:
            self.problem(spec, f"Required column missing: {', '.join(missing)}.", code="missing_column")
            return
        if data.truncated:
            self.problem(
                spec, "The sheet has more rows than one import accepts; split the file.", code="too_many_rows"
            )
        unknown_with_data: set[str] = set()
        multi = {c.key for c in spec.columns if sum(1 for other in spec.columns if other.key == c.key) > 1}
        for number, cells in data.rows:
            values: dict[str, Any] = {key: [] for key in multi}
            row = Row(sheet=spec, number=number, values=values)
            for index, cell in enumerate(cells):
                column = columns[index] if index < len(columns) else None
                if column is None:
                    header = data.headers[index] if index < len(data.headers) else None
                    if header and normalize_header(header) not in _SKIPPED_HEADERS and text(cell):
                        unknown_with_data.add(header)
                    continue
                try:
                    value = parse(cell, column)
                except CellError as error:
                    self.row_error(row, str(error), key=column.key, code="invalid_value")
                    continue
                if column.key in multi:
                    if value is not None and value not in values[column.key]:
                        values[column.key].append(value)
                elif value is not None:
                    values[column.key] = value
            for column in spec.columns:
                if column.required and row.get(column.key) is None and not row.failed:
                    self.row_error(row, f"{column.header} is required.", key=column.key, code="required")
            bound.rows.append(row)
        bound.outcome.rows = len(bound.rows)
        bound.outcome.ignored_columns = sorted(unknown_with_data)
        for header in bound.outcome.ignored_columns:
            self.problem(
                spec,
                f"Column '{header}' is not part of the template and was not imported.",
                column=header,
                code="column_not_imported",
                severity=WARNING,
            )

    # ---- running -----------------------------------------------------------------------------
    def rows(self, key: str) -> list[Row]:
        bound = self.bound.get(key)
        return [] if bound is None else bound.rows

    def each(self, key: str, handler: Callable[[Row], str | None], *, natural_key: str = "sku") -> None:
        """Run ``handler`` per valid row; it returns ``"created"``, ``"updated"`` or ``"existing"``. Duplicates fail."""
        bound = self.bound.get(key)
        if bound is None:
            return
        seen: dict[Any, int] = {}
        for row in bound.rows:
            identity = row.get(natural_key)
            if isinstance(identity, str):
                identity = identity.casefold()
            if identity is not None and identity in seen:
                self.row_error(
                    row, f"Duplicate of row {seen[identity]} in this sheet.", key=natural_key, code="duplicate"
                )
            elif identity is not None:
                seen[identity] = row.number
            if row.failed:
                bound.outcome.failed += 1
                self._remember_failure(bound, row, natural_key)
                continue
            result: str | None = None
            with self.capture(row):
                result = handler(row)
            if row.failed:
                bound.outcome.failed += 1
                self._remember_failure(bound, row, natural_key)
            elif result == "created":
                bound.outcome.created += 1
            elif result == "updated":
                bound.outcome.updated += 1
            elif result == "existing":
                bound.outcome.existing += 1


__all__ = ["BoundSheet", "ImportRun", "Row", "RowFailed"]
