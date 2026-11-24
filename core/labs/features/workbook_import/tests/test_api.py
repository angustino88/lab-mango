"""Workbook import over HTTP: check, apply, all-or-nothing, the v1 template, access and the template."""

from __future__ import annotations

import io
from typing import Any, cast

import pytest
from openpyxl import load_workbook

from core.labs.models import (
    Bench,
    Building,
    EquipmentKind,
    EquipmentManufacturer,
    EquipmentProductModel,
    Room,
    RoomSlot,
    Station,
    StationSlot,
)
from core.labs.models.resource.base.downtime import ResourceDowntime
from core.labs.models.resource.base.resource import Department, Group
from core.labs.models.resource.equipment.assignment import EquipmentAssignment, EquipmentPlacement
from core.labs.models.resource.equipment.computing import ComputingProfile
from core.labs.models.resource.equipment.equipment import Equipment
from tests.factories import UserFactory, grant_labs_role

from .conftest import TEMPLATE_URL, build_xlsx, upload

pytestmark = pytest.mark.django_db


def full_workbook() -> dict[str, Any]:
    return {
        "Departments": (["Name", "Description", "Active"], [["MS/EEC-XC", "", "Yes"]]),
        "Groups": (["Name *", "Department", "Description", "Active"], [["MS/EEC3-XC", "MS/EEC-XC", "", "Yes"]]),
        "Countries": (["Code *", "Name *"], [["VN", "Vietnam"]]),
        "Cities": (["City *", "Country"], [["Ho Chi Minh", "Vietnam"]]),
        "Buildings": (["Building *", "City", "Address"], [["ETOWN-02", "Ho Chi Minh", ""]]),
        "Station Types": (["Name *"], [["Table"]]),
        "Bench Groups": (["Name *", "Description", "Active"], [["Radar", "Radar benches", "Yes"]]),
        "Screen Sizes": (["Label *", "Diagonal (inch)"], [['24"', 24]]),
        "Resolutions": (["Label *", "Width (px)", "Height (px)"], [["FHD", 1920, 1080]]),
        "Lookups": (
            ["Interfaces", "Materials", "Network Protocols", "Customers", "Characteristics", "Technical Users"],
            [["HDMI", None, None, None, None, "lc92kor"], ["DisplayPort", None, None, None, None, None]],
        ),
        "Equipment Kinds": (
            ["Category *", "Name *", "Active"],
            [["Computing", "Desktop", "Yes"], ["Display", "Monitor", "Yes"]],
        ),
        "Equipment Types": (
            ["Category", "Kind *", "Name *", "Active"],
            [["Computing", "Desktop", "Performance Desktop", "Yes"]],
        ),
        "Manufacturers": (
            ["Name *", "Category 1", "Category 2", "Category 3", "Active"],
            [["HP", "Computing", "Display", None, "Yes"]],
        ),
        "Product Models": (
            ["Manufacturer *", "Kind", "Equipment Type *", "Model Name *", "Active"],
            [["HP", "Desktop", "Performance Desktop", "Z2 G5", "Yes"]],
        ),
        "Rooms": (
            [
                "Asset Tag *",
                "Name",
                "Department",
                "Group",
                "Country",
                "City",
                "Building",
                "Floor",
                "Grid Rows",
                "Grid Columns",
                "Utilities",
                "Lifecycle",
                "Access",
                "Condition",
            ],
            [
                [
                    "RM-001",
                    "Radar lab",
                    "MS/EEC-XC",
                    "MS/EEC3-XC",
                    "Vietnam",
                    "Ho Chi Minh",
                    "ETOWN-02",
                    "GF",
                    1,
                    2,
                    "ethernet=4, 230V",
                    None,
                    "Restricted",
                    None,
                ]
            ],
        ),
        "Stations": (
            [
                "Asset Tag *",
                "Name",
                "Station Type",
                "Room Asset Tag",
                "Room Slot Code",
                "Bench Capacity",
                "Power Capacity (W)",
            ],
            [["ST-001", "Station 1", "Table", "RM-001", "R1C1", 2, 3000]],
        ),
        "Station Slots": (
            ["Station Asset Tag *", "Position No. *", "Slot Code *", "Label"],
            [["ST-001", 0, "top", "Top shelf"]],
        ),
        "Benches": (
            [
                "Asset Tag *",
                "Name",
                "Group",
                "Owner ID",
                "Bench Group",
                "Station Asset Tag",
                "Station Slot Code",
                "Lifecycle",
                "Condition",
                "Commissioning Date",
            ],
            [
                [
                    "BN-001",
                    "Radar bench 1",
                    "MS/EEC3-XC",
                    "labadmin",
                    "Radar",
                    "ST-001",
                    "TOP",
                    "In service",
                    "In maintenance",
                    "2026-01-15",
                ]
            ],
        ),
        "Equipment": (
            [
                "Asset Tag *",
                "Name",
                "Category *",
                "Kind *",
                "Type",
                "Manufacturer",
                "Product Model",
                "Serial Number",
                "Department",
                "Group",
                "Owner ID",
                "Lifecycle",
                "Condition",
                "Storage Room",
                "Replacement Date",
                "Calibration Required",
            ],
            [
                [
                    "PC-001",
                    "Desktop 1",
                    "Computing",
                    "Desktop",
                    "Performance Desktop",
                    "HP",
                    "Z2 G5",
                    "SN1",
                    "MS/EEC-XC",
                    "MS/EEC3-XC",
                    "labadmin",
                    "In service",
                    None,
                    None,
                    "2026-Q2",
                    None,
                ],
                [
                    "MON-001",
                    "Monitor 1",
                    "Display",
                    "Monitor",
                    None,
                    "HP",
                    None,
                    "SN2",
                    None,
                    None,
                    None,
                    None,
                    "Out of service",
                    "RM-001",
                    None,
                    None,
                ],
            ],
        ),
        "Computing": (
            ["Asset Tag *", "Hostname", "MAC Address", "Technical User"],
            [["PC-001", "pc-001.lab", "AA:BB:CC:DD:EE:01", "lc92kor"]],
        ),
        "Display": (
            ["Asset Tag *", "Screen Size", "Resolution", "Interface 1", "Interface 2"],
            [["MON-001", '24"', "FHD", "HDMI", "DisplayPort"]],
        ),
        "Bench Placements": (
            ["Bench Asset Tag *", "Equipment Asset Tag *", "Role", "Position No."],
            [["BN-001", "PC-001", "host", 1]],
        ),
    }


def _problems(response, severity="error"):
    return [p for p in response.json()["data"]["problems"] if p["severity"]["value"] == severity]


def test_check_reports_every_sheet_and_saves_nothing(post_workbook):
    response = post_workbook(full_workbook())

    assert response.status_code == 200, response.json()
    report = response.json()["data"]
    assert report["is_dry_run"] is True
    assert report["is_valid"] is True, _problems(response)
    sheets = {sheet["key"]: sheet for sheet in report["sheets"]}
    assert sheets["rooms"]["created"] == 1
    assert sheets["equipment"]["created"] == 2
    assert sheets["computing"]["created"] == 1
    assert sheets["bench_placements"]["created"] == 1
    assert report["summary"]["error_count"] == 0
    assert not Room.objects.exists()
    assert not Department.objects.filter(name="MS/EEC-XC").exists()
    assert not EquipmentManufacturer.objects.filter(name="HP").exists()


def test_apply_creates_everything_through_the_owning_commands(post_workbook):
    response = post_workbook(full_workbook(), apply=True)

    assert response.status_code == 200, response.json()
    assert response.json()["data"]["is_valid"] is True
    group = Group.objects.get(name="MS/EEC3-XC")
    assert group.department is not None and group.department.name == "MS/EEC-XC"
    room = Room.objects.get(sku="RM-001")
    assert room.building == Building.objects.get(name="ETOWN-02")
    assert room.access_policy == "restricted"
    assert room.utilities == {"ethernet": 4, "230V": True}
    assert set(RoomSlot.objects.filter(room=room).values_list("slot_code", flat=True)) == {"R1C1", "R1C2"}
    station = Station.objects.get(sku="ST-001")
    assert station.room == room and station.slot.slot_code == "R1C1"
    slot = StationSlot.objects.get(station=station)
    bench = Bench.objects.get(sku="BN-001")
    assert bench.station_slot == slot
    assert bench.department == group.department
    assert bench.owner.username == "labadmin"
    assert ResourceDowntime.objects.for_resource(bench).filter(condition="in_maintenance").exists()
    pc = Equipment.objects.get(sku="PC-001")
    assert pc.product_model == EquipmentProductModel.objects.get(name="Z2 G5")
    assert pc.replacement_date.isoformat() == "2026-04-01"
    assert pc.mac_address == "AA:BB:CC:DD:EE:01"
    profile = ComputingProfile.objects.get(equipment=pc)
    assert profile.hostname == "pc-001.lab"
    assert profile.technical_user is not None and profile.technical_user.username == "lc92kor"
    assert EquipmentAssignment.objects.get(equipment=pc, unassigned_at__isnull=True).bench == bench
    monitor = Equipment.objects.get(sku="MON-001")
    assert monitor.size.size == '24"'
    assert set(monitor.interfaces.values_list("name", flat=True)) == {"HDMI", "DisplayPort"}
    assert ResourceDowntime.objects.for_resource(monitor).filter(condition="out_of_service").exists()
    assert EquipmentPlacement.objects.get(equipment=monitor, unassigned_at__isnull=True).room == room


def test_existing_references_are_matched_not_duplicated(post_workbook):
    assert post_workbook(full_workbook(), apply=True).status_code == 200
    second = {
        key: value
        for key, value in full_workbook().items()
        if key
        not in {
            "Rooms",
            "Stations",
            "Station Slots",
            "Benches",
            "Equipment",
            "Computing",
            "Display",
            "Bench Placements",
        }
    }

    response = post_workbook(second, apply=True)

    assert response.status_code == 200, response.json()
    sheets = {sheet["key"]: sheet for sheet in response.json()["data"]["sheets"]}
    assert sheets["manufacturers"]["existing"] == 1 and sheets["manufacturers"]["created"] == 0
    assert EquipmentKind.objects.filter(name="Desktop").count() == 1


def test_apply_with_any_error_saves_nothing_and_lists_every_problem(post_workbook):
    sheets = full_workbook()
    sheets["Benches"][1].append(["BN-002", "Second", "NO-SUCH-GROUP", None, None, None, None, None, None, None])
    sheets["Equipment"][1].append(["PC-001", "Duplicate", "Computing", "Desktop"] + [None] * 12)

    response = post_workbook(sheets, apply=True)

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_failed"
    fields = {detail["field"] for detail in body["details"]}
    assert "Benches[5].Group" in fields
    assert "Equipment[6].Asset Tag" in fields
    assert not Room.objects.exists()
    assert not Department.objects.filter(name="MS/EEC-XC").exists()


def test_create_only_refuses_an_existing_asset_tag(post_workbook):
    assert post_workbook(full_workbook(), apply=True).status_code == 200

    response = post_workbook({"Rooms": full_workbook()["Rooms"]})

    assert response.status_code == 200
    errors = _problems(response)
    assert errors and errors[0]["sheet"] == "Rooms" and errors[0]["row"] == 4


def test_retired_status_columns_are_ignored_with_warnings(post_workbook):
    sheets = {
        "Rooms": (
            ["Asset Tag (SKU) *", "Name", "Status", "Data Check"],
            [["RM-V1", "Old room", "Maintenance", "OK"], ["RM-V2", "Reserved room", "Reserved", "OK"]],
        ),
        "Equipment Kinds": (["Category *", "Name *", "Active"], [["Power", "PSU", "Yes"]]),
        "Equipment": (
            ["Asset Tag (SKU) *", "Name", "Category *", "Kind *", "Status", "Purchase Price"],
            [
                ["PSU-1", "Supply", "Power", "PSU", "Broken", 100],
            ],
        ),
        "Power": (
            ["Asset Tag *", "Name", "Manufacturer", "Product Model", "Channels", "Power Rating (W)"],
            [["PSU-1", "=formula", None, None, 3, 300]],
        ),
        "Licenses": (["Asset Tag (SKU) *"], [["LIC-1"]]),
        "Summary": (["x"], [["y"]]),
    }

    response = post_workbook(sheets, apply=True)

    assert response.status_code == 200, response.json()
    warnings = {(p["sheet"], p["code"]) for p in _problems(response, "warning")}
    assert ("Licenses", "sheet_not_imported") in warnings
    assert ("Rooms", "column_not_imported") in warnings
    assert ("Equipment", "column_not_imported") in warnings
    assert ("Power", "column_not_imported") not in warnings  # v1 auto columns (Name ...) are skipped silently
    room = Room.objects.get(sku="RM-V1")
    assert not ResourceDowntime.objects.for_resource(room).exists()
    psu = Equipment.objects.get(sku="PSU-1")
    assert psu.channels == 3 and psu.power_rating == 300
    assert not ResourceDowntime.objects.for_resource(psu).exists()


def test_only_labs_administrators_can_import(api_client, categories):
    coordinator = grant_labs_role(cast(Any, UserFactory(username="coord1")), "coord")
    api_client.force_authenticate(user=coordinator)

    response = api_client.post(
        "/api/labs/workbook-imports/actions/check", {"file": upload(build_xlsx({}))}, format="multipart"
    )

    assert response.status_code == 403


def test_a_file_that_is_not_a_workbook_is_refused(admin_client):
    response = admin_client.post(
        "/api/labs/workbook-imports/actions/check", {"file": upload(b"not a zip")}, format="multipart"
    )

    assert response.status_code == 415


def test_template_lists_current_references_and_imports_cleanly(admin_client, post_workbook):
    post_workbook(full_workbook(), apply=True)

    response = admin_client.get(TEMPLATE_URL)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/vnd.openxmlformats")
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames[0] == "README"
    assert workbook["Lists"].sheet_state == "hidden"
    manufacturers = workbook["Manufacturers"]
    assert manufacturers["A2"].value == "Name *"
    assert manufacturers["A4"].value == "HP"
    assert workbook["Equipment Categories"]["C4"].value is not None
    check = admin_client.post(
        "/api/labs/workbook-imports/actions/check", {"file": upload(response.content)}, format="multipart"
    )
    report = check.json()["data"]
    assert report["is_valid"] is True, report["problems"]
    assert report["template_version"] == "2.0"
    assert report["summary"]["created"] == 0
    assert report["summary"]["existing"] > 0
