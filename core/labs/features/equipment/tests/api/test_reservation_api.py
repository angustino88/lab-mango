"""HTTP contract of equipment reservations (booking revision 2, phase 2)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import EquipmentCategory, EquipmentKind
from tests.factories import create_computing_equipment

ROOT = "/api/labs/"
User = get_user_model()


@pytest.fixture
def items(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    kind = EquipmentKind.objects.create(category=category, name="RS API")
    return [
        create_computing_equipment(sku=f"RS-API-{index}", name=f"Probe {index}", kind=kind)
        for index in range(3)
    ]


@pytest.fixture
def coord(db):
    client = APIClient()
    client.force_authenticate(grant_labs_role(User.objects.create_user(username="rs-coord"), "coord"))
    return client


def _window(start_hours=24, length_hours=48):
    start = timezone.now() + timedelta(hours=start_hours)
    return start.isoformat(), (start + timedelta(hours=length_hours)).isoformat()


@pytest.mark.django_db
def test_reserve_list_change_hand_over(coord, items):
    starts_at, ends_at = _window(start_hours=0.01)
    body = {
        "equipment_ids": [items[0].pk, items[1].pk],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "borrower_name": "Anna",
        "purpose": "Field test",
    }
    assert (
        coord.post(ROOT + "equipment-reservations", body, format="json").status_code == 400
    )  # Idempotency-Key required
    created = coord.post(ROOT + "equipment-reservations", body, format="json", HTTP_IDEMPOTENCY_KEY="rs-1")
    assert created.status_code == 201, created.data
    slip = created.data["data"]
    assert len(slip["reservations"]) == 2 and slip["loans"] == []

    lines = coord.get(ROOT + "equipment-reservations", {"borrower_name": "anna"}).data["data"]
    assert {line["equipment"]["id"] for line in lines} == {items[0].pk, items[1].pk}
    detail = coord.get(ROOT + f"equipment/{items[0].pk}").data["data"]
    assert [row["batch"]["id"] for row in detail["reservations"]] == [slip["id"]]

    changed = coord.patch(
        ROOT + f"equipment-reservations/{slip['id']}", {"add_equipment_ids": [items[2].pk]}, format="json"
    )
    assert changed.status_code == 200, changed.data
    assert len([line for line in changed.data["data"]["reservations"] if line["status"] == "reserved"]) == 3

    handed = coord.post(
        ROOT + f"equipment-reservations/{slip['id']}/actions/hand-over",
        {"equipment_ids": [items[0].pk]},
        format="json",
    )
    assert handed.status_code == 200, handed.data
    assert len(handed.data["data"]["loans"]) == 1
    assert coord.get(ROOT + f"equipment/{items[0].pk}").data["data"]["display_status"]["value"] == "borrowed"


@pytest.mark.django_db
def test_conflict_and_cancel(coord, items):
    starts_at, ends_at = _window()
    body = {"equipment_ids": [items[0].pk], "starts_at": starts_at, "ends_at": ends_at, "borrower_name": "Anna"}
    slip = coord.post(ROOT + "equipment-reservations", body, format="json", HTTP_IDEMPOTENCY_KEY="rs-2").data["data"]
    clash = coord.post(
        ROOT + "equipment-reservations", {**body, "borrower_name": "Ben"}, format="json", HTTP_IDEMPOTENCY_KEY="rs-3"
    )
    assert clash.status_code == 409 and clash.data["error"]["code"] == "booking_conflict"
    assert (
        coord.post(ROOT + f"equipment-reservations/{slip['id']}/actions/cancel", {}, format="json").status_code == 422
    )
    cancelled = coord.post(
        ROOT + f"equipment-reservations/{slip['id']}/actions/cancel", {"reason": "Not needed"}, format="json"
    )
    assert cancelled.status_code == 200 and cancelled.data["data"]["reservations"][0]["status"] == "cancelled"
    assert coord.get(ROOT + "equipment-reservations").data["data"] == []


@pytest.mark.django_db
def test_engineers_cannot_see_reservations(items):
    engineer = APIClient()
    engineer.force_authenticate(grant_labs_role(User.objects.create_user(username="rs-engineer"), "user"))
    assert engineer.get(ROOT + "equipment-reservations").status_code == 403
