"""``read_workbook`` (python-calamine): cell types, row numbers, limits and unreadable files."""

from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from core.infrastructure.spreadsheets import xlsx

_SHEET = "xl/worksheets/sheet1.xml"


def _template(rows: list[list[object]], headers: list[object] | None = None, title: str = "Equipment") -> Workbook:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = title
    sheet.append(["Title"])
    sheet.append(headers or ["Name", "Count"])
    sheet.append(["hint"])
    for row in rows:
        sheet.append(row)
    return workbook


def _save(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _replace(data: bytes, updates: dict[str, bytes | None]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as original, ZipFile(buffer, "w") as changed:
        for name in original.namelist():
            if name not in updates:
                changed.writestr(name, original.read(name))
        for name, content in updates.items():
            if content is not None:
                changed.writestr(name, content)
    return buffer.getvalue()


def test_cell_values_keep_the_types_the_importer_reads() -> None:
    headers: list[object] = [" Name ", "Count", "Ratio", "Enabled", "Bought", "Seen", "Opens", "Runtime", None]
    workbook = _template(
        [["café & <", 42, 1.5, True, date(2026, 6, 1), datetime(2026, 6, 1, 9, 30), time(8, 15), timedelta(hours=30)]],
        headers=headers,
    )

    (sheet,) = xlsx.read_workbook(_save(workbook), sheet_names=["Equipment"])

    assert sheet.headers == ("Name", "Count", "Ratio", "Enabled", "Bought", "Seen", "Opens", "Runtime")
    ((number, values),) = sheet.rows
    assert number == 4
    assert values == (
        "café & <",
        42,
        1.5,
        True,
        datetime(2026, 6, 1),
        datetime(2026, 6, 1, 9, 30),
        time(8, 15),
        timedelta(hours=30),
    )
    assert tuple(map(type, values)) == (str, int, float, bool, datetime, datetime, time, timedelta)


def test_error_cells_keep_their_text_and_formulas_read_the_cached_result() -> None:
    sheet_xml = b"""<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
      <row r="2"><c r="A2" t="inlineStr"><is><t>Name</t></is></c><c r="B2" t="inlineStr"><is><t>Total</t></is></c>
        <c r="C2" t="inlineStr"><is><t>Price</t></is></c></row>
      <row r="4"><c r="A4" t="inlineStr"><is><t>scope</t></is></c><c r="B4"><f>1+1</f><v>2</v></c>
        <c r="C4" t="e"><f>1/0</f><v>#DIV/0!</v></c><c r="D4" t="e"><v>#N/A</v></c></row>
    </sheetData></worksheet>"""
    data = _replace(_save(_template([])), {_SHEET: sheet_xml})

    (sheet,) = xlsx.read_workbook(data, sheet_names=["Equipment"])

    assert sheet.headers == ("Name", "Total", "Price")
    assert sheet.rows == ((4, ("scope", 2, "#DIV/0!")),)


def test_blank_rows_are_skipped_and_rows_keep_their_excel_numbers() -> None:
    workbook = _template([["one", 1], [None, None], ["   ", None], [None, 3, "beyond the header width"]])

    (sheet,) = xlsx.read_workbook(_save(workbook), sheet_names=["Equipment"])

    assert sheet.rows == ((4, ("one", 1)), (7, (None, 3)))
    assert not sheet.truncated


def test_short_rows_are_padded_to_the_header_width() -> None:
    workbook = _template([["only a name"]], headers=["Name", "Count", "Notes"])

    (sheet,) = xlsx.read_workbook(_save(workbook), sheet_names=["Equipment"])

    assert sheet.rows == ((4, ("only a name", None, None)),)


def test_a_sheet_stops_after_max_data_rows_and_is_marked_truncated() -> None:
    workbook = _template([["a", 1], [None, None], ["b", 2], ["c", 3]])

    (sheet,) = xlsx.read_workbook(_save(workbook), sheet_names=["Equipment"], max_data_rows=2)

    assert sheet.rows == ((4, ("a", 1)), (6, ("b", 2)))
    assert sheet.truncated


def test_a_sheet_without_headers_has_no_rows() -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Equipment"
    sheet["A4"] = "orphan"

    (read,) = xlsx.read_workbook(_save(workbook), sheet_names=["Equipment"])

    assert read == xlsx.RawSheet("Equipment", (), ())


def test_only_requested_worksheets_are_read_in_workbook_order_including_hidden_ones() -> None:
    workbook = _template([["a", 1]])
    hidden = workbook.create_sheet("_Meta")
    hidden.sheet_state = "hidden"
    hidden.append(["Meta"])
    hidden.append(["template_version", "3"])
    workbook.create_sheet("Ignored").append(["x"])
    workbook.create_chartsheet("Chart")

    sheets = xlsx.read_workbook(io.BytesIO(_save(workbook)), sheet_names=["_Meta", "Equipment", "Chart", "Missing"])

    assert [sheet.name for sheet in sheets] == ["Equipment", "_Meta"]
    assert sheets[1].headers == ("template_version", "3")


def test_a_file_that_is_not_a_zip_is_refused() -> None:
    with pytest.raises(xlsx.SpreadsheetUnreadable, match="not an .xlsx workbook"):
        xlsx.read_workbook(b"not a workbook", sheet_names=["Equipment"])


def test_a_zip_that_is_not_an_xlsx_package_is_refused() -> None:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        archive.writestr("content.xml", "<office:document-content/>")

    with pytest.raises(xlsx.SpreadsheetUnreadable, match="could not be read"):
        xlsx.read_workbook(buffer.getvalue(), sheet_names=["Equipment"])


@pytest.mark.parametrize(
    "sheet_xml",
    [
        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>',
        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        b'<row r="4"><c r="A4" t="e"><v>#N/A</v></c></row></sheetData>',
    ],
    ids=["truncated", "truncated-with-error-cell"],
)
def test_a_malformed_worksheet_is_unreadable(sheet_xml: bytes) -> None:
    data = _replace(_save(_template([["a", 1]])), {_SHEET: sheet_xml})

    with pytest.raises(xlsx.SpreadsheetUnreadable, match="could not be read"):
        xlsx.read_workbook(data, sheet_names=["Equipment"])


def test_the_archive_size_limit_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xlsx, "MAX_UNCOMPRESSED_BYTES", 1)

    with pytest.raises(xlsx.SpreadsheetUnreadable, match="too large once unpacked"):
        xlsx.read_workbook(_save(_template([])), sheet_names=["Equipment"])


def test_written_workbooks_read_back_unchanged() -> None:
    layout = xlsx.SheetLayout(
        name="Equipment",
        title="Equipment",
        columns=(xlsx.ColumnLayout("Asset Tag", required=True), xlsx.ColumnLayout("Count")),
        rows=(("PC-001", 2), ("=cmd", None)),
    )

    (sheet,) = xlsx.read_workbook(xlsx.build_workbook([layout]), sheet_names=["Equipment"])

    assert sheet.headers == ("Asset Tag *", "Count")
    assert sheet.rows == ((4, ("PC-001", 2)), (5, ("'=cmd", None)))


@pytest.mark.parametrize(("reference", "expected"), [("A1", (1, 1)), ("Z9", (9, 26)), ("AB12", (12, 28))])
def test_cell_references(reference: str, expected: tuple[int, int]) -> None:
    assert xlsx._coordinate(reference) == expected


@pytest.mark.parametrize("reference", ["12", "A", "a1", "Ä1"])
def test_invalid_cell_references(reference: str) -> None:
    with pytest.raises(ValueError):
        xlsx._coordinate(reference)
