"""Tests for the Support Desk /options selector standard (ADR 002)."""

import pytest

from core.support_desk.models.category import SupportCategory
from core.support_desk.models.label import SupportLabel
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.team import SupportTeam


@pytest.mark.django_db
class TestSupportOptionsStandard:
    """Ensure options endpoints strictly conform to flat {id, sku, name} standard."""

    def test_category_options_shape_and_filtering(self, support_setup, requester_client):
        # Create an inactive category (should not appear in options)
        SupportCategory.objects.create(name="Inactive Category", is_active=False)

        resp = requester_client.get("/api/support/categories/options")
        assert resp.status_code == 200
        assert "ETag" in resp.headers
        data = resp.json()["data"]
        assert isinstance(data, list)
        assert len(data) >= 1

        for item in data:
            assert set(item.keys()) == {"id", "sku", "name"}
            assert isinstance(item["id"], int)
            assert isinstance(item["name"], str)
            assert isinstance(item["sku"], str)
            assert item["name"] != "Inactive Category"

        # Search filter test with q
        resp_q = requester_client.get("/api/support/categories/options?q=General")
        assert resp_q.status_code == 200
        search_data = resp_q.json()["data"]
        assert any(item["name"] == "General Hardware" for item in search_data)

    def test_priority_options_shape_and_filtering(self, support_setup, requester_client):
        SupportPriority.objects.create(name="Archived Priority", rank=9, code="", is_active=False)
        p_null_code = SupportPriority.objects.create(name="No Code Priority", rank=10, code="", is_active=True)

        resp = requester_client.get("/api/support/priorities/options")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 3

        for item in data:
            assert set(item.keys()) == {"id", "sku", "name"}
            assert item["name"] != "Archived Priority"
            # sku must be string or None, never integer
            assert item["sku"] is None or isinstance(item["sku"], str)

        item_null = next(item for item in data if item["id"] == p_null_code.pk)
        assert item_null["sku"] is None

    def test_status_options_shape_and_filtering(self, support_setup, requester_client):
        SupportStatus.objects.create(name="Archived Status", system_state="done", is_active=False)

        resp = requester_client.get("/api/support/statuses/options")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 4

        for item in data:
            assert set(item.keys()) == {"id", "sku", "name"}
            assert item["sku"] is None
            assert item["name"] != "Archived Status"

        # Filter by system_state
        resp_filtered = requester_client.get("/api/support/statuses/options?system_state=done")
        assert resp_filtered.status_code == 200
        assert all(item["id"] in [s.id for s in SupportStatus.objects.filter(system_state="done")] for item in resp_filtered.json()["data"])

    def test_team_and_label_options(self, support_setup, requester_client):
        SupportTeam.objects.create(name="Hardware Ops", code="hw-ops", is_active=True)
        SupportTeam.objects.create(name="Inactive Team", code="inact", is_active=False)
        label = SupportLabel.objects.create(name="calibration")

        resp_team = requester_client.get("/api/support/teams/options")
        assert resp_team.status_code == 200
        team_items = resp_team.json()["data"]
        assert any(item["name"] == "Hardware Ops" and item["sku"] == "hw-ops" for item in team_items)
        assert not any(item["name"] == "Inactive Team" for item in team_items)

        # Label options without filter returns all
        resp_label_no_filter = requester_client.get("/api/support/labels/options")
        assert resp_label_no_filter.status_code == 200
        assert any(item["name"] == "calibration" for item in resp_label_no_filter.json()["data"])

        resp_label = requester_client.get("/api/support/labels/options?q=calib")
        assert resp_label.status_code == 200
        assert resp_label.json()["data"] == [{"id": label.pk, "sku": None, "name": "calibration"}]

    def test_admin_routes_moved_to_resource_roots(self, support_setup, requester_client):
        # Requester can read categories catalog
        resp = requester_client.get("/api/support/categories")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

        # Non-admin cannot write
        resp_post = requester_client.post("/api/support/categories", {"name": "New Cat"})
        assert resp_post.status_code == 403
