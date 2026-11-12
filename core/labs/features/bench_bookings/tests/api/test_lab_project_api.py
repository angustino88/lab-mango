"""HTTP and selector tests for lab project reads (owned by bench_bookings)."""

import pytest
from django.db import connection, models
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from core.labs.features.bench_bookings.exceptions import LabProjectNotFound
from core.labs.features.bench_bookings.queries import get_lab_project, list_lab_projects
from core.labs.models import BenchBooking, LabProject

URL = "/api/labs/lab-projects"


@pytest.fixture()
def projects(db):
    return [
        LabProject.objects.create(project_name="Beta", code="B-1"),
        LabProject.objects.create(project_name="Alpha", code="A-1"),
        LabProject.objects.create(project_name="Gamma", code="G-1", active=False),
    ]


@pytest.mark.django_db
class TestListApi:
    def test_anonymous_is_rejected(self):
        assert APIClient().get(URL).status_code in (401, 403)

    def test_lists_ordered_by_name_with_expected_shape(self, api_client, projects):
        response = api_client.get(URL)
        assert response.status_code == 200
        rows = response.json()["data"]
        assert [row["name"] for row in rows] == ["Alpha", "Beta", "Gamma"]
        assert set(rows[0]) == {"id", "name", "code", "active", "starts_on", "ends_on"}
        assert response.json()["meta"]["pagination"]["count"] == 3

    def test_filters_by_search_and_active(self, api_client, projects):
        assert [r["name"] for r in api_client.get(URL, {"search": "alp"}).json()["data"]] == ["Alpha"]
        assert [r["code"] for r in api_client.get(URL, {"search": "G-1"}).json()["data"]] == ["G-1"]
        assert [r["name"] for r in api_client.get(URL, {"active": "false"}).json()["data"]] == ["Gamma"]

    def test_unknown_query_parameter_is_bad_request(self, api_client, projects):
        assert api_client.get(URL, {"bogus": "1"}).status_code == 400

    def test_list_query_count_is_constant(self, api_client, db):
        LabProject.objects.create(project_name="One")
        # Warm the per-user Labs role cache (one query on the first request) before measuring.
        api_client.get(URL)
        with CaptureQueriesContext(connection) as small:
            api_client.get(URL)
        for index in range(10):
            LabProject.objects.create(project_name=f"Many {index}")
        with CaptureQueriesContext(connection) as large:
            api_client.get(URL)
        assert len(large) == len(small)


@pytest.mark.django_db
class TestDetailApi:
    def test_returns_project(self, api_client, projects):
        response = api_client.get(f"{URL}/{projects[0].pk}")
        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Beta"

    def test_missing_project_is_not_found(self, api_client, db):
        response = api_client.get(f"{URL}/999999")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "lab_project_not_found"

    def test_anonymous_is_rejected(self, projects):
        assert APIClient().get(f"{URL}/{projects[0].pk}").status_code in (401, 403)


@pytest.mark.django_db
class TestSelectors:
    def test_get_missing_raises(self):
        with pytest.raises(LabProjectNotFound):
            get_lab_project(project_id=1)

    def test_list_filters(self, projects):
        assert list_lab_projects(active=True).count() == 2
        assert list_lab_projects(search="beta").count() == 1


def test_booking_project_fk_is_set_null():
    """FK audit: removing a project must not delete bookings."""
    assert BenchBooking._meta.get_field("project").remote_field.on_delete is models.SET_NULL
