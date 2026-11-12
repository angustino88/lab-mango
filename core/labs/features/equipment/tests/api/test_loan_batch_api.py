"""HTTP contract of loan slips and the read restriction (equipment booking revision 2)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import EquipmentCategory, EquipmentKind, Room
from tests.factories import create_computing_equipment

ROOT = "/api/labs/"
User = get_user_model()


@pytest.fixture
def items(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    kind = EquipmentKind.objects.create(category=category, name="LB API")
    return [
        create_computing_equipment(sku=f"LB-API-{index}", name=f"Scope {index}", kind=kind)
        for index in range(3)
    ]


@pytest.fixture
def coord(db):
    client = APIClient()
    client.force_authenticate(grant_labs_role(User.objects.create_user(username="lb-coord"), "coord"))
    return client


def _body(units, **extra):
    return {
        "equipment_ids": [item.pk for item in units],
        "borrower_name": "Anna Tran (Supplier X)",
        "borrower_contact": "anna@example.com",
        "purpose": "EMC test week",
        "due_at": (timezone.now() + timedelta(days=3)).isoformat(),
        **extra,
    }


@pytest.mark.django_db
def test_lend_list_slip_return_extend(coord, items):
    room = Room.objects.create(sku="LB-API-R", name="Store")
    created = coord.post(
        ROOT + "equipment-loans",
        _body(items, items=[{"equipment_id": items[0].pk, "condition_out": "Scratched"}]),
        format="json",
        HTTP_IDEMPOTENCY_KEY="slip-api-1",
    )
    assert created.status_code == 201, created.data
    slip = created.data["data"]
    assert (
        slip["borrower"] is None
        and slip["borrower_name"] == "Anna Tran (Supplier X)"
        and slip["purpose"] == "EMC test week"
    )
    assert slip["open_count"] == 3 and len(slip["loans"]) == 3
    assert slip["reminders"] == [] and slip["reservations"] == []

    replay = coord.post(ROOT + "equipment-loans", _body(items), format="json", HTTP_IDEMPOTENCY_KEY="slip-api-1")
    assert replay.status_code == 422  # same key, different body (no per-item notes)

    assert coord.get(ROOT + f"equipment-loan-batches/{slip['id']}").data["data"]["id"] == slip["id"]
    lines = coord.get(ROOT + "equipment-loans", {"open": "true", "borrower_name": "anna"}).data["data"]
    assert {line["equipment"]["id"] for line in lines} == {item.pk for item in items}

    later = (timezone.now() + timedelta(days=7)).isoformat()
    extended = coord.post(
        ROOT + "equipment-loans/actions/extend", {"batch_id": slip["id"], "due_at": later}, format="json"
    )
    assert extended.status_code == 200, extended.data
    assert len(extended.data["data"]) == 3

    returned = coord.post(
        ROOT + "equipment-loans/actions/return",
        {"items": [{"equipment_id": items[0].pk, "condition_in": "ok", "room_id": room.pk}]},
        format="json",
    )
    assert returned.status_code == 200, returned.data
    assert returned.data["data"][0]["close_reason"] == "returned"
    assert coord.get(ROOT + f"equipment-loan-batches/{slip['id']}").data["data"]["open_count"] == 2


@pytest.mark.django_db
def test_lend_needs_idempotency_key_and_is_all_or_nothing(coord, items):
    assert coord.post(ROOT + "equipment-loans", _body(items), format="json").status_code == 400
    coord.post(
        ROOT + f"equipment/{items[1].pk}/actions/change-condition", {"condition": "in_maintenance"}, format="json"
    )
    refused = coord.post(ROOT + "equipment-loans", _body(items), format="json", HTTP_IDEMPOTENCY_KEY="slip-api-2")
    assert refused.status_code == 409 and refused.data["error"]["code"] == "equipment_not_available"
    assert [detail["field"] for detail in refused.data["error"]["details"]] == ["equipment_ids[1]"]
    assert coord.get(ROOT + "equipment-loans").data["data"] == []


@pytest.mark.django_db
def test_single_hand_over_accepts_a_borrower_name(coord, items):
    response = coord.post(
        ROOT + f"equipment/{items[0].pk}/actions/hand-over",
        {
            "borrower_name": "Visitor Ben",
            "purpose": "Demo",
            "due_at": (timezone.now() + timedelta(hours=4)).isoformat(),
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["data"]["borrower_name"] == "Visitor Ben" and response.data["data"]["purpose"] == "Demo"
    missing = coord.post(
        ROOT + f"equipment/{items[1].pk}/actions/hand-over",
        {"due_at": (timezone.now() + timedelta(hours=4)).isoformat()},
        format="json",
    )
    assert missing.status_code == 422


@pytest.mark.django_db
def test_engineers_cannot_read_equipment_but_can_read_organisation(items):
    engineer = APIClient()
    engineer.force_authenticate(grant_labs_role(User.objects.create_user(username="lb-engineer"), "user"))
    for path in (
        "equipment",
        f"equipment/{items[0].pk}",
        "equipment/options?q=Scope",
        "equipment-loans",
        "equipment-kinds",
        "equipment/reference-data/kinds",
        "equipment/status-summary",
    ):
        assert engineer.get(ROOT + path).status_code == 403, path
    for path in ("departments", "teams", "equipment/reference-data/departments"):
        assert engineer.get(ROOT + path).status_code == 200, path
