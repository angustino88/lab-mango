"""Read and write .xlsx workbooks laid out as: row 1 title, row 2 column names, row 3 hints, data below.

The module is technical only: callers decide which sheets and columns mean something.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import IO, Any
from xml.etree import ElementTree

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from python_calamine import CalamineError, CalamineWorkbook, SheetTypeEnum

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# A .xlsx is a zip archive; refuse archives that expand to more than this (zip bombs).
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
# Text that a spreadsheet program would run as a formula when written to a cell (CSV/formula injection).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_DOCUMENT_REL = f"{_DOCUMENT_REL_NS}/officeDocument"

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


def _workbook_part(archive: zipfile.ZipFile) -> str:
    """The archive path of the main workbook part, from the package relationships."""
    root = ElementTree.fromstring(archive.read("_rels/.rels"))
    for relationship in root.iter(f"{{{_PACKAGE_REL_NS}}}Relationship"):
        if relationship.get("Type") == _OFFICE_DOCUMENT_REL:
            return _resolve_target("", relationship.get("Target", ""))
    raise KeyError("officeDocument")


def _resolve_target(base_dir: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base_dir, target))


def _sheet_parts(archive: zipfile.ZipFile) -> dict[str, str]:
    """Sheet name -> archive path of its worksheet XML."""
    workbook_part = _workbook_part(archive)
    base_dir, file_name = posixpath.split(workbook_part)
    rels = ElementTree.fromstring(archive.read(posixpath.join(base_dir, "_rels", f"{file_name}.rels")))
    targets = {
        relationship.get("Id"): _resolve_target(base_dir, relationship.get("Target", ""))
        for relationship in rels.iter(f"{{{_PACKAGE_REL_NS}}}Relationship")
    }
    workbook = ElementTree.fromstring(archive.read(workbook_part))
    parts: dict[str, str] = {}
    for sheet in workbook.iter(f"{{{_MAIN_NS}}}sheet"):
        target = targets.get(sheet.get(f"{{{_DOCUMENT_REL_NS}}}id"))
        name = sheet.get("name")
        if name is not None and target is not None:
            parts[name] = target
    return parts


def _coordinate(reference: str) -> tuple[int, int]:
    """``"AB12"`` -> ``(12, 28)``: 1-based row and column of a cell reference."""
    letters = reference.rstrip("0123456789")
    if not letters or not letters.isascii() or not letters.isupper() or len(letters) == len(reference):
        raise ValueError(f"Invalid cell reference {reference!r}.")
    column = 0
    for letter in letters:
        column = column * 26 + ord(letter) - ord("A") + 1
    return int(reference[len(letters) :]), column


def _error_cells(archive: zipfile.ZipFile, part: str) -> dict[int, dict[int, str]]:
    """Row -> {column -> error text} (``#DIV/0!``, ``#N/A``...) for every error cell of one worksheet.

    python-calamine returns error cells as empty strings; the import must see the error text instead, so a
    broken formula is reported, not read as a blank cell.
    """
    with archive.open(part) as source:
        xml = source.read()
    if b't="e"' not in xml and b"t='e'" not in xml:
        return {}
    errors: dict[int, dict[int, str]] = {}
    for _event, element in ElementTree.iterparse(io.BytesIO(xml)):
        if element.tag != f"{{{_MAIN_NS}}}c":
            continue
        reference = element.get("r")
        if element.get("t") == "e" and reference:
            value = element.findtext(f"{{{_MAIN_NS}}}v")
            if value:
                row, column = _coordinate(reference)
                errors.setdefault(row, {})[column] = value
        element.clear()
    return errors


def _cell(value: Any) -> Any:
    """Return a calamine value as the reader's callers expect it.

    Empty cells are ``None``; whole numbers are ``int`` (Excel stores every number as a float); a date
    cell is a ``datetime`` (calamine returns a ``date`` when the time is midnight).
    """
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if type(value) is date:
        return datetime.combine(value, time())
    return value


def _read_sheet(
    workbook: CalamineWorkbook,
    name: str,
    errors: dict[int, dict[int, str]],
    *,
    header_row: int,
    first_data_row: int,
    max_data_rows: int,
) -> RawSheet:
    # skip_empty_area=False keeps the grid anchored at A1: list index i is Excel row i + 1.
    grid = workbook.get_sheet_by_name(name).to_python(skip_empty_area=False)

    def values(number: int, width: int | None = None) -> list[Any]:
        cells = grid[number - 1] if 0 < number <= len(grid) else []
        if width is not None:
            cells = cells[:width]
        row = [_cell(value) for value in cells]
        for column, text in errors.get(number, {}).items():
            if column <= len(row):
                row[column - 1] = text
        return row

    headers = values(header_row)
    while headers and _is_empty(headers[-1]):
        headers.pop()
    width = len(headers)
    rows: list[tuple[int, tuple[Any, ...]]] = []
    truncated = False
    if width:
        for number in range(first_data_row, len(grid) + 1):
            cells = values(number, width)
            if all(_is_empty(value) for value in cells):
                continue
            if len(rows) >= max_data_rows:
                truncated = True
                break
            rows.append((number, tuple(cells) + (None,) * (width - len(cells))))
    return RawSheet(
        name=name,
        headers=tuple(None if _is_empty(h) else str(h).strip() for h in headers),
        rows=tuple(rows),
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
    """Read the named worksheets that exist in the file; cached formula results are read, not formulas.

    Each sheet stops after ``max_data_rows`` non-empty rows and is then marked ``truncated``.
    """
    data = file if isinstance(file, bytes) else file.read()
    _check_archive(data)
    wanted = set(sheet_names)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = _sheet_parts(archive)
            with CalamineWorkbook.from_filelike(io.BytesIO(data)) as workbook:
                names = [
                    sheet.name
                    for sheet in workbook.sheets_metadata
                    if sheet.typ == SheetTypeEnum.WorkSheet and sheet.name in wanted
                ]
                return tuple(
                    _read_sheet(
                        workbook,
                        name,
                        _error_cells(archive, parts[name]) if name in parts else {},
                        header_row=header_row,
                        first_data_row=first_data_row,
                        max_data_rows=max_data_rows,
                    )
                    for name in names
                )
    except (CalamineError, ElementTree.ParseError, KeyError, ValueError, zipfile.BadZipFile) as error:
        raise SpreadsheetUnreadable("The workbook could not be read.") from error


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
