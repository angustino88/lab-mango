"""Query budget of a Check: the queries per equipment row are a constant (query-performance section 2)."""

from __future__ import annotations

from typing import Any

from django.db import connection
from django.test.utils import CaptureQueriesContext

from .conftest import CHECK_URL, build_xlsx, upload
from .test_api import full_workbook

# One desktop with a Computing details row (profile, .rdp file, activity) and one monitor with a Display
# details row, a condition and a storage room: the two heaviest create paths. 86 before the import
# performance work (redundant validation queries and per-unit follow-up commands), 25 after.
QUERIES_PER_UNIT_PAIR = 25


def _workbook(pairs: int) -> dict[str, Any]:
    workbook = full_workbook()
    headers, (desktop, monitor) = workbook["Equipment"]
    computing_headers, computing_rows = workbook["Computing"]
    display_headers, display_rows = workbook["Display"]
    equipment = [list(desktop), list(monitor)]
    computing, display = list(computing_rows), list(display_rows)
    for index in range(pairs):
        pc, mon = f"BUDGET-PC-{index:03d}", f"BUDGET-MON-{index:03d}"
        equipment.append([pc, f"Desktop {index}", *desktop[2:7], f"SN-P{index}", *desktop[8:]])
        equipment.append([mon, f"Monitor {index}", *monitor[2:7], f"SN-M{index}", *monitor[8:]])
        computing.append([pc, f"budget-pc-{index:03d}.lab", f"AA:BB:CC:DD:EF:{index:02X}", "lc92kor"])
        display.append([mon, '24"', "FHD", "HDMI", "DisplayPort"])
    workbook["Equipment"] = (headers, equipment)
    workbook["Computing"] = (computing_headers, computing)
    workbook["Display"] = (display_headers, display)
    return workbook


def _check_queries(client, pairs: int) -> int:
    data = build_xlsx(_workbook(pairs))
    with CaptureQueriesContext(connection) as queries:
        response = client.post(CHECK_URL, {"file": upload(data)}, format="multipart")
    assert response.status_code == 200, response.json()
    assert response.json()["data"]["is_valid"] is True, response.json()["data"]["problems"]
    return len(queries)


def test_check_queries_grow_by_a_constant_per_equipment_row(admin_client):
    _check_queries(admin_client, 1)  # warm the per-process caches
    small = _check_queries(admin_client, 2)
    large = _check_queries(admin_client, 6)

    assert large - small == 4 * QUERIES_PER_UNIT_PAIR
