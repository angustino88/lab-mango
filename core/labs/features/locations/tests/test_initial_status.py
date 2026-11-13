"""Room and station lifecycle is a stored column defaulting to ``in_service``; the deprecated seven-value
``status`` is computed (resource-status-and-downtime.md, RS3)."""

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from core.labs.models import Room, Station
from core.users.models import User
from tests.factories import grant_labs_role, set_condition

KINDS = [("rooms", Room), ("stations", Station)]


@pytest.fixture
def client(db):
    coordinator = grant_labs_role(User.objects.create_user(username="loc-init-coord"), "coord")
    result = APIClient()
    result.force_authenticate(coordinator)
    return result, coordinator


@pytest.mark.django_db
def test_model_default_is_in_service_and_open_without_any_service():
    for model, sku in ((Room, "RM-DEFAULT"), (Station, "ST-DEFAULT")):
        resource = model.objects.create(sku=sku)
        assert (resource.lifecycle_status, resource.access_policy) == ("in_service", "open")


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "model"), KINDS)
def test_create_starts_available_with_one_record(client, path, model):
    api, coordinator = client

    response = api.post(f"/api/labs/{path}", {"sku": f"{path}-INIT", "name": "Init"}, format="json")

    assert response.status_code == 201, response.data
    body = response.data["data"]
    assert body["status"] == {"value": "available", "label": "Available"}
    assert body["lifecycle_status"] == {"value": "in_service", "label": "In service"}
    assert body["condition"]["value"] == "operational"
    assert body["availability"]["value"] == "available"
    assert "operational_status" not in body
    resource = model.objects.get(pk=body["id"])
    assert resource.lifecycle_status == "in_service"
    records = list(resource.status_records.all())
    assert [record.status for record in records] == ["in_service"]
    assert records[0].creator_id == coordinator.pk


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "model"), KINDS)
def test_deprecated_change_status_opens_downtime_and_appends_history(client, path, model):
    api, _ = client
    created = api.post(f"/api/labs/{path}", {"sku": f"{path}-CHG", "name": "Chg"}, format="json").data["data"]

    changed = api.post(
        f"/api/labs/{path}/{created['id']}/actions/change-status", {"status": "maintenance"}, format="json"
    )

    assert changed.status_code == 200, changed.data
    resource = model.objects.get(pk=created["id"])
    assert resource.lifecycle_status == "in_service"
    records = list(resource.status_records.all())
    assert [record.status for record in records] == ["in_service", "in_service"]
    assert records[0].metadata == {"legacy_status": "maintenance"}
    detail = api.get(f"/api/labs/{path}/{created['id']}").data["data"]
    assert detail["status"]["value"] == "maintenance"
    assert detail["condition"]["value"] == "in_maintenance"


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "model"), KINDS)
def test_status_filter_and_summary_read_the_computed_status(client, path, model):
    api, _ = client
    model.objects.create(sku=f"{path}-A")
    set_condition(model.objects.create(sku=f"{path}-M"), "in_maintenance")

    listed = api.get(f"/api/labs/{path}", {"status": "maintenance"})
    summary = api.get(f"/api/labs/{path}/status-summary")

    assert listed.status_code == 200, listed.data
    assert [row["sku"] for row in listed.data["data"]] == [f"{path}-M"]
    assert summary.status_code == 200, summary.data
    counts = {row["status"]["value"]: row["resource_count"] for row in summary.data["data"]["statuses"]}
    assert counts["available"] == 1
    assert counts["maintenance"] == 1
    assert summary.data["data"]["unknown_status_count"] == 0


@pytest.mark.django_db
@pytest.mark.parametrize("model", [Room, Station])
def test_database_rejects_unknown_lifecycle_and_access_policy(model):
    resource = model.objects.create(sku=f"{model.__name__}-BAD")
    for field in ("lifecycle_status", "access_policy"):
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.filter(pk=resource.pk).update(**{field: "available"})


@pytest.mark.django_db
@pytest.mark.parametrize(("path", "model"), KINDS)
def test_rejected_duplicate_create_leaves_no_extra_record(client, path, model):
    api, _ = client
    payload = {"sku": f"{path}-DUP", "name": "Dup"}
    assert api.post(f"/api/labs/{path}", payload, format="json").status_code == 201

    duplicate = api.post(f"/api/labs/{path}", payload, format="json")

    assert duplicate.status_code in (400, 409), duplicate.data
    assert model.objects.filter(sku=payload["sku"]).count() == 1
    assert model.status_records.rel.related_model.objects.count() == 1
