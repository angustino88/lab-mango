import io
from datetime import datetime
from xml.etree.ElementTree import ParseError
from zipfile import ZipFile

import pytest
from openpyxl import Workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from core.infrastructure.spreadsheets import xlsx


def _save(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _update_archive(data: bytes, updates: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as original, ZipFile(buffer, "w") as changed:
        for name in original.namelist():
            if name not in updates:
                changed.writestr(name, original.read(name))
        for name, content in updates.items():
            changed.writestr(name, content)
    return buffer.getvalue()


def test_native_preserves_cell_types_and_row_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Equipment"
    workbook.create_sheet("Ignored")
    sheet_xml = """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <dimension ref="A1:G8"/><sheetData>
        <row r="2">
          <c r="A2" t="inlineStr"><is><t xml:space="preserve"> Name </t></is></c>
          <c r="B2" t="inlineStr"><is><t>Count</t></is></c>
          <c r="C2" t="inlineStr"><is><t>Enabled</t></is></c>
          <c r="D2" t="inlineStr"><is><t>Error</t></is></c>
          <c r="E2" t="inlineStr"><is><t>Cached</t></is></c>
          <c r="G2" t="inlineStr"><is><t>Float</t></is></c>
        </row>
        <row r="4">
          <c r="A4" t="inlineStr"><is><t>café &amp; &lt;</t></is></c>
          <c r="B4"><v>9007199254740993</v></c>
          <c r="C4" t="b"><v>1</v></c>
          <c r="D4" t="e"><v>#DIV/0!</v></c>
          <c r="E4"><f>1+1</f><v>2</v></c>
          <c r="F4" t="inlineStr"><is><t>extra</t></is></c>
          <c r="G4"><v>1.0</v></c>
        </row>
        <row r="6"><c r="D6" t="inlineStr"><is><t xml:space="preserve">  </t></is></c></row>
        <row r="8"><c r="A8" t="inlineStr"><is><t>one more row</t></is></c></row>
      </sheetData>
    </worksheet>"""
    data = _update_archive(_save(workbook), {"xl/worksheets/sheet1.xml": sheet_xml.encode()})

    monkeypatch.delenv("XLSX_READER", raising=False)
    expected = xlsx.read_workbook(data, sheet_names=["Equipment"], max_data_rows=1)
    monkeypatch.setenv("XLSX_READER", "native")

    def unexpected_fallback(*args: object, **kwargs: object) -> None:
        pytest.fail("This workbook should be decoded by the Rust extension.")

    monkeypatch.setattr(ReadOnlyWorksheet, "iter_rows", unexpected_fallback)
    actual = xlsx.read_workbook(io.BytesIO(data), sheet_names=["Equipment"], max_data_rows=1)

    assert actual == expected
    assert actual[0].headers == ("Name", "Count", "Enabled", "Error", "Cached", None, "Float")
    assert actual[0].truncated
    ((number, values),) = actual[0].rows
    assert number == 4
    assert values == ("café & <", 9007199254740993, True, "#DIV/0!", 2, "extra", 1.0)
    assert tuple(map(type, values)) == (str, int, bool, str, int, str, float)


def test_native_falls_back_for_date_styles(monkeypatch: pytest.MonkeyPatch) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Title"])
    sheet.append(["Date"])
    sheet.append(["Hint"])
    sheet.append([datetime(2026, 6, 1, 9, 30)])
    data = _save(workbook)
    monkeypatch.setenv("XLSX_READER", "native")
    assert xlsx.read_workbook(data, sheet_names=["Sheet"]) == (
        xlsx.RawSheet("Sheet", ("Date",), ((4, (datetime(2026, 6, 1, 9, 30),)),)),
    )


def test_native_falls_back_for_non_utf8_declarations(monkeypatch: pytest.MonkeyPatch) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Title"])
    sheet.append(["Name"])
    sheet.append(["Hint"])
    sheet.append(["cafX"])
    data = _save(workbook)
    sheet_path = "xl/worksheets/sheet1.xml"
    with ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read(sheet_path).replace(b"cafX", b"caf\xc3\xa9")
    xml = b'<?xml version="1.0" encoding="ISO-8859-1"?>' + xml
    data = _update_archive(data, {sheet_path: xml})

    monkeypatch.setenv("XLSX_READER", "native")
    assert xlsx.read_workbook(data, sheet_names=["Sheet"])[0].rows == ((4, ("cafÃ©",)),)


def test_native_mode_preserves_archive_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _save(Workbook())
    monkeypatch.setenv("XLSX_READER", "native")
    monkeypatch.setattr(xlsx, "MAX_UNCOMPRESSED_BYTES", 1)

    with pytest.raises(xlsx.SpreadsheetUnreadable, match="too large once unpacked"):
        xlsx.read_workbook(data, sheet_names=["Sheet"])


def test_native_delegates_a_malformed_worksheet_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Title"])
    sheet.append(["Name"])
    sheet.append(["Hint"])
    sheet.append(["device"])
    data = _save(workbook)
    sheet_path = "xl/worksheets/sheet1.xml"
    with ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read(sheet_path).removesuffix(b"</worksheet>")
    data = _update_archive(data, {sheet_path: xml})

    monkeypatch.setenv("XLSX_READER", "native")
    with pytest.raises(ParseError):
        xlsx.read_workbook(data, sheet_names=["Sheet"])
