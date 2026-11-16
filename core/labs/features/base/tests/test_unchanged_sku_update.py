"""An update that sends the record's own SKU back succeeds; a changed SKU is a 409 ``resource_field_immutable``.

Regression: bench, room and station updates answered 422 "<model> with this sku already exists" when a form
re-sent the unchanged SKU, and silently renamed the SKU when a different one was sent.
"""

import pytest
from rest_framework.test import APIClient

from tests.factories import BenchFactory, UserFactory, create_computing_equipment, grant_labs_role

pytestmark = pytest.mark.django_db


@pytest.fixture()
def client(settings):
    settings.MIDDLEWARE = [item for item in settings.MIDDLEWARE if not item.startswith("allauth.")]
    user = UserFactory()
    grant_labs_role(user, "admin")
    api = APIClient()
    api.force_authenticate(user)
    return api


def _create(client, resource, sku):
    response = client.post(f"/api/labs/{resource}", {"sku": sku, "name": sku}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()["data"]["id"]


def _url(client, resource):
    if resource == "benches":
        bench = BenchFactory()
        return f"/api/labs/benches/{bench.pk}", bench.sku
    sku = f"{resource.upper()}-SKU-1"
    return f"/api/labs/{resource}/{_create(client, resource, sku)}", sku


# Bench PUT is left out: it fails for every body, SKU or not (pre-existing, reported separately).
@pytest.mark.parametrize(
    ("resource", "method"),
    [("benches", "patch"), ("rooms", "patch"), ("rooms", "put"), ("stations", "patch"), ("stations", "put")],
)
def test_update_accepts_the_unchanged_sku(client, resource, method):
    url, sku = _url(client, resource)

    response = getattr(client, method)(url, {"sku": f"  {sku} ", "name": "Renamed"}, format="json")

    assert response.status_code == 200, response.json()
    assert response.json()["data"]["sku"] == sku
    assert response.json()["data"]["name"] == "Renamed"


@pytest.mark.parametrize("resource", ["benches", "rooms", "stations"])
def test_update_rejects_a_changed_sku_and_keeps_the_record(client, resource):
    url, sku = _url(client, resource)

    response = client.patch(url, {"sku": "OTHER-SKU", "name": "Renamed"}, format="json")

    assert response.status_code == 409, response.json()
    assert response.json()["error"]["code"] == "resource_field_immutable"
    after = client.get(url).json()["data"]
    assert (after["sku"], after["name"]) != ("OTHER-SKU", "Renamed")
    assert after["sku"] == sku


def test_equipment_update_accepts_the_unchanged_sku_and_rejects_a_changed_one(client):
    equipment = create_computing_equipment(sku="EQ-SKU-1")
    url = f"/api/labs/equipment/uid/{equipment.uid}"

    same = client.patch(url, {"sku": equipment.sku, "name": "Renamed"}, format="json")
    changed = client.patch(url, {"sku": "OTHER-SKU"}, format="json")

    assert same.status_code == 200, same.json()
    assert same.json()["data"]["name"] == "Renamed"
    assert changed.status_code == 409, changed.json()
    assert changed.json()["error"]["code"] == "resource_field_immutable"
