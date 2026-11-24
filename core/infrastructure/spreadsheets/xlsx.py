"""Read and write .xlsx workbooks laid out as: row 1 title, row 2 column names, row 3 hints, data below.

The module is technical only: callers decide which sheets and columns mean something.
"""

from __future__ import annotations

import io
import os
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import IO, Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# A .xlsx is a zip archive; refuse archives that expand to more than this (zip bombs).
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
# Text that a spreadsheet program would run as a formula when written to a cell (CSV/formula injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_TITLE_FILL = PatternFill("solid", fgColor="1F3864")
_REQUIRED_FILL = PatternFill("solid", fgColor="1F3864")
_OPTIONAL_FILL = PatternFill("solid", fgColor="2F5597")
_READ_ONLY_FILL = PatternFill("solid", fgColor="7F7F7F")
_WHITE_BOLD = Font(bold=True, color="FFFFFF")
_HINT_FONT = Font(italic=True, color="595959", size=9)


class SpreadsheetUnreadable(Exception):
    """The file is not a readable .xlsx workbook, or it is too large once unpacked."""


@dataclass(frozen=True, slots=True)
class RawSheet:
    """One sheet as read: the header row and the non-empty data rows with their Excel row numbers."""

    name: str
    headers: tuple[str | None, ...]
    rows: tuple[tuple[int, tuple[Any, ...]], ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ColumnLayout:
    header: str
    hint: str = ""
    required: bool = False
    width: int = 18
    # A formula range used as a dropdown, e.g. "Departments!$A$4:$A$2000".
    choices: str | None = None
    read_only: bool = False


@dataclass(frozen=True, slots=True)
class SheetLayout:
    name: str
    title: str
    columns: tuple[ColumnLayout, ...]
    rows: tuple[tuple[Any, ...], ...] = ()
    hidden: bool = False
    # Plain sheets (README, lists) are written as-is: no title, header or hint rows.
    plain: bool = False
    dropdown_rows: int = 2000


def _check_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise SpreadsheetUnreadable("The workbook is too large once unpacked.")
    except zipfile.BadZipFile as error:
        raise SpreadsheetUnreadable("The file is not an .xlsx workbook.") from error


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _format_headers(values: Iterable[Any]) -> tuple[str | None, ...]:
    return tuple(None if _is_empty(value) else str(value).strip() for value in values)


def _read_native_sheet(worksheet: Any, header_row: int, first_data_row: int, max_data_rows: int) -> RawSheet | None:
    try:
        from xlsx_reader import MAX_XML_BYTES, read_sheet
    except ModuleNotFoundError as error:
        if error.name != "xlsx_reader":
            raise
        raise RuntimeError("XLSX_READER=native requires the native-xlsx extra.") from error

    # openpyxl resolves and validates the workbook package. Its read-only worksheet
    # exposes the member stream and styles used by the normal XML decoder.
    get_source = getattr(worksheet, "_get_source", None)
    date_styles = getattr(worksheet.parent, "_date_formats", None)
    shared_strings = getattr(worksheet, "_shared_strings", None)
    if get_source is None or date_styles is None or shared_strings is None:
        return None

    with get_source() as source:
        xml = source.read(MAX_XML_BYTES + 1)
    if len(xml) > MAX_XML_BYTES:
        return None
    decoded = read_sheet(
        xml,
        (header_row, first_data_row, max_data_rows),
        (worksheet.max_row, worksheet.max_column),
        list(date_styles),
        tuple(shared_strings),
    )
    if decoded is None:
        return None
    headers, rows, truncated = decoded
    return RawSheet(
        name=worksheet.title,
        headers=_format_headers(headers),
        rows=tuple((number, tuple(values)) for number, values in rows),
        truncated=truncated,
    )


def read_workbook(
    file: IO[bytes] | bytes,
    *,
    sheet_names: Iterable[str],
    header_row: int = 2,
    first_data_row: int = 4,
    max_data_rows: int = 5000,
) -> tuple[RawSheet, ...]:
    """Read the named sheets that exist in the file; cached formula results are read, not formulas.

    Each sheet stops after ``max_data_rows`` non-empty rows and is then marked ``truncated``.
    """
    data = file if isinstance(file, bytes) else file.read()
    _check_archive(data)
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as error:  # noqa: BLE001 - openpyxl raises many types for corrupt files.
        raise SpreadsheetUnreadable("The workbook could not be read.") from error
    wanted = set(sheet_names)
    sheets: list[RawSheet] = []
    use_native = os.environ.get("XLSX_READER") == "native" and 0 < header_row < first_data_row and max_data_rows >= 0
    try:
        for worksheet in workbook.worksheets:
            if worksheet.title not in wanted:
                continue
            if use_native:
                native_sheet = _read_native_sheet(worksheet, header_row, first_data_row, max_data_rows)
                if native_sheet is not None:
                    sheets.append(native_sheet)
                    continue
            header_cells = next(worksheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True), ())
            headers = list(header_cells)
            while headers and _is_empty(headers[-1]):
                headers.pop()
            width = len(headers)
            rows: list[tuple[int, tuple[Any, ...]]] = []
            truncated = False
            if width:
                for number, values in enumerate(
                    worksheet.iter_rows(min_row=first_data_row, max_col=width, values_only=True),
                    start=first_data_row,
                ):
                    if all(_is_empty(value) for value in values):
                        continue
                    if len(rows) >= max_data_rows:
                        truncated = True
                        break
                    padded = tuple(values) + (None,) * (width - len(values))
                    rows.append((number, padded))
            sheets.append(
                RawSheet(
                    name=worksheet.title,
                    headers=_format_headers(headers),
                    rows=tuple(rows),
                    truncated=truncated,
                )
            )
    finally:
        workbook.close()
    return tuple(sheets)


def safe_cell_value(value: Any) -> Any:
    """Return ``value`` so that a spreadsheet program shows it as text instead of running it."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _write_sheet(workbook: Workbook, layout: SheetLayout) -> None:
    sheet = workbook.create_sheet(layout.name)
    if layout.hidden:
        sheet.sheet_state = "hidden"
    if layout.plain:
        for row in layout.rows:
            sheet.append([safe_cell_value(value) for value in row])
        for index, column in enumerate(layout.columns, start=1):
            sheet.column_dimensions[get_column_letter(index)].width = column.width
        return
    count = max(len(layout.columns), 1)
    sheet.cell(row=1, column=1, value=layout.title).font = _WHITE_BOLD
    for index in range(1, count + 1):
        sheet.cell(row=1, column=index).fill = _TITLE_FILL
    for index, column in enumerate(layout.columns, start=1):
        letter = get_column_letter(index)
        header = sheet.cell(row=2, column=index, value=f"{column.header} *" if column.required else column.header)
        header.font = _WHITE_BOLD
        header.fill = _READ_ONLY_FILL if column.read_only else (_REQUIRED_FILL if column.required else _OPTIONAL_FILL)
        header.alignment = Alignment(wrap_text=True, vertical="center")
        hint = sheet.cell(row=3, column=index, value=column.hint)
        hint.font = _HINT_FONT
        hint.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.column_dimensions[letter].width = column.width
        if column.choices and not column.read_only:
            validation = DataValidation(type="list", formula1=f"={column.choices}", allow_blank=True)
            validation.error = "Pick a value from the list, or add it to its reference sheet first."
            validation.showErrorMessage = False  # a warning only: new values may be added elsewhere first
            sheet.add_data_validation(validation)
            validation.add(f"{letter}4:{letter}{3 + layout.dropdown_rows}")
    for row in layout.rows:
        sheet.append([safe_cell_value(value) for value in row])
    sheet.freeze_panes = "B4"
    sheet.row_dimensions[3].height = 30


def build_workbook(layouts: Sequence[SheetLayout]) -> bytes:
    """Write the sheets in order and return the .xlsx bytes."""
    workbook = Workbook()
    default = workbook.active
    for layout in layouts:
        _write_sheet(workbook, layout)
    if default is not None:
        workbook.remove(default)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


__all__ = [
    "XLSX_CONTENT_TYPE",
    "ColumnLayout",
    "RawSheet",
    "SheetLayout",
    "SpreadsheetUnreadable",
    "build_workbook",
    "read_workbook",
    "safe_cell_value",
]
