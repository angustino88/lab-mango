"""
Excel export utilities.

Provides helpers to build and stream .xlsx files from Django querysets or
pre-serialised data dicts. Uses openpyxl.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


def return_data_row(data: dict[str, Any], extract_fields: list[str]) -> list[Any]:
    """
    Extract an ordered list of cell values from a serialised data dict.

    Supports:
    - Plain field names: ``"sku"``
    - Nested lookups: ``"computer__sku"``  (split on ``__``)
    - Special casing: ``"created"`` → formatted as ``YYYY-MM-DD HH:MM:SS``
    """
    row: list[Any] = []
    for field in extract_fields:
        if field == "created":
            raw = data.get("created")
            if raw:
                try:
                    dt = datetime.fromisoformat(str(raw))
                    row.append(dt.strftime("%Y-%m-%d %H:%M:%S"))
                except (ValueError, TypeError):
                    row.append(raw)
            else:
                row.append("")
        elif "__" in field:
            keys = field.split("__")
            value: Any = data
            for key in keys:
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(key)
            row.append(value)
        else:
            row.append(data.get(field))
    return row


def export_excel_file(sheets: dict[str, Any], data: dict[str, Any]) -> HttpResponse:
    """
    Build a multi-sheet .xlsx file and return it as an HttpResponse attachment.

    Args:
        sheets: Mapping of equipment_type → {sheet: str, cols: [{title, field}]}
        data:   Mapping of equipment_type → {data: [serialised_row_dict, ...]}

    Returns:
        HttpResponse with content-type ``application/vnd.openxmlformats...``
    """
    # Precompute field lists per device type
    extract_fields: dict[str, list[str]] = {
        equipment_type: [c.get("field", "") for c in config.get("cols", [])]
        for equipment_type, config in sheets.items()
    }

    wb = Workbook()
    # Remove the default empty sheet
    if wb.active:
        wb.remove(wb.active)

    # Styles
    thin_side = Side(style="thin")
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    header_font = Font(bold=True, size=12, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell_align = Alignment(horizontal="left", vertical="center")

    for equipment_type, config in sheets.items():
        ws = wb.create_sheet(title=config["sheet"])
        columns_info: list[dict[str, str]] = config.get("cols", [])
        headers = [c["title"] for c in columns_info]

        ws.append(headers)
        for col_num, _ in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        device_rows: list[dict[str, Any]] = data.get(equipment_type, {}).get("data", [])
        fields = extract_fields[equipment_type]
        for row_num, log in enumerate(device_rows, start=2):
            row_values = return_data_row(log, fields)
            ws.append(row_values)
            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=row_num, column=col_num)
                cell.border = thin_border
                cell.alignment = cell_align

        # Auto-size columns (cap at 50)
        for col_num, column_cells in enumerate(ws.columns, 1):
            max_length = max(
                (len(str(cell.value)) for cell in column_cells if cell.value),
                default=0,
            )
            ws.column_dimensions[get_column_letter(col_num)].width = min(max_length + 2, 50)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = "attachment; filename=export.xlsx"
    wb.save(response)
    return response
