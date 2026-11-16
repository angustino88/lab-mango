"""Update mode (upsert) and the data export: existing asset tags update their records, and an exported file
imports back with nothing to change."""

from __future__ import annotations

import io
from typing import Any

import pytest
from openpyxl import load_workbook

from core.labs.models import Bench, Room, Station
from core.labs.models.resource.equipment.equipment import Equipment
from tests.factories import UserFactory, grant_labs_role

from .conftest import APPLY_URL, CHECK_URL, build_xlsx, upload
from .test_api import full_workbook

pytestmark = pytest.mark.django_db

EXPORT_URL = "/api/labs/workbook-imports/export"


def _post(client, data: bytes, *, mode: str | None = None, apply: bool = False):
    body: dict[str, Any] = {"file": upload(data)}
    if mode is not None:
        body["mode"] = mode
    return client.post(APPLY_URL if apply else CHECK_URL, body, format="multipart")


def _sheets(response) -> dict[str, dict[str, Any]]:
    return {sheet["key"]: sheet for sheet in response.json()["data"]["sheets"]}


def _errors(response) -> list[dict[str, Any]]:
    return [p for p in response.json()["data"]["problems"] if p["severity"]["value"] == "error"]


@pytest.fixture()
def imported(admin_client):
    response = _post(admin_client, build_xlsx(full_workbook()), apply=True)
    assert response.status_code == 200, response.json()
    return admin_client


def test_create_mode_names_the_existing_asset_tag(imported):
    response = _post(imported, build_xlsx(full_workbook()), apply=True)

    assert response.status_code == 422
    details = response.json()["error"]["details"]
    room = next(item for item in details if item["field"].startswith("Rooms["))
    assert room["code"] == "already_exists"
    assert "RM-001" in room["message"] and "upsert" in room["message"]


def test_upsert_of_the_same_rows_reports_them_unchanged(imported):
    response = _post(imported, build_xlsx(full_workbook()), mode="upsert")

    report = response.json()["data"]
    assert report["is_valid"] is True, _errors(response)
    assert report["mode"]["value"] == "upsert"
    sheets = _sheets(response)
    for key in ("rooms", "stations", "station_slots", "benches", "bench_placements"):
        assert (sheets[key]["created"], sheets[key]["updated"], sheets[key]["existing"]) == (0, 0, 1), key
    assert sheets["equipment"]["created"] == 0


def test_upsert_updates_changed_cells_keeps_blank_ones_and_creates_new_tags(imported):
    workbook = full_workbook()
    headers, rows = workbook["Rooms"]
    room = list(rows[0])
    room[headers.index("Name")] = "Radar lab (renovated)"
    room[headers.index("Floor")] = None  # blank keeps the stored floor
    new_room: list[Any] = [None] * len(headers)
    new_room[0], new_room[1] = "RM-002", "Second lab"
    workbook["Rooms"] = (headers, [room, new_room])
    bench_headers, bench_rows = workbook["Benches"]
    bench = list(bench_rows[0])
    bench[bench_headers.index("Name")] = "Radar bench 1 (moved)"
    workbook["Benches"] = (bench_headers, [bench])

    response = _post(imported, build_xlsx(workbook), mode="upsert", apply=True)

    assert response.status_code == 200, response.json()
    sheets = _sheets(response)
    assert (sheets["rooms"]["created"], sheets["rooms"]["updated"]) == (1, 1)
    assert sheets["benches"]["updated"] == 1
    assert response.json()["data"]["summary"]["updated"] >= 2
    stored = Room.objects.get(sku="RM-001")
    assert (stored.name, stored.floor) == ("Radar lab (renovated)", "GF")
    assert Room.objects.filter(sku="RM-002", name="Second lab").exists()
    assert Bench.objects.get(sku="BN-001").name == "Radar bench 1 (moved)"


def test_upsert_changes_lifecycle_and_access_and_keeps_open_downtime_with_a_warning(imported):
    workbook = full_workbook()
    headers, rows = workbook["Rooms"]
    room = list(rows[0])
    room[headers.index("Access")] = "Open"
    workbook["Rooms"] = (headers, [room])
    bench_headers, bench_rows = workbook["Benches"]
    bench = list(bench_rows[0])
    bench[bench_headers.index("Condition")] = "Operational"  # an open downtime is ended in the app
    workbook["Benches"] = (bench_headers, [bench])

    response = _post(imported, build_xlsx(workbook), mode="upsert", apply=True)

    assert response.status_code == 200, response.json()
    assert Room.objects.get(sku="RM-001").access_policy == "open"
    warnings = [p for p in response.json()["data"]["problems"] if p["code"] == "condition_not_changed"]
    assert len(warnings) == 1 and warnings[0]["sheet"] == "Benches"


def test_upsert_never_changes_the_asset_tag(imported):
    # A row is matched by its asset tag, so another tag is another record: it is created, the old one stays.
    workbook = full_workbook()
    headers, rows = workbook["Stations"]
    station = list(rows[0])
    station[0] = "ST-NEW"
    station[headers.index("Room Slot Code")] = "R1C2"
    workbook["Stations"] = (headers, [station])

    response = _post(imported, build_xlsx(workbook), mode="upsert", apply=True)

    assert response.status_code == 200, response.json()
    assert set(Station.objects.values_list("sku", flat=True)) == {"ST-001", "ST-NEW"}


def test_export_round_trips_with_nothing_to_change(imported):
    response = imported.get(EXPORT_URL)

    assert response.status_code == 200
    assert response["Content-Disposition"].startswith('attachment; filename="labmango-data-export-')
    workbook = load_workbook(io.BytesIO(response.content))
    rooms = workbook["Rooms"]
    headers = [cell.value for cell in rooms[2]]
    first = {header.rstrip(" *"): cell.value for header, cell in zip(headers, rooms[4], strict=False) if header}
    assert first["Asset Tag"] == "RM-001"
    assert first["Access"] == "Restricted"
    assert sorted(part.strip() for part in first["Utilities"].split(",")) == ["230V", "ethernet=4"]
    assert workbook["Equipment"].max_row >= 5  # two units from row 4
    assert workbook["Bench Placements"]["A4"].value == "BN-001"

    check = _post(imported, response.content, mode="upsert")

    report = check.json()["data"]
    assert report["is_valid"] is True, _errors(check)
    assert report["summary"]["created"] == 0
    assert report["summary"]["updated"] == 0, [s for s in report["sheets"] if s["updated"]]


def test_export_then_edit_then_upsert_applies_the_edit(imported):
    exported = load_workbook(io.BytesIO(imported.get(EXPORT_URL).content))
    sheet = exported["Equipment"]
    headers = [cell.value.rstrip(" *") if cell.value else None for cell in sheet[2]]
    for row in sheet.iter_rows(min_row=4):
        if row[0].value == "PC-001":
            row[headers.index("Serial Number")].value = "SN1-REPLACED"
    buffer = io.BytesIO()
    exported.save(buffer)

    response = _post(imported, buffer.getvalue(), mode="upsert", apply=True)

    assert response.status_code == 200, response.json()
    assert _sheets(response)["equipment"]["updated"] == 1
    assert Equipment.objects.get(sku="PC-001").serial_number == "SN1-REPLACED"


def test_export_is_for_labs_administrators_only(admin_client):
    user: Any = UserFactory()
    coordinator = grant_labs_role(user, "coord")
    admin_client.force_authenticate(user=coordinator)

    assert admin_client.get(EXPORT_URL).status_code == 403


def test_unknown_mode_is_a_field_error(admin_client):
    response = _post(admin_client, build_xlsx(full_workbook()), mode="replace")

    assert response.status_code == 422
    assert any(item["field"] == "mode" for item in response.json()["error"]["details"])
