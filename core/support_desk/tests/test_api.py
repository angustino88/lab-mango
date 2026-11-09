"""API integration tests for all Support Desk endpoints and contracts."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.support_desk.contracts import CommentVisibility
from tests.factories import BenchFactory


@pytest.mark.django_db
class TestTicketAPIEndpoints:
    def test_ticket_create_and_get_detail(self, support_setup, requester_client, requester_user):
        payload = {
            "subject": "Multimeter out of calibration",
            "description": "Voltage readings deviate by 5V.",
            "category_id": support_setup["category"].id,
            "priority_id": support_setup["priority_med"].id,
        }
        res_create = requester_client.post("/api/support/tickets", payload, format="json")
        assert res_create.status_code == 201
        data = res_create.json()["data"]
        key = data["key"]
        assert key.startswith("SUP-")
        assert data["subject"] == payload["subject"]
        assert data["status"]["name"] == "Open"
        assert data["requester"]["id"] == requester_user.id

        # GET detail
        res_get = requester_client.get(f"/api/support/tickets/{key}")
        assert res_get.status_code == 200
        get_data = res_get.json()["data"]
        assert get_data["key"] == key
        assert get_data["description"] == payload["description"]

    def test_ticket_list_filtering(self, support_setup, requester_client, requester_user):
        # Create ticket under test
        requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Filter target ticket",
                "description": "Specific keywords",
                "category_id": support_setup["category"].id,
                "priority_id": support_setup["priority_high"].id,
            },
            format="json",
        )

        # List all
        res_all = requester_client.get("/api/support/tickets")
        assert res_all.status_code == 200
        assert "data" in res_all.json()

        # Filter by priority_id
        res_filter = requester_client.get(f"/api/support/tickets?priority_id={support_setup['priority_high'].id}")
        assert res_filter.status_code == 200
        items = res_filter.json()["data"]
        assert all(item["priority"]["id"] == support_setup["priority_high"].id for item in items)

    def test_ticket_optimistic_locking_conflict(self, support_setup, requester_client):
        res = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Concurrency ticket",
                "description": "Desc",
                "category_id": support_setup["category"].id,
                "priority_id": support_setup["priority_med"].id,
            },
            format="json",
        )
        ticket_data = res.json()["data"]
        key = ticket_data["key"]
        version = ticket_data["version"]

        # Valid update
        res_up1 = requester_client.patch(
            f"/api/support/tickets/{key}",
            {"version": version, "subject": "Updated subject"},
            format="json",
        )
        assert res_up1.status_code == 200
        new_version = res_up1.json()["data"]["version"]
        assert new_version == version + 1

        # Stale update returns 409
        res_stale = requester_client.patch(
            f"/api/support/tickets/{key}",
            {"version": version, "subject": "Stale update attempt"},
            format="json",
        )
        assert res_stale.status_code == 409

    def test_ticket_assignment_permissions(self, support_setup, requester_client, agent_client, agent_user):
        res = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Assign ticket test",
                "description": "Desc",
                "category_id": support_setup["category"].id,
                "priority_id": support_setup["priority_med"].id,
            },
            format="json",
        )
        key = res.json()["data"]["key"]

        # Requester cannot assign ticket (403)
        res_req_assign = requester_client.post(
            f"/api/support/tickets/{key}/assign",
            {"assignee_id": agent_user.id},
            format="json",
        )
        assert res_req_assign.status_code == 403

        # Agent can assign ticket (200)
        res_agent_assign = agent_client.post(
            f"/api/support/tickets/{key}/assign",
            {"assignee_id": agent_user.id},
            format="json",
        )
        assert res_agent_assign.status_code == 200
        assert res_agent_assign.json()["data"]["assignee"]["id"] == agent_user.id

    def test_ticket_transitions_and_validation(self, support_setup, requester_client, agent_client):
        res = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Transition workflow ticket",
                "description": "Desc",
                "category_id": support_setup["category"].id,
                "priority_id": support_setup["priority_med"].id,
            },
            format="json",
        )
        ticket = res.json()["data"]
        key = ticket["key"]
        v1 = ticket["version"]

        # Open -> In Progress
        res_t1 = agent_client.post(
            f"/api/support/tickets/{key}/transitions",
            {"to_status_id": support_setup["status_active"].id, "version": v1},
            format="json",
        )
        assert res_t1.status_code == 200
        v2 = res_t1.json()["data"]["version"]

        # In Progress -> Resolved without summary returns 422 / 400
        res_t2_fail = agent_client.post(
            f"/api/support/tickets/{key}/transitions",
            {"to_status_id": support_setup["status_resolved"].id, "version": v2, "resolution_summary": ""},
            format="json",
        )
        assert res_t2_fail.status_code in (400, 422)

        # In Progress -> Resolved with summary
        res_t2 = agent_client.post(
            f"/api/support/tickets/{key}/transitions",
            {
                "to_status_id": support_setup["status_resolved"].id,
                "version": v2,
                "resolution_summary": "Replaced fuse and calibrated unit.",
            },
            format="json",
        )
        assert res_t2.status_code == 200
        v3 = res_t2.json()["data"]["version"]

        # Resolved -> Open (Reopen) with reason
        res_reopen = requester_client.post(
            f"/api/support/tickets/{key}/transitions",
            {
                "to_status_id": support_setup["status_open"].id,
                "version": v3,
                "reason": "Calibration drifted again within 2 hours.",
            },
            format="json",
        )
        assert res_reopen.status_code == 200
        assert res_reopen.json()["data"]["status"]["name"] == "Open"


@pytest.mark.django_db
class TestResourceTraceabilityEndpoints:
    def test_link_unlink_and_history(self, support_setup, requester_client, agent_client):
        bench = BenchFactory(sku="BENCH-API-TEST-01", name="API Traceable Bench")
        res = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Bench traceability test",
                "description": "Desc",
                "category_id": support_setup["category"].id,
                "priority_id": support_setup["priority_med"].id,
            },
            format="json",
        )
        key = res.json()["data"]["key"]

        # Link resource
        res_link = requester_client.post(
            f"/api/support/tickets/{key}/resources",
            {"resource_type": "bench", "resource_id": str(bench.id)},
            format="json",
        )
        assert res_link.status_code == 201
        assert res_link.json()["data"]["snapshot"]["name"] == "API Traceable Bench"

        # Duplicate link returns 409
        res_dup = requester_client.post(
            f"/api/support/tickets/{key}/resources",
            {"resource_type": "bench", "resource_id": str(bench.id)},
            format="json",
        )
        assert res_dup.status_code == 409

        # Resource incident history endpoint
        res_history = requester_client.get(f"/api/support/resources/bench/{bench.id}/tickets")
        assert res_history.status_code == 200
        history_data = res_history.json()["data"]
        assert history_data["open_count"] >= 1
        assert any(t["key"] == key for t in history_data["tickets"])

        # Unlink resource (agent allowed)
        res_unlink = agent_client.delete(
            f"/api/support/tickets/{key}/resources",
            {"resource_type": "bench", "resource_id": str(bench.id), "reason": "Completed testing"},
            format="json",
        )
        assert res_unlink.status_code == 204


@pytest.mark.django_db
class TestCommentsAndActivityVisibility:
    def test_public_and_internal_comments_and_audit(self, support_setup, requester_client, agent_client):
        res = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Comments test ticket",
                "description": "Desc",
                "category_id": support_setup["category"].id,
                "priority_id": support_setup["priority_med"].id,
            },
            format="json",
        )
        key = res.json()["data"]["key"]

        # Requester adds public comment
        res_c1 = requester_client.post(
            f"/api/support/tickets/{key}/comments",
            {"body": "Public comment from user."},
            format="json",
        )
        assert res_c1.status_code == 201

        # Requester denied internal note (403)
        res_c_fail = requester_client.post(
            f"/api/support/tickets/{key}/comments",
            {"body": "Internal secret", "visibility": "internal"},
            format="json",
        )
        assert res_c_fail.status_code == 403

        # Agent adds internal note (201)
        res_c2 = agent_client.post(
            f"/api/support/tickets/{key}/comments",
            {"body": "Internal agent assessment.", "visibility": "internal"},
            format="json",
        )
        assert res_c2.status_code == 201

        # Requester reading comments sees ONLY public
        res_req_comments = requester_client.get(f"/api/support/tickets/{key}/comments")
        assert res_req_comments.status_code == 200
        req_bodies = [c["body"] for c in res_req_comments.json()["data"]]
        assert "Public comment from user." in req_bodies
        assert "Internal agent assessment." not in req_bodies

        # Agent reading comments sees BOTH
        res_agent_comments = agent_client.get(f"/api/support/tickets/{key}/comments")
        assert res_agent_comments.status_code == 200
        agent_bodies = [c["body"] for c in res_agent_comments.json()["data"]]
        assert "Public comment from user." in agent_bodies
        assert "Internal agent assessment." in agent_bodies

        # Activity endpoint respects internal note privacy
        res_req_acts = requester_client.get(f"/api/support/tickets/{key}/activity")
        assert res_req_acts.status_code == 200
        # No internal comment payload visible to requester
        for act in res_req_acts.json()["data"]:
            if act["event_type"] == "comment_added":
                assert act["payload"].get("visibility") != CommentVisibility.INTERNAL.value


@pytest.mark.django_db
class TestAttachmentAPIEndpoints:
    def test_upload_and_download_attachment(self, support_setup, requester_client, agent_client):
        res_ticket = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Attachment API ticket",
                "description": "Desc",
                "category_id": support_setup["category"].id,
                "priority_id": support_setup["priority_med"].id,
            },
            format="json",
        )
        key = res_ticket.json()["data"]["key"]

        uploaded_file = SimpleUploadedFile(
            "test_log.txt",
            b"Line 1: Log details here.",
            content_type="text/plain",
        )

        res_upload = requester_client.post(
            f"/api/support/tickets/{key}/attachments",
            {"file": uploaded_file},
            format="multipart",
        )
        assert res_upload.status_code == 201
        att_data = res_upload.json()["data"]
        att_id = att_data["id"]
        assert att_data["filename"] == "test_log.txt"

        # Download attachment
        res_dl = requester_client.get(f"/api/support/attachments/{att_id}/download")
        assert res_dl.status_code == 200
        assert b"Line 1: Log details here." in res_dl.getvalue()

        # Delete attachment
        res_del = requester_client.delete(f"/api/support/tickets/{key}/attachments/{att_id}")
        assert res_del.status_code == 204


@pytest.mark.django_db
class TestAdminAPIEndpoints:
    def test_admin_category_management(self, support_setup, requester_client, admin_client):
        # Requester cannot create category (403)
        res_fail = requester_client.post(
            "/api/support/categories",
            {"name": "Unauthorized Cat"},
            format="json",
        )
        assert res_fail.status_code == 403

        # Admin can create category (201)
        res_create = admin_client.post(
            "/api/support/categories",
            {"name": "RF Equipment", "description": "High-frequency RF analyzers", "sort_order": 10},
            format="json",
        )
        assert res_create.status_code == 201
        cat_id = res_create.json()["data"]["id"]

        # Admin can update category
        res_update = admin_client.patch(
            f"/api/support/categories/{cat_id}",
            {"description": "Updated RF description"},
            format="json",
        )
        assert res_update.status_code == 200
        assert res_update.json()["data"]["description"] == "Updated RF description"

    def test_admin_settings_management(self, support_setup, admin_client):
        res_get = admin_client.get("/api/support/admin/settings")
        assert res_get.status_code == 200
        assert res_get.json()["data"]["reopen_window_days"] == 14

        res_patch = admin_client.patch(
            "/api/support/admin/settings",
            {"reopen_window_days": 21, "comment_edit_window_minutes": 30},
            format="json",
        )
        assert res_patch.status_code == 200
        assert res_patch.json()["data"]["reopen_window_days"] == 21
        assert res_patch.json()["data"]["comment_edit_window_minutes"] == 30
