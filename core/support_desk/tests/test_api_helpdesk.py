"""API tests for the helpdesk additions (visibility scoping, watchers, links, CSAT, teams, stats)."""

import pytest


def _create(client, setup, **extra):
    res = client.post(
        "/api/support/tickets",
        {
            "subject": "API helpdesk ticket",
            "description": "Desc",
            "category_id": setup["category"].id,
            "priority_id": setup["priority_med"].id,
            **extra,
        },
        format="json",
    )
    assert res.status_code == 201, res.content
    return res.json()["data"]


@pytest.mark.django_db
class TestTicketScopingAPI:
    def test_requester_cannot_list_or_read_foreign_tickets(self, support_setup, requester_client, agent_client):
        foreign = _create(agent_client, support_setup)  # created by the agent for themselves
        listing = requester_client.get("/api/support/tickets").json()["data"]
        assert all(t["key"] != foreign["key"] for t in listing)
        assert requester_client.get(f"/api/support/tickets/{foreign['key']}").status_code == 404
        assert requester_client.get(f"/api/support/tickets/{foreign['key']}/comments").status_code == 404
        assert requester_client.get(f"/api/support/tickets/{foreign['key']}/activity").status_code == 404

    def test_foreign_attachment_download_is_not_found(self, support_setup, requester_client, agent_client):
        from django.core.files.uploadedfile import SimpleUploadedFile

        foreign = _create(agent_client, support_setup)
        up = agent_client.post(
            f"/api/support/tickets/{foreign['key']}/attachments",
            {"file": SimpleUploadedFile("a.txt", b"secret", content_type="text/plain")},
            format="multipart",
        )
        att_id = up.json()["data"]["id"]
        assert requester_client.get(f"/api/support/attachments/{att_id}/download").status_code == 404


@pytest.mark.django_db
class TestHelpdeskEndpoints:
    def test_create_with_new_fields_and_priority_derivation(self, support_setup, requester_client):
        res = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Scope dead",
                "description": "Desc",
                "category_id": support_setup["category"].id,
                "ticket_type": "incident",
                "impact": "1",
                "urgency": "2",
                "external_reference": "VENDOR-9",
            },
            format="json",
        )
        assert res.status_code == 201
        data = res.json()["data"]
        assert data["ticket_type"] == "incident" and data["external_reference"] == "VENDOR-9"
        assert data["sla"]["state"] in {"none", "ok"}

    def test_watch_link_and_csat_flow(self, support_setup, requester_client, agent_client, agent_user):
        a = _create(requester_client, support_setup)
        b = _create(requester_client, support_setup)

        assert requester_client.post(f"/api/support/tickets/{a['key']}/watchers", {}, format="json").status_code == 201
        detail = requester_client.get(f"/api/support/tickets/{a['key']}").json()["data"]
        assert detail["is_watching"] is True

        res = agent_client.post(
            f"/api/support/tickets/{a['key']}/links",
            {"target_key": b["key"], "link_type": "blocks"},
            format="json",
        )
        assert res.status_code == 201
        dup = agent_client.post(
            f"/api/support/tickets/{a['key']}/links",
            {"target_key": b["key"], "link_type": "blocks"},
            format="json",
        )
        assert dup.status_code == 409
        denied = requester_client.post(
            f"/api/support/tickets/{a['key']}/links",
            {"target_key": b["key"], "link_type": "relates_to"},
            format="json",
        )
        assert denied.status_code == 403

        # CSAT is refused until resolved
        early = requester_client.post(f"/api/support/tickets/{a['key']}/csat", {"score": 5}, format="json")
        assert early.status_code == 422

    def test_stats_and_canned_responses_are_agent_only(self, support_setup, requester_client, agent_client):
        assert requester_client.get("/api/support/tickets/stats").status_code == 403
        res = agent_client.get("/api/support/tickets/stats")
        assert res.status_code == 200 and "open_total" in res.json()["data"]
        assert requester_client.get("/api/support/canned-responses").status_code == 403
        assert agent_client.get("/api/support/canned-responses").status_code == 200

    def test_admin_team_label_canned_response_crud(self, support_setup, requester_client, admin_client, agent_user):
        assert requester_client.post("/api/support/teams", {"name": "X"}, format="json").status_code == 403
        team = admin_client.post(
            "/api/support/teams",
            {"name": "CAN Tooling", "member_ids": [agent_user.pk]},
            format="json",
        )
        assert team.status_code == 201
        team_id = team.json()["data"]["id"]
        assert admin_client.get("/api/support/teams/options").json()["data"][0]["name"] == "CAN Tooling"

        label = admin_client.post("/api/support/labels", {"name": "Calibration"}, format="json")
        assert label.status_code == 201 and label.json()["data"]["name"] == "calibration"

        canned = admin_client.post(
            "/api/support/admin/canned-responses",
            {"title": "Ack", "body": "Hi {{requester_name}}, we are on {{ticket_key}}."},
            format="json",
        )
        assert canned.status_code == 201
        assert admin_client.delete(f"/api/support/teams/{team_id}").status_code == 204

    def test_priority_sla_targets_validated(self, support_setup, admin_client):
        bad = admin_client.post(
            "/api/support/priorities",
            {"name": "Bad", "rank": 9, "response_target_minutes": 100, "resolution_target_minutes": 50},
            format="json",
        )
        assert bad.status_code == 422
        ok = admin_client.post(
            "/api/support/priorities",
            {"name": "SLA", "rank": 8, "response_target_minutes": 15, "resolution_target_minutes": 120},
            format="json",
        )
        assert ok.status_code == 201
