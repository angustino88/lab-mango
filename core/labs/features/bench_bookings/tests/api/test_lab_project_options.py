"""Tests for GET /api/labs/lab-projects/options (ADR 002)."""

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient

from core.labs.models import LabProject

URL = "/api/labs/lab-projects/options"


@pytest.fixture()
def actor(db):
    return get_user_model().objects.create_user(username="project_actor", email="proj@example.com")


@pytest.fixture()
def client(actor):
    api_client = APIClient()
    api_client.force_authenticate(user=actor)
    return api_client


@pytest.mark.django_db
def test_unauthenticated_options_rejected():
    assert APIClient().get(URL, {"q": "Alpha"}).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_options_without_filter_returns_all_projects(client):
    LabProject.objects.create(project_name="P1", code="CODE1", active=True)
    response = client.get(URL)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["data"]) >= 1


@pytest.mark.django_db
def test_options_returns_project_sku_and_name(client):
    proj = LabProject.objects.create(project_name="Project Alpha", code="PRJ-A", active=True)
    LabProject.objects.create(project_name="Inactive Beta", code="PRJ-B", active=False)

    response = client.get(URL, {"q": "Alpha"})
    assert response.status_code == status.HTTP_200_OK
    assert response.data == {
        "data": [
            {"id": proj.pk, "sku": "PRJ-A", "name": "Project Alpha"},
        ]
    }
    assert "ETag" in response.headers


@pytest.mark.django_db
def test_active_on_filter(client):
    p1 = LabProject.objects.create(
        project_name="Current Project",
        code="CURR",
        active=True,
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 31),
    )
    LabProject.objects.create(
        project_name="Past Project",
        code="PAST",
        active=True,
        starts_on=date(2025, 1, 1),
        ends_on=date(2025, 12, 31),
    )

    response = client.get(URL, {"active_on": "2026-06-01"})
    assert response.status_code == status.HTTP_200_OK
    assert [item["id"] for item in response.data["data"]] == [p1.pk]


@pytest.mark.django_db
def test_include_ids_merges_retired(client):
    live = LabProject.objects.create(project_name="Live", code="LIVE", active=True)
    retired = LabProject.objects.create(project_name="Old Retired", code="OLD", active=False)

    response = client.get(URL, {"q": "Live", "include_ids": str(retired.pk)})
    assert response.status_code == status.HTTP_200_OK
    ids = [item["id"] for item in response.data["data"]]
    assert live.pk in ids
    assert retired.pk in ids
