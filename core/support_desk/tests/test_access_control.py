"""Access control for Support Desk configuration reads, catalogs, public settings and ticket actions."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from rest_framework_api_key.models import APIKey

from core.support_desk.models.canned_response import CannedResponse
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.team import SupportTeam
from core.support_desk.models.transition import SupportStatusTransition

ADMIN_ONLY_READS = (
    "/api/support/admin/settings",
    "/api/support/admin/transitions",
    "/api/support/admin/canned-responses",
)

PUBLIC_SETTINGS_FIELDS = {
    "requesters_can_set_priority",
    "default_ticket_type",
    "reopen_window_days",
    "comment_edit_window_minutes",
    "max_attachment_size_bytes",
    "allowed_attachment_extensions",
    "max_attachments_per_ticket",
    "csat_enabled",
    "csat_window_days",
}


@pytest.fixture
def anonymous_client():
    return APIClient()


@pytest.fixture
def api_key_client(db):
    _, key = APIKey.objects.create_key(name="support-desk-test")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")
    return client


@pytest.fixture
def inactive_rows(support_setup, agent_user):
    team = SupportTeam.objects.create(name="Field Service", code="field", lead=agent_user, is_active=True)
    team.members.add(agent_user)
    retired_team = SupportTeam.objects.create(name="Retired Team", code="retired", is_active=False)
    return {
        "team": team,
        "category": SupportCategory.objects.create(name="Retired Category", is_active=False, sort_order=9),
        "priority": SupportPriority.objects.create(name="Retired Priority", rank=9, is_active=False),
        "status": SupportStatus.objects.create(
            name="Retired Status", system_state="active", is_active=False, sort_order=9
        ),
        "team_inactive": retired_team,
        "canned": CannedResponse.objects.create(title="Internal template", body="Hi {{requester_name}}"),
    }


def _names(response):
    return {row["name"] for row in response.json()["data"]}


def _create_ticket(client, setup):
    response = client.post(
        "/api/support/tickets",
        {
            "subject": "Scope check",
            "description": "Desc",
            "category_id": setup["category"].id,
            "priority_id": setup["priority_med"].id,
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.json()["data"]


def _transition(client, key, to_status, **extra):
    version = client.get(f"/api/support/tickets/{key}").json()["data"]["version"]
    response = client.post(
        f"/api/support/tickets/{key}/transitions",
        {"to_status_id": to_status.id, "version": version, **extra},
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()["data"]


@pytest.mark.django_db
class TestAdminConfigurationIsAdminOnly:
    @pytest.mark.parametrize("path", ADMIN_ONLY_READS)
    @pytest.mark.parametrize(
        ("caller", "expected"),
        # An API key is not a user identity, so DRF answers 401 rather than 403; both deny the read.
        [("requester_client", 403), ("agent_client", 403), ("api_key_client", 401)],
    )
    def test_non_admin_reads_are_rejected(self, support_setup, inactive_rows, request, caller, expected, path):
        assert request.getfixturevalue(caller).get(path).status_code == expected

    @pytest.mark.parametrize("path", ADMIN_ONLY_READS)
    def test_anonymous_reads_are_rejected(self, support_setup, anonymous_client, path):
        assert anonymous_client.get(path).status_code == 401

    @pytest.mark.parametrize("path", ADMIN_ONLY_READS)
    def test_admin_reads_are_allowed(self, support_setup, inactive_rows, admin_client, path):
        assert admin_client.get(path).status_code == 200

    def test_agents_keep_their_usable_canned_responses(self, support_setup, inactive_rows, agent_client):
        response = agent_client.get("/api/support/canned-responses")
        assert response.status_code == 200
        assert [row["title"] for row in response.json()["data"]] == ["Internal template"]


@pytest.mark.django_db
class TestCatalogReads:
    @pytest.mark.parametrize(
        ("path", "inactive_key"),
        [
            ("/api/support/categories", "category"),
            ("/api/support/priorities", "priority"),
            ("/api/support/statuses", "status"),
            ("/api/support/teams", "team_inactive"),
        ],
    )
    @pytest.mark.parametrize("caller", ["requester_client", "agent_client", "api_key_client"])
    def test_non_admins_see_only_active_rows(self, inactive_rows, request, caller, path, inactive_key):
        response = request.getfixturevalue(caller).get(path)
        assert response.status_code == 200
        names = _names(response)
        assert inactive_rows[inactive_key].name not in names
        assert names, "active rows must still be listed"

    @pytest.mark.parametrize(
        ("path", "inactive_key"),
        [
            ("/api/support/categories", "category"),
            ("/api/support/priorities", "priority"),
            ("/api/support/statuses", "status"),
            ("/api/support/teams", "team_inactive"),
        ],
    )
    def test_admins_also_see_inactive_rows(self, inactive_rows, admin_client, path, inactive_key):
        response = admin_client.get(path)
        assert response.status_code == 200
        assert inactive_rows[inactive_key].name in _names(response)

    def test_anonymous_catalog_read_is_rejected(self, support_setup, anonymous_client):
        assert anonymous_client.get("/api/support/categories").status_code == 401

    @pytest.mark.parametrize(
        ("caller", "expected"), [("requester_client", 403), ("agent_client", 403), ("api_key_client", 401)]
    )
    def test_catalog_writes_stay_admin_only(self, support_setup, request, caller, expected):
        response = request.getfixturevalue(caller).post("/api/support/categories", {"name": "Sneaky"}, format="json")
        assert response.status_code == expected
        assert not SupportCategory.objects.filter(name="Sneaky").exists()

    @pytest.mark.parametrize("caller", ["requester_client", "api_key_client"])
    def test_team_membership_hidden_from_non_agents(self, inactive_rows, request, caller):
        rows = request.getfixturevalue(caller).get("/api/support/teams").json()["data"]
        team = next(row for row in rows if row["code"] == "field")
        assert team["lead"] is None
        assert team["members"] is None

    def test_team_membership_visible_to_agents(self, inactive_rows, agent_client, agent_user):
        rows = agent_client.get("/api/support/teams").json()["data"]
        team = next(row for row in rows if row["code"] == "field")
        assert team["lead"]["id"] == agent_user.id
        assert [member["id"] for member in team["members"]] == [agent_user.id]


@pytest.mark.django_db
class TestPublicSettings:
    @pytest.mark.parametrize("caller", ["requester_client", "agent_client", "admin_client"])
    def test_ticket_users_read_only_client_facing_fields(self, support_setup, request, caller):
        response = request.getfixturevalue(caller).get("/api/support/settings")
        assert response.status_code == 200
        data = response.json()["data"]
        assert set(data) == PUBLIC_SETTINGS_FIELDS
        assert data["reopen_window_days"] == 14

    def test_anonymous_is_rejected(self, support_setup, anonymous_client):
        assert anonymous_client.get("/api/support/settings").status_code == 401

    def test_settings_cannot_be_changed_through_public_endpoint(self, support_setup, admin_client):
        response = admin_client.patch("/api/support/settings", {"reopen_window_days": 1}, format="json")
        assert response.status_code == 405


@pytest.mark.django_db
class TestAvailableTransitions:
    def test_actions_follow_role_and_ticket_state(self, support_setup, requester_client, agent_client):
        setup = support_setup
        ticket = _create_ticket(requester_client, setup)
        key = ticket["key"]

        # Open: only staff may start work.
        assert ticket["available_transitions"] == []
        agent_view = agent_client.get(f"/api/support/tickets/{key}").json()["data"]
        assert [t["to_status"]["id"] for t in agent_view["available_transitions"]] == [setup["status_active"].id]

        _transition(agent_client, key, setup["status_active"])
        resolved = _transition(
            agent_client, key, setup["status_resolved"], resolution_summary="Recalibrated", resolution_code="fixed"
        )
        assert {t["to_status"]["id"] for t in resolved["available_transitions"]} == {
            setup["status_open"].id,
            setup["status_closed"].id,
        }

        # Resolved: the requester may reopen (reason required) but not close.
        requester_view = requester_client.get(f"/api/support/tickets/{key}").json()["data"]
        assert requester_view["available_transitions"] == [
            {
                "id": setup["t_resolved_open"].id,
                "to_status": requester_view["available_transitions"][0]["to_status"],
                "requires_reason": True,
                "requires_resolution": False,
            }
        ]
        assert requester_view["available_transitions"][0]["to_status"]["id"] == setup["status_open"].id

    def test_inactive_target_status_is_not_offered(self, support_setup, requester_client, agent_client):
        setup = support_setup
        key = _create_ticket(requester_client, setup)["key"]
        SupportStatus.objects.filter(pk=setup["status_active"].pk).update(is_active=False)
        agent_view = agent_client.get(f"/api/support/tickets/{key}").json()["data"]
        assert agent_view["available_transitions"] == []

    def test_query_count_does_not_grow_with_transitions(self, support_setup, requester_client, agent_client):
        setup = support_setup
        key = _create_ticket(requester_client, setup)["key"]
        path = f"/api/support/tickets/{key}"
        agent_client.get(path)  # warm caches (settings singleton, content types)

        with CaptureQueriesContext(connection) as one_transition:
            agent_client.get(path)

        for index in range(3):
            extra = SupportStatus.objects.create(
                name=f"Extra {index}", system_state="active", is_active=True, sort_order=10 + index
            )
            SupportStatusTransition.objects.create(
                from_status=setup["status_open"], to_status=extra, allowed_roles=["agent", "admin"]
            )
        with CaptureQueriesContext(connection) as four_transitions:
            response = agent_client.get(path)

        assert len(response.json()["data"]["available_transitions"]) == 4
        assert len(four_transitions) == len(one_transition)
