"""HTTP contract of equipment loans (redesign step 3)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import EquipmentCategory, EquipmentKind, EquipmentLoan, Room
from tests.factories import create_computing_equipment

ROOT = "/api/labs/equipment"
User = get_user_model()


@pytest.fixture
def unit(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    return create_computing_equipment(
        sku="LN-API-1", name="Loan API unit", kind=EquipmentKind.objects.create(category=category, name="LN API")
    )


@pytest.fixture
def client(db):
    result = APIClient()
    result.force_authenticate(grant_labs_role(User.objects.create_user(username="ln-coord"), "coord"))
    return result


@pytest.fixture
def borrower(db):
    return User.objects.create_user(username="ln-api-borrower", display_name="Ada")


def _due(hours=24):
    return (timezone.now() + timedelta(hours=hours)).isoformat()


@pytest.mark.django_db
def test_hand_over_get_extend_return(client, unit, borrower):
    room = Room.objects.create(sku="LN-API-R", name="Store")
    opened = client.post(
        f"{ROOT}/{unit.pk}/actions/hand-over", {"borrower_id": borrower.pk, "due_at": _due()}, format="json"
    )
    assert opened.status_code == 200, opened.data
    assert opened.data["data"]["borrower"] == {"id": borrower.pk, "name": "Ada"}
    assert opened.data["data"]["borrower_name"] == "Ada"
    assert opened.data["data"]["is_overdue"] is False

    detail = client.get(f"{ROOT}/{unit.pk}").data["data"]
    assert detail["display_status"]["value"] == "borrowed"
    assert detail["loan"]["id"] == opened.data["data"]["id"] and detail["placement"] is None

    assert client.get(f"{ROOT}/{unit.pk}/loan").status_code == 200
    extended = client.post(f"{ROOT}/{unit.pk}/actions/extend-loan", {"due_at": _due(72)}, format="json")
    assert extended.status_code == 200, extended.data

    on_loan = client.get(ROOT, {"on_loan": "true"}).data["data"]
    assert [row["id"] for row in on_loan] == [unit.pk]

    closed = client.post(f"{ROOT}/{unit.pk}/actions/return", {"condition_in": "ok", "room_id": room.pk}, format="json")
    assert closed.status_code == 200, closed.data
    assert closed.data["data"]["close_reason"] == "returned"
    after = client.get(f"{ROOT}/{unit.pk}").data["data"]
    assert after["loan"] is None and after["placement"]["room"]["id"] == room.pk
    assert client.get(f"{ROOT}/{unit.pk}/loan").status_code == 404


@pytest.mark.django_db
def test_conflicts_and_validation(client, unit, borrower):
    url = f"{ROOT}/{unit.pk}/actions/"
    assert client.post(url + "return", {}, format="json").status_code == 409
    assert (
        client.post(url + "hand-over", {"borrower_id": borrower.pk, "due_at": _due(-1)}, format="json").status_code
        == 422
    )
    client.post(url + "change-condition", {"condition": "in_maintenance"}, format="json")
    refused = client.post(url + "hand-over", {"borrower_id": borrower.pk, "due_at": _due()}, format="json")
    assert refused.status_code == 409 and refused.data["error"]["code"] == "equipment_not_available"


@pytest.mark.django_db
def test_overdue_filter(client, unit, borrower):
    client.post(f"{ROOT}/{unit.pk}/actions/hand-over", {"borrower_id": borrower.pk, "due_at": _due()}, format="json")
    assert client.get(ROOT, {"loan_overdue": "true"}).data["data"] == []
    EquipmentLoan.objects.filter(equipment=unit).update(
        handed_over_at=timezone.now() - timedelta(days=2), due_at=timezone.now() - timedelta(hours=1)
    )
    rows = client.get(ROOT, {"loan_overdue": "true"}).data["data"]
    assert [row["id"] for row in rows] == [unit.pk] and rows[0]["loan"]["is_overdue"] is True


@pytest.mark.django_db
def test_loan_actions_need_coordinator(unit, borrower):
    plain = APIClient()
    plain.force_authenticate(User.objects.create_user(username="ln-plain"))
    response = plain.post(
        f"{ROOT}/{unit.pk}/actions/hand-over", {"borrower_id": borrower.pk, "due_at": _due()}, format="json"
    )
    assert response.status_code == 403
    assert plain.get(f"{ROOT}/{unit.pk}/loan").status_code == 403
    assert plain.get("/api/labs/equipment-loans").status_code == 403
