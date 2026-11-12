"""Tests for locations selectors and catalog endpoints (ADR 002)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from core.labs.models import Building, City, Country, Room, Station, StationType
from tests.factories import grant_labs_role


@pytest.fixture()
def actor(db):
    return get_user_model().objects.create_user(username="loc_user", email="loc@example.com")


@pytest.fixture()
def client(actor):
    c = APIClient()
    grant_labs_role(actor, "coord")
    c.force_authenticate(user=actor)
    return c


@pytest.mark.django_db
def test_country_options(client):
    Country.objects.create(name="Germany", code="DE")
    resp = client.get("/api/labs/countries/options")
    assert resp.status_code == status.HTTP_200_OK
    assert "ETag" in resp.headers
    assert any(item["name"] == "Germany" and item["sku"] == "DE" for item in resp.data["data"])


@pytest.mark.django_db
def test_city_options_filtering(client):
    de = Country.objects.create(name="Germany", code="DE")
    city = City.objects.create(name="Berlin", country=de)

    # Empty filter returns all
    assert client.get("/api/labs/cities/options").status_code == status.HTTP_200_OK

    # Filter with q
    resp_q = client.get("/api/labs/cities/options?q=Ber")
    assert resp_q.status_code == status.HTTP_200_OK
    assert resp_q.data["data"] == [{"id": city.pk, "sku": None, "name": "Berlin"}]

    # Filter with country_id
    resp_cid = client.get(f"/api/labs/cities/options?country_id={de.pk}")
    assert resp_cid.status_code == status.HTTP_200_OK
    assert any(item["name"] == "Berlin" for item in resp_cid.data["data"])


@pytest.mark.django_db
def test_building_options(client):
    de = Country.objects.create(name="Germany", code="DE")
    city = City.objects.create(name="Stuttgart", country=de)
    b = Building.objects.create(name="Building 101", city=city)

    # Empty filter returns 200
    assert client.get("/api/labs/buildings/options").status_code == status.HTTP_200_OK

    # Filter with q
    resp = client.get("/api/labs/buildings/options?q=101")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["data"] == [{"id": b.pk, "sku": None, "name": "Building 101"}]


@pytest.mark.django_db
def test_room_options(client):
    room = Room.objects.create(name="Lab Room 1", sku="ROOM-01")

    # Empty filter returns 200
    assert client.get("/api/labs/rooms/options").status_code == status.HTTP_200_OK

    resp = client.get("/api/labs/rooms/options?q=Room")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["data"] == [{"id": room.pk, "sku": "ROOM-01", "name": "Lab Room 1"}]


@pytest.mark.django_db
def test_station_and_station_type_options(client):
    st_type = StationType.objects.create(name="Soldering Station")
    st = Station.objects.create(name="Bench Station 1", sku="ST-01", type=st_type)

    # Station type is small: returns all without filter
    resp_type = client.get("/api/labs/station-types/options")
    assert resp_type.status_code == status.HTTP_200_OK
    assert any(item["name"] == "Soldering Station" and item["sku"] is None for item in resp_type.data["data"])

    # Station returns 200 without filter
    assert client.get("/api/labs/stations/options").status_code == status.HTTP_200_OK

    resp_st = client.get("/api/labs/stations/options?q=Station")
    assert resp_st.status_code == status.HTTP_200_OK
    assert resp_st.data["data"] == [{"id": st.pk, "sku": "ST-01", "name": "Bench Station 1"}]
