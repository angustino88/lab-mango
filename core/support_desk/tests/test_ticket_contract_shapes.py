"""Wire shapes of Support Desk responses (response standard REL-3, REL-14, REL-16, ENU-1, NAM-2; ADR 007)."""

import pytest

from core.support_desk.tests.test_api_helpdesk import _create


@pytest.mark.django_db
class TestTicketContractShapes:
    def test_ticket_lookups_are_relations_and_enums_are_choices(self, support_setup, agent_client):
        created = _create(agent_client, support_setup, ticket_type="incident")
        detail = agent_client.get(f"/api/support/tickets/{created['key']}").json()["data"]
        listed = next(
            row for row in agent_client.get("/api/support/tickets").json()["data"] if row["id"] == detail["id"]
        )
        for row in (detail, listed):
            assert row["priority"] == {"id": support_setup["priority_med"].id, "name": "Medium"}
            assert set(row["category"]) == {"id", "name"}
            assert set(row["status"]) == {"id", "name"}
            assert row["ticket_type"] == {"value": "incident", "label": "Incident"}
            assert set(row["source"]) == {"value", "label"}
            assert set(row["requester"]) == {"id", "name"}

    def test_queue_stats_dimensions_are_relations(self, support_setup, agent_client, agent_user):
        created = _create(agent_client, support_setup)
        assigned = agent_client.post(
            f"/api/support/tickets/{created['key']}/assign", {"assignee_id": agent_user.id}, format="json"
        )
        assert assigned.status_code == 200, assigned.content
        stats = agent_client.get("/api/support/tickets/stats").json()["data"]
        priority_row = next(
            row for row in stats["by_priority"] if row["priority"]["id"] == support_setup["priority_med"].id
        )
        assert priority_row["priority"] == {"id": support_setup["priority_med"].id, "name": "Medium"}
        assert {"rank", "count"} <= set(priority_row)
        for row in stats["by_team"]:
            assert row["team"] is None or set(row["team"]) == {"id", "name"}
        assignee_row = next(row for row in stats["by_assignee"] if row["assignee"]["id"] == agent_user.id)
        assert set(assignee_row["assignee"]) == {"id", "name"} and assignee_row["assignee"]["name"]

    def test_admin_boolean_names_match_on_read_and_write(self, support_setup, admin_client):
        settings = admin_client.patch(
            "/api/support/admin/settings", {"is_sla_enabled": False, "is_csat_enabled": True}, format="json"
        )
        assert settings.status_code == 200, settings.content
        data = settings.json()["data"]
        assert data["is_sla_enabled"] is False and data["is_csat_enabled"] is True
        assert "sla_enabled" not in data and "csat_enabled" not in data
        assert set(data["default_ticket_type"]) == {"value", "label"}

        status = admin_client.patch(
            f"/api/support/statuses/{support_setup['status_active'].id}", {"is_sla_paused": True}, format="json"
        )
        assert status.status_code == 200, status.content
        assert status.json()["data"]["is_sla_paused"] is True
        assert set(status.json()["data"]["system_state"]) == {"value", "label"}
