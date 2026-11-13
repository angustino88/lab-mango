"""HTTP contract of ``GET /equipment/{id}/status-changes``: the unit's ``display_status`` history."""

from datetime import datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from core.labs.features.equipment.queries import status_history
from core.labs.features.equipment.tests.roles import grant_labs_role
from core.labs.models import Bench, Equipment, EquipmentCategory, EquipmentKind
from tests.factories import create_computing_equipment

ROOT = "/api/labs/equipment"
START = "2026-03-02T09:00:00Z"
User = get_user_model()


@pytest.fixture
def frozen():
    with freeze_time(START) as clock:
        yield clock


@pytest.fixture
def unit(db, frozen):
    category, _ = EquipmentCategory.objects.get_or_create(
        key="computing", defaults={"name": "Computing", "definition": "Computing", "active": True}
    )
    kind = EquipmentKind.objects.create(category=category, name="SC API")
    return create_computing_equipment(sku="SC-API-1", name="Status change unit", kind=kind)


@pytest.fixture
def coordinator(db):
    return grant_labs_role(User.objects.create_user(username="sc-coord", display_name="Coord"), "coord")


@pytest.fixture
def client(coordinator):
    result = APIClient()
    result.force_authenticate(coordinator)
    return result


def _url(unit_id):
    return f"{ROOT}/{unit_id}/status-changes"


def _act(client, frozen, method, path, body=None):
    frozen.tick(timedelta(minutes=5))
    response = getattr(client, method)(f"{ROOT}/{path}", body or {}, format="json")
    assert response.status_code in (200, 204), response.data
    return response


def _labels(client, unit_id):
    response = client.get(_url(unit_id))
    assert response.status_code == 200, response.data
    return [
        (row["previous_display_status"] and row["previous_display_status"]["value"], row["display_status"]["value"])
        for row in response.data["data"]
    ]


@pytest.mark.django_db
def test_history_follows_display_status_through_bench_loan_condition_and_lifecycle(client, frozen, unit):
    bench = Bench.objects.create(sku="SC-B-1", name="Bench 1")
    _act(client, frozen, "put", f"{unit.pk}/placement", {"bench_id": bench.pk, "role": "primary"})
    _act(client, frozen, "delete", f"{unit.pk}/placement")
    _act(
        client,
        frozen,
        "post",
        f"{unit.pk}/actions/hand-over",
        {
            "borrower_name": "Ada",
            "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
        },
    )
    _act(
        client, frozen, "post", f"{unit.pk}/actions/return", {"condition": "out_of_service", "condition_in": "Cracked"}
    )
    _act(client, frozen, "post", f"{unit.pk}/actions/change-condition", {"condition": "operational"})
    _act(
        client,
        frozen,
        "post",
        f"{unit.pk}/actions/change-lifecycle",
        {
            "lifecycle_state": "retired",
            "reason": "End of life",
        },
    )

    assert _labels(client, unit.pk) == [
        ("available", "retired"),
        ("broken", "available"),
        ("borrowed", "broken"),  # return and new condition are one step, never "available" in between
        ("available", "borrowed"),
        ("in_use", "available"),
        ("available", "in_use"),
        (None, "available"),
    ]
    rows = client.get(_url(unit.pk)).data["data"]
    assert rows[0]["reason"] == "End of life"
    assert rows[0]["actor"]["username"] == "sc-coord"
    assert rows[0]["display_status"] == {"value": "retired", "label": "Retired"}
    # A step is explained by the fact behind its new label: the condition, not the closed loan.
    assert "borrower_name" not in rows[2]["details"] and rows[2]["actor"]["username"] == "sc-coord"
    assert rows[3]["details"]["borrower_name"] == "Ada"
    assert rows[4]["details"]["bench"] == {"id": bench.pk, "name": "Bench 1"}  # back to available: bench left
    assert rows[5]["details"]["bench"] == {"id": bench.pk, "name": "Bench 1"}
    assert set(rows[0]) == {
        "display_status",
        "previous_display_status",
        "occurred_at",
        "actor",
        "reason",
        "details",
    }
    assert datetime.fromisoformat(rows[-1]["occurred_at"]) == datetime.fromisoformat(START)  # unit creation


@pytest.mark.django_db
def test_leaving_service_from_maintenance_is_one_step(client, frozen, unit):
    _act(client, frozen, "post", f"{unit.pk}/actions/change-condition", {"condition": "in_maintenance"})
    _act(
        client,
        frozen,
        "post",
        f"{unit.pk}/actions/change-lifecycle",
        {
            "lifecycle_state": "transferred_out",
            "receiving_organisation": "Partner lab",
        },
    )

    assert _labels(client, unit.pk) == [
        ("maintenance", "transferred"),
        ("available", "maintenance"),
        (None, "available"),
    ]
    assert client.get(_url(unit.pk)).data["data"][0]["details"]["receiving_organisation"] == "Partner lab"


@pytest.mark.django_db
def test_lost_while_borrowed_is_one_step(client, frozen, unit):
    _act(
        client,
        frozen,
        "post",
        f"{unit.pk}/actions/hand-over",
        {
            "borrower_name": "Bo",
            "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
        },
    )
    _act(client, frozen, "post", f"{unit.pk}/actions/change-lifecycle", {"lifecycle_state": "lost"})

    assert _labels(client, unit.pk) == [("borrowed", "lost"), ("available", "borrowed"), (None, "available")]


@pytest.mark.django_db
def test_changes_that_keep_the_label_are_not_rows(client, frozen, unit):
    _act(client, frozen, "post", f"{unit.pk}/actions/change-condition", {"condition": "out_of_service"})
    # Placing a unit at a noted place changes a fact but not the label.
    _act(client, frozen, "put", f"{unit.pk}/placement", {"location_note": "Shelf 3"})

    assert _labels(client, unit.pk) == [("available", "broken"), (None, "available")]


@pytest.mark.django_db
def test_truncated_history_has_no_creation_row(client, frozen, unit, monkeypatch):
    for condition in ("in_maintenance", "operational", "out_of_service"):
        _act(client, frozen, "post", f"{unit.pk}/actions/change-condition", {"condition": condition})
    monkeypatch.setattr(status_history, "SOURCE_LIMIT", 2)

    labels = _labels(client, unit.pk)

    assert labels[0] == ("available", "broken")
    assert all(previous is not None for previous, _ in labels)


@pytest.mark.django_db
def test_unknown_and_deleted_units_are_404(client, unit):
    assert client.get(_url(999999)).status_code == 404
    Equipment.objects.filter(pk=unit.pk).update(deleted_at=timezone.now())
    assert client.get(_url(unit.pk)).status_code == 404


@pytest.mark.django_db
def test_paginated_and_rejects_unknown_query(client, frozen, unit):
    for condition in ("in_maintenance", "operational", "out_of_service"):
        _act(client, frozen, "post", f"{unit.pk}/actions/change-condition", {"condition": condition})

    page = client.get(_url(unit.pk), {"page_size": 2})

    assert page.status_code == 200, page.data
    assert len(page.data["data"]) == 2
    assert page.data["meta"]["pagination"]["count"] == 4
    assert client.get(_url(unit.pk), {"axis": "condition"}).status_code == 400


@pytest.mark.django_db
def test_needs_coordinator(unit):
    anonymous = APIClient()
    plain = APIClient()
    plain.force_authenticate(User.objects.create_user(username="sc-plain"))
    labs_user = APIClient()
    labs_user.force_authenticate(grant_labs_role(User.objects.create_user(username="sc-user"), "user"))
    assert anonymous.get(_url(unit.pk)).status_code in (401, 403)
    assert plain.get(_url(unit.pk)).status_code == 403
    assert labs_user.get(_url(unit.pk)).status_code == 403


@pytest.mark.django_db
def test_query_budget_does_not_grow_with_history(client, frozen, unit, django_assert_num_queries):
    bench = Bench.objects.create(sku="SC-B-2", name="Bench 2")
    for _ in range(3):
        _act(client, frozen, "put", f"{unit.pk}/placement", {"bench_id": bench.pk, "role": "primary"})
        _act(client, frozen, "delete", f"{unit.pk}/placement")
        _act(
            client,
            frozen,
            "post",
            f"{unit.pk}/actions/hand-over",
            {
                "borrower_name": "Di",
                "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
            },
        )
        _act(client, frozen, "post", f"{unit.pk}/actions/return", {})
    client.get(_url(unit.pk))  # warm the per-user Labs role cache

    with django_assert_num_queries(4):
        # unit, events, loans with slip and people, bench placements with bench and people
        response = client.get(_url(unit.pk))
    assert response.status_code == 200
    assert response.data["meta"]["pagination"]["count"] == 13
