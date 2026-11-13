"""New rooms and stations start with an ``available`` status record; no ``operational_status`` field."""

import pytest
from rest_framework.test import APIClient

from core.labs.models import Room, Station
from core.users.models import User
from tests.factories import grant_labs_role


@pytest.fixture
def client(db):
    coordinator = grant_labs_role(User.objects.create_user(username="loc-init-coord"), "coord")
    result = APIClient()
    result.force_authenticate(coordinator)
    return result, coordinator


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "model"), [("rooms", Room), ("stations", Station)])
def test_create_starts_available_with_one_record(client, path, model):
    api, coordinator = client

    response = api.post(f"/api/labs/{path}", {"sku": f"{path}-INIT", "name": "Init"}, format="json")

    assert response.status_code == 201, response.data
    body = response.data["data"]
    assert body["status"] == {"value": "available", "label": "Available"}
    assert "operational_status" not in body
    records = list(model.objects.get(pk=body["id"]).status_records.all())
    assert [record.status for record in records] == ["available"]
    assert records[0].creator_id == coordinator.pk


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "model"), [("rooms", Room), ("stations", Station)])
def test_rejected_duplicate_create_leaves_no_extra_record(client, path, model):
    api, _ = client
    payload = {"sku": f"{path}-DUP", "name": "Dup"}
    assert api.post(f"/api/labs/{path}", payload, format="json").status_code == 201

    duplicate = api.post(f"/api/labs/{path}", payload, format="json")

    assert duplicate.status_code in (400, 409), duplicate.data
    assert model.objects.filter(sku=payload["sku"]).count() == 1
    assert model.status_records.rel.related_model.objects.count() == 1
