"""HTTP contract of the change-condition and change-lifecycle actions (redesign step 2)."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import ComputingEquipment, EquipmentCategory, EquipmentKind
from core.labs.models.resource.equipment.display import DisplayEquipment

ROOT = "/api/labs/equipment"
User = get_user_model()


def _kind(key):
    category, _ = EquipmentCategory.objects.get_or_create(
        key=key, defaults={"name": key.title(), "definition": key, "active": True}
    )
    return EquipmentKind.objects.create(category=category, name=f"{key} kind")


@pytest.fixture
def unit(db):
    return ComputingEquipment.objects.create(sku="ST-API-1", name="API unit", kind=_kind("computing"))


@pytest.fixture
def client(db):
    result = APIClient()
    result.force_authenticate(grant_labs_role(User.objects.create_user(username="st-coord"), "coord"))
    return result


@pytest.mark.django_db
@pytest.mark.parametrize("prefix", ["", "/computing"])
def test_change_condition_returns_updated_equipment(client, unit, prefix):
    response = client.post(
        f"{ROOT}{prefix}/{unit.pk}/actions/change-condition",
        {"condition": "in_maintenance", "reason": "Fan noise"},
        format="json",
    )
    assert response.status_code == 200, response.data
    body = response.data["data"]
    assert body["display_status"]["value"] == "maintenance"
    assert body["condition"]["value"] == "in_maintenance"
    assert body["lifecycle_state"]["value"] == "in_service"
    assert "status" not in body


@pytest.mark.django_db
def test_change_lifecycle_transfer_and_invalid_transition(client, unit):
    url = f"{ROOT}/computing/{unit.pk}/actions/change-lifecycle"
    missing = client.post(url, {"lifecycle_state": "transferred_out"}, format="json")
    assert missing.status_code == 422
    done = client.post(
        url, {"lifecycle_state": "transferred_out", "receiving_organisation": "Partner lab"}, format="json"
    )
    assert done.status_code == 200, done.data
    assert done.data["data"]["display_status"]["value"] == "transferred"
    invalid = client.post(url, {"lifecycle_state": "lost"}, format="json")
    assert invalid.status_code == 409
    assert invalid.data["error"]["code"] == "invalid_state_transition"


@pytest.mark.django_db
def test_category_routes_isolate_units_and_hide_deleted(client, unit):
    display = DisplayEquipment.objects.create(sku="ST-API-D", name="Screen", kind=_kind("display"))
    body = {"condition": "out_of_service"}
    assert (
        client.post(f"{ROOT}/computing/{display.pk}/actions/change-condition", body, format="json").status_code == 404
    )
    assert client.post(f"{ROOT}/computing/999999/actions/change-condition", body, format="json").status_code == 404
    ComputingEquipment.objects.filter(pk=unit.pk).update(deleted_at=timezone.now())
    assert client.post(f"{ROOT}/{unit.pk}/actions/change-condition", body, format="json").status_code == 404


@pytest.mark.django_db
def test_invalid_values_are_422(client, unit):
    url = f"{ROOT}/{unit.pk}/actions/"
    assert client.post(url + "change-condition", {"condition": "broken"}, format="json").status_code == 422
    assert client.post(url + "change-lifecycle", {"lifecycle_state": "gone"}, format="json").status_code == 422


@pytest.mark.django_db
def test_state_actions_need_coordinator(unit):
    anonymous = APIClient()
    plain = APIClient()
    plain.force_authenticate(User.objects.create_user(username="st-plain"))
    url = f"{ROOT}/{unit.pk}/actions/change-condition"
    assert anonymous.post(url, {"condition": "in_maintenance"}, format="json").status_code in (401, 403)
    assert plain.post(url, {"condition": "in_maintenance"}, format="json").status_code == 403


@pytest.mark.django_db
def test_list_filters_on_display_status_lifecycle_and_condition(client, unit):
    planned = ComputingEquipment.objects.create(
        sku="ST-API-2", name="Planned", kind=unit.kind, lifecycle_state="planned"
    )
    client.post(f"{ROOT}/{unit.pk}/actions/change-condition", {"condition": "in_maintenance"}, format="json")

    def ids(**query):
        response = client.get(ROOT, query)
        assert response.status_code == 200, response.data
        return {row["id"] for row in response.data["data"]}

    assert ids(status="maintenance") == {unit.pk}
    assert ids(status="on_order") == {planned.pk}
    assert ids(lifecycle_state="planned") == {planned.pk}
    assert ids(condition="in_maintenance") == {unit.pk}
    assert client.get(ROOT, {"status": "in_storage"}).status_code == 400
