"""Tests for workbook import live progress polling and room-slot utility inheritance."""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from core.labs.models import Room, RoomSlot, Station
from tests.factories import UserFactory, grant_labs_role

from .conftest import APPLY_URL, CHECK_URL, build_xlsx, upload

PROGRESS_URL = "/api/labs/workbook-imports/progress/{progress_key}"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _minimal_room_and_station_workbook(
    *, room_utilities: str = "230V=20, ethernet=48", station_utilities: str = "230V=8, ethernet=16"
):
    return build_xlsx(
        {
            "Rooms": (
                ["Asset Tag", "Name", "Grid Rows", "Grid Columns", "Utilities"],
                [["RM-PROG-1", "Progress Room", 2, 2, room_utilities]],
            ),
            "Stations": (
                ["Asset Tag", "Name", "Room Asset Tag", "Room Slot Code", "Utilities"],
                [["ST-PROG-1", "Progress Station", "RM-PROG-1", "R1C1", station_utilities]],
            ),
        }
    )


def test_check_and_apply_record_owner_scoped_progress(admin_client, db):
    progress_key = str(uuid.uuid4())
    data = _minimal_room_and_station_workbook()

    check_res = admin_client.post(
        CHECK_URL,
        {"file": upload(data), "mode": "create", "progress_key": progress_key},
        format="multipart",
    )
    assert check_res.status_code == 200, check_res.json()
    assert check_res.json()["data"]["is_valid"] is True

    progress_res = admin_client.get(PROGRESS_URL.format(progress_key=progress_key))
    assert progress_res.status_code == 200, progress_res.json()
    payload = progress_res.json()["data"]
    assert payload["progress_key"] == progress_key
    assert payload["status"]["value"] == "completed"
    assert payload["phase"]["value"] == "completed"
    assert payload["percent"] == 100
    assert payload["total_rows"] == 2
    assert payload["processed_rows"] == 2
    assert payload["total_sheets"] == 2
    assert payload["completed_sheets"] == 2

    # Another Labs admin cannot inspect this admin's progress key (object-scoped, deny by default -> 404).
    other_admin = grant_labs_role(cast(Any, UserFactory(username="otheradmin")), "admin")
    other_client = APIClient()
    other_client.force_authenticate(other_admin)
    assert other_client.get(PROGRESS_URL.format(progress_key=progress_key)).status_code == 404

    # Non-admin users are denied with 403.
    coordinator = grant_labs_role(cast(Any, UserFactory(username="labcoord")), "coord")
    coord_client = APIClient()
    coord_client.force_authenticate(coordinator)
    assert coord_client.get(PROGRESS_URL.format(progress_key=progress_key)).status_code == 403

    # Unknown progress key returns 404.
    assert admin_client.get(PROGRESS_URL.format(progress_key=uuid.uuid4())).status_code == 404


def test_apply_records_failed_progress_when_rejected(admin_client, db):
    progress_key = str(uuid.uuid4())
    # Room does NOT support 400V, so station validation fails.
    data = _minimal_room_and_station_workbook(room_utilities="230V=20", station_utilities="400V=4")

    apply_res = admin_client.post(
        APPLY_URL,
        {"file": upload(data), "mode": "create", "progress_key": progress_key},
        format="multipart",
    )
    assert apply_res.status_code == 422

    progress_res = admin_client.get(PROGRESS_URL.format(progress_key=progress_key))
    assert progress_res.status_code == 200, progress_res.json()
    payload = progress_res.json()["data"]
    assert payload["status"]["value"] == "failed"
    assert payload["phase"]["value"] == "failed"
    assert payload["percent"] == 100


def test_station_on_generated_room_slot_inherits_room_utilities_unless_slot_overrides(admin_client, db):
    # 1. Auto-generated RoomSlot (empty slot.utilities) succeeds when Room supports the station's utilities.
    ok_res = admin_client.post(
        APPLY_URL,
        {"file": upload(_minimal_room_and_station_workbook()), "mode": "create"},
        format="multipart",
    )
    assert ok_res.status_code == 200, ok_res.json()
    room = Room.objects.get(sku="RM-PROG-1")
    station = Station.objects.get(sku="ST-PROG-1")
    assert station.slot is not None and station.slot.slot_code == "R1C1"
    assert station.utilities == {"230V": 8, "ethernet": 16}

    # 2. When a RoomSlot explicitly restricts slot.utilities, station validation still enforces it.
    restricted_slot = RoomSlot.objects.get(room=room, slot_code="R1C2")
    restricted_slot.utilities = {"ethernet": 4}
    restricted_slot.save()

    blocked_data = build_xlsx(
        {
            "Stations": (
                ["Asset Tag", "Name", "Room Asset Tag", "Room Slot Code", "Utilities"],
                [["ST-PROG-2", "Blocked Station", "RM-PROG-1", "R1C2", "230V=8, ethernet=4"]],
            ),
        }
    )
    check_res = admin_client.post(
        CHECK_URL,
        {"file": upload(blocked_data), "mode": "create"},
        format="multipart",
    )
    assert check_res.status_code == 200
    body = check_res.json()["data"]
    assert body["is_valid"] is False
    assert any("230V" in p["message"] for p in body["problems"])
