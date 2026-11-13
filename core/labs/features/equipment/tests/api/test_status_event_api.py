"""HTTP contract of ``GET /equipment/{id}/status-events``: the unit's recorded state changes."""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import Equipment, EquipmentCategory, EquipmentEvent, EquipmentKind
from tests.factories import create_computing_equipment

ROOT = "/api/labs/equipment"
User = get_user_model()


@pytest.fixture
def unit(db):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    kind = EquipmentKind.objects.create(category=category, name="SE API")
    return create_computing_equipment(sku="SE-API-1", name="Status event unit", kind=kind)


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="se-coord", display_name="Coord"), "coord")


@pytest.fixture
def client(coordinator):
    result = APIClient()
    result.force_authenticate(coordinator)
    return result


def _events_url(unit_id):
    return f"{ROOT}/{unit_id}/status-events"


@pytest.mark.django_db
def test_lists_recorded_changes_newest_first(client, unit, coordinator):
    before = EquipmentEvent.objects.filter(equipment=unit).count()
    actions = f"{ROOT}/{unit.pk}/actions/"
    assert (
        client.post(
            actions + "change-condition", {"condition": "in_maintenance", "reason": "Fan noise"}, format="json"
        ).status_code
        == 200
    )
    assert (
        client.post(
            actions + "change-lifecycle",
            {"lifecycle_state": "transferred_out", "receiving_organisation": "Partner lab"},
            format="json",
        ).status_code
        == 200
    )

    response = client.get(_events_url(unit.pk))

    assert response.status_code == 200, response.data
    rows = response.data["data"]
    # Leaving service resets the condition to operational, then records the lifecycle move.
    assert len(rows) == EquipmentEvent.objects.filter(equipment=unit).count() > before
    assert [row["id"] for row in rows] == list(
        EquipmentEvent.objects.filter(equipment=unit).order_by("-occurred_at", "-id").values_list("id", flat=True)
    )
    transfer = next(row for row in rows if row["to_value"]["value"] == "transferred_out")
    assert transfer["axis"] == {"value": "lifecycle", "label": "Lifecycle"}
    assert transfer["from_value"]["value"] == "in_service"
    assert transfer["details"]["receiving_organisation"] == "Partner lab"
    assert transfer["actor"] == {"id": coordinator.pk, "username": "se-coord", "display_name": "Coord"}
    maintenance = next(row for row in rows if row["to_value"]["value"] == "in_maintenance")
    assert maintenance["axis"]["value"] == "condition"
    assert maintenance["from_value"]["value"] == "operational"
    assert maintenance["reason"] == "Fan noise"
    assert set(maintenance) == {
        "id",
        "axis",
        "from_value",
        "to_value",
        "reason",
        "details",
        "actor",
        "occurred_at",
    }


@pytest.mark.django_db
def test_initial_state_has_null_from_value_and_actor(client, unit):
    EquipmentEvent.objects.filter(equipment=unit).delete()
    EquipmentEvent.objects.create(equipment=unit, axis="lifecycle", from_value="", to_value="in_service")

    rows = client.get(_events_url(unit.pk)).data["data"]

    assert len(rows) == 1
    assert rows[0]["from_value"] is None
    assert rows[0]["actor"] is None
    assert rows[0]["to_value"] == {"value": "in_service", "label": "In service"}


@pytest.mark.django_db
def test_only_this_units_events_and_empty_history(client, unit):
    other = create_computing_equipment(sku="SE-API-2", name="Other", kind=unit.kind)
    EquipmentEvent.objects.filter(equipment__in=[unit, other]).delete()
    EquipmentEvent.objects.create(
        equipment=other, axis="condition", from_value="operational", to_value="out_of_service"
    )

    response = client.get(_events_url(unit.pk))

    assert response.status_code == 200
    assert response.data["data"] == []


@pytest.mark.django_db
def test_unknown_and_deleted_units_are_404(client, unit):
    assert client.get(_events_url(999999)).status_code == 404
    Equipment.objects.filter(pk=unit.pk).update(deleted_at=timezone.now())
    assert client.get(_events_url(unit.pk)).status_code == 404


@pytest.mark.django_db
def test_paginated_and_rejects_unknown_query(client, unit):
    EquipmentEvent.objects.filter(equipment=unit).delete()
    values = ["operational", "in_maintenance"] * 3
    for previous, current in zip(values, values[1:], strict=False):
        EquipmentEvent.objects.create(equipment=unit, axis="condition", from_value=previous, to_value=current)

    page = client.get(_events_url(unit.pk), {"page_size": 2})

    assert page.status_code == 200, page.data
    assert len(page.data["data"]) == 2
    assert client.get(_events_url(unit.pk), {"axis": "condition"}).status_code == 400


@pytest.mark.django_db
def test_needs_coordinator(unit):
    anonymous = APIClient()
    plain = APIClient()
    plain.force_authenticate(User.objects.create_user(username="se-plain"))
    labs_user = APIClient()
    labs_user.force_authenticate(grant_labs_role(User.objects.create_user(username="se-user"), "user"))
    assert anonymous.get(_events_url(unit.pk)).status_code in (401, 403)
    assert plain.get(_events_url(unit.pk)).status_code == 403
    assert labs_user.get(_events_url(unit.pk)).status_code == 403


@pytest.mark.django_db
def test_query_budget_does_not_grow_with_events(client, unit, coordinator, django_assert_num_queries):
    EquipmentEvent.objects.filter(equipment=unit).delete()
    values = ["operational", "in_maintenance"] * 6
    for previous, current in zip(values, values[1:], strict=False):
        EquipmentEvent.objects.create(
            equipment=unit, axis="condition", from_value=previous, to_value=current, actor=coordinator
        )
    # Warm the per-user Labs role cache before measuring.
    client.get(_events_url(unit.pk))

    with django_assert_num_queries(3):
        # 1: unit visibility, 2: count, 3: page with the actor joined
        response = client.get(_events_url(unit.pk))
    assert response.status_code == 200
    assert len(response.data["data"]) == 11
