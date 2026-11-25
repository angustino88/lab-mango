from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from core.support_desk.contracts import SystemState
from core.support_desk.models.outbox import NotificationOutbox
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.team import SupportTeam
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.transition import SupportStatusTransition
from core.support_desk.models.work_log import TicketWorkLog
from tests.factories import UserFactory

TICKETS = "/api/support/tickets"
WORK_LOGS = "/api/support/work-logs"
PEOPLE = "/api/support/people/options"


def _create_ticket(client, setup, **fields):
    response = client.post(
        TICKETS,
        {
            "subject": "Calibrate the microscope",
            "description": "Calibration",
            "category_id": setup["category"].id,
            **fields,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["data"]


@pytest.mark.django_db
def test_creation_keeps_ownership_and_all_selected_watchers(
    support_setup, agent_client, requester_client, agent_user, requester_user, admin_user
):
    created = _create_ticket(
        agent_client,
        support_setup,
        assignee_id=admin_user.id,
        watcher_ids=[requester_user.id, agent_user.id],
        on_behalf_of_id=requester_user.id,
    )
    detail = agent_client.get(f"{TICKETS}/{created['key']}").data["data"]
    assert detail["assignee"]["id"] == admin_user.id
    assert {watcher["user"]["id"] for watcher in detail["watchers"]} == {requester_user.id, agent_user.id}
    assert detail["is_watching"]
    assert requester_client.get(f"{TICKETS}/{created['key']}").data["data"]["is_watching"]
    assert NotificationOutbox.objects.filter(recipient=admin_user, payload__ticket_key=created["key"]).exists()


@pytest.mark.django_db
def test_people_picker_uses_support_permissions_and_active_assignable_people(
    agent_client, requester_client, admin_user, requester_user
):
    inactive = UserFactory.create(is_active=False)
    ids = f"{admin_user.id},{requester_user.id},{inactive.id}"

    assert requester_client.get(PEOPLE, {"include_ids": ids}).status_code == 403
    allowed = agent_client.get(PEOPLE, {"include_ids": ids})
    assert allowed.status_code == 200, allowed.data
    assert {person["id"] for person in allowed.data["data"]} == {admin_user.id, requester_user.id}
    assert all(set(person) == {"id", "name", "sku"} for person in allowed.data["data"])

    eligible = agent_client.get(PEOPLE, {"include_ids": ids, "is_assignee": "true"})
    assert eligible.status_code == 200, eligible.data
    assert [person["id"] for person in eligible.data["data"]] == [admin_user.id]


@pytest.mark.django_db
def test_create_replay_is_actor_scoped_and_legacy_assignee_cannot_receive_private_ticket(
    support_setup, agent_client, requester_client, requester_user
):
    replay_key = str(uuid4())
    created = _create_ticket(agent_client, support_setup, idempotency_key=replay_key, assignee_id=requester_user.id)
    assert not NotificationOutbox.objects.filter(recipient=requester_user, payload__ticket_key=created["key"]).exists()
    assert _create_ticket(agent_client, support_setup, idempotency_key=replay_key)["key"] == created["key"]
    started = agent_client.post(
        f"{TICKETS}/{created['key']}/actions/transition",
        {"to_status_id": support_setup["status_active"].id, "version": created["version"]},
        format="json",
    )
    assert started.status_code == 200, started.data
    assert not NotificationOutbox.objects.filter(recipient=requester_user, payload__ticket_key=created["key"]).exists()
    collision = requester_client.post(
        TICKETS,
        {
            "subject": "Another request",
            "description": "Details",
            "category_id": support_setup["category"].id,
            "idempotency_key": replay_key,
        },
        format="json",
    )
    assert collision.status_code == 409
    assert collision.data["error"]["code"] == "idempotency_key_conflict"


@pytest.mark.django_db
def test_configured_transitions_and_request_outcome_round_trip(
    support_setup, agent_client, requester_client, requester_user
):
    created = _create_ticket(
        agent_client, support_setup, ticket_type="service_request", on_behalf_of_id=requester_user.id
    )
    url = f"{TICKETS}/{created['key']}"
    custom = SupportStatus.objects.create(name="Lab approval", system_state=SystemState.ACTIVE)
    resolved = support_setup["status_resolved"]
    start = SupportStatusTransition.objects.create(
        from_status_id=created["status"]["id"],
        to_status=custom,
        allowed_roles=["agent"],
        requires_reason=True,
    )
    SupportStatusTransition.objects.create(
        from_status=custom,
        to_status=resolved,
        allowed_roles=["agent"],
        requires_resolution=True,
    )
    inactive = SupportStatus.objects.create(name="Disabled destination", is_active=False)
    SupportStatusTransition.objects.create(
        from_status_id=created["status"]["id"],
        to_status=inactive,
        allowed_roles=["agent"],
    )
    direct_reopen = SupportStatusTransition.objects.create(
        from_status=resolved,
        to_status=custom,
        allowed_roles=["requester"],
        requires_reason=False,
    )

    offered = agent_client.get(url).data["data"]["available_transitions"]
    assert {item["status"]["name"] for item in offered} == {"In Progress", "Lab approval"}
    assert next(item for item in offered if item["id"] == start.id)["is_reason_required"]
    assert requester_client.get(url).data["data"]["available_transitions"] == []
    started = agent_client.post(
        f"{url}/actions/transition",
        {"to_status_id": custom.id, "version": created["version"], "reason": "Review"},
        format="json",
    )
    assert started.status_code == 200, started.data
    completed = agent_client.post(
        f"{url}/actions/transition",
        {
            "to_status_id": resolved.id,
            "version": started.data["data"]["version"],
            "resolution_code": "fulfilled",
            "resolution_summary": "Microscope access provisioned.",
        },
        format="json",
    )
    assert completed.status_code == 200, completed.data
    assert completed.data["data"]["resolution_code"] == "fulfilled"
    available = requester_client.get(url).data["data"]["available_transitions"]
    reopening = next(item for item in available if item["id"] == direct_reopen.id)
    assert reopening["is_reopen"] and reopening["is_reason_required"]

    ticket = SupportTicket.objects.get(key=created["key"])
    expired_at = timezone.now() - timedelta(days=SupportSettings.get_solo().reopen_window_days + 1)
    SupportTicket.objects.filter(pk=ticket.pk).update(resolved_at=expired_at)
    assert requester_client.get(url).data["data"]["available_transitions"] == []
    denied = requester_client.post(
        f"{url}/actions/transition",
        {"to_status_id": custom.id, "version": ticket.version, "reason": "Follow-up"},
        format="json",
    )
    assert denied.status_code == 422

    SupportTicket.objects.filter(pk=ticket.pk).update(resolved_at=timezone.now(), root_cause="Completed review")
    reopened = requester_client.post(
        f"{url}/actions/transition",
        {"to_status_id": custom.id, "version": ticket.version, "reason": "Follow-up"},
        format="json",
    )
    assert reopened.status_code == 200, reopened.data
    assert all(reopened.data["data"][field] == "" for field in ("resolution_code", "resolution_summary", "root_cause"))
    activity = reopened.data["data"]["activities"][-1]["payload"]
    assert activity["previous_resolution_code"] == "fulfilled"
    assert activity["previous_resolution_summary"] == "Microscope access provisioned."
    assert activity["previous_root_cause"] == "Completed review"


@pytest.mark.django_db
def test_work_log_reports_respect_scope_and_aggregate_all_filtered_entries(
    support_setup, agent_client, requester_client, agent_user, requester_user, django_assert_max_num_queries
):
    team = SupportTeam.objects.create(name="Calibration", code="calibration")
    other_team = SupportTeam.objects.create(name="Facilities", code="facilities")
    visible = _create_ticket(agent_client, support_setup, on_behalf_of_id=requester_user.id, team_id=team.id)
    private = _create_ticket(agent_client, support_setup, team_id=other_team.id)
    now = timezone.now()
    old = now - timedelta(days=3)
    for created, author, minutes, started_at in (
        (visible, requester_user, 35, now),
        (visible, requester_user, 15, now),
        (visible, agent_user, 75, now),
        (visible, agent_user, 900, old),
        (private, agent_user, 100, now),
        (private, requester_user, 800, now),
    ):
        TicketWorkLog.objects.create(
            ticket_id=created["id"], author=author, time_spent_minutes=minutes, started_at=started_at
        )

    personal = requester_client.get(f"{WORK_LOGS}/summary")
    assert personal.status_code == 200
    assert personal.data["data"]["total_minutes"] == 50
    for path in (WORK_LOGS, f"{WORK_LOGS}/summary", f"{WORK_LOGS}/contributors"):
        assert requester_client.get(path, {"scope": "team"}).status_code == 403
        assert requester_client.get(path, {"scope": "ticket", "ticket_key": private["key"]}).status_code == 404
    ticket_summary = requester_client.get(f"{WORK_LOGS}/summary", {"scope": "ticket", "ticket_key": visible["key"]})
    assert ticket_summary.data["data"]["total_minutes"] == 1025
    assert ticket_summary.data["data"]["my_minutes"] == 50

    team_filters = {
        "scope": "team",
        "team_id": team.id,
        "started_after": now.isoformat(),
        "started_before": (now + timedelta(days=1)).isoformat(),
    }
    summary = agent_client.get(f"{WORK_LOGS}/summary", team_filters)
    assert summary.data["data"] == {
        "total_minutes": 125,
        "my_minutes": 75,
        "entry_count": 3,
        "ticket_count": 1,
        "contributor_count": 2,
    }
    with django_assert_max_num_queries(6):
        entries = agent_client.get(WORK_LOGS, {**team_filters, "page_size": 1})
    assert entries.data["meta"]["pagination"]["count"] == 3
    assert entries.data["data"][0]["ticket"]["key"] == visible["key"]

    with django_assert_max_num_queries(6):
        rollup = agent_client.get(f"{WORK_LOGS}/contributors", {**team_filters, "page_size": 1})
    assert rollup.data["meta"]["pagination"]["count"] == 2
    assert rollup.data["data"][0]["total_minutes"] == 75
    filtered = agent_client.get(f"{WORK_LOGS}/summary", {**team_filters, "author_id": requester_user.id})
    assert filtered.data["data"]["total_minutes"] == 50
