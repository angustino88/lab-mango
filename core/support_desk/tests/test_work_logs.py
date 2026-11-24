from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.work_log import TicketWorkLog
from tests.factories import UserFactory

TICKETS = "/api/support/tickets"


@pytest.fixture
def create_ticket(support_setup):
    def create(client):
        response = client.post(
            TICKETS,
            {
                "subject": "Calibrate the multimeter",
                "description": "Verify the readings.",
                "category_id": support_setup["category"].id,
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        return f"{TICKETS}/{response.data['data']['key']}"

    return create


@pytest.mark.django_db
def test_work_log_lifecycle(create_ticket, requester_client, requester_user, agent_client):
    ticket = create_ticket(requester_client)
    collection = f"{ticket}/work-logs"
    headers = {"Idempotency-Key": str(uuid4())}
    payload = {"time_spent_minutes": 75, "description": "Calibrated"}
    response = requester_client.post(collection, payload, format="json", headers=headers)
    assert response.status_code == 201, response.data
    entry = response.data["data"]
    url = f"{collection}/{entry['id']}"
    assert response["Location"].endswith(url)
    assert entry["author"]["id"] == requester_user.id
    assert entry["can_manage"] is True
    assert entry["started_at"]
    assert response["ETag"] == entry["etag"]

    replay = requester_client.post(collection, payload, format="json", headers=headers)
    assert replay.status_code == 201
    assert replay["Idempotency-Replayed"] == "true"
    assert replay.data == response.data
    assert (
        requester_client.post(collection, {"time_spent_minutes": 1}, format="json", headers=headers).status_code == 422
    )

    assert agent_client.patch(url, {"description": ""}, format="json").status_code == 428
    response = agent_client.patch(url, {"description": ""}, format="json", headers={"If-Match": entry["etag"]})
    assert response.status_code == 200, response.data
    assert response.data["data"]["description"] == ""
    assert response.data["data"]["time_spent_minutes"] == 75

    edited = response.data["data"]
    noop = agent_client.patch(url, {}, format="json", headers={"If-Match": edited["etag"]})
    assert noop.status_code == 200
    assert noop["ETag"] == edited["etag"]
    assert noop.data["data"]["updated_at"] == edited["updated_at"]

    response = requester_client.get(collection, {"page_size": 1})
    assert response.status_code == 200, response.data
    assert response.data["meta"]["pagination"]["count"] == 1
    assert response.data["data"][0]["id"] == entry["id"]

    assert requester_client.delete(url, headers={"If-Match": entry["etag"]}).status_code == 412
    assert requester_client.delete(url, headers={"If-Match": response.data["data"][0]["etag"]}).status_code == 204
    assert requester_client.get(url).status_code == 404
    events = agent_client.get(f"{ticket}/activity").data["data"]
    assert [e["event_type"]["value"] for e in events][-3:] == ["work_logged", "work_log_updated", "work_log_deleted"]


@pytest.mark.django_db
def test_work_log_access_and_validation(create_ticket, requester_client, agent_client):
    ticket = create_ticket(requester_client)
    collection = f"{ticket}/work-logs"
    headers = {"Idempotency-Key": str(uuid4())}
    stranger = APIClient()
    stranger.force_authenticate(user=UserFactory.create())
    assert stranger.get(collection).status_code == 404
    assert stranger.post(collection, {"time_spent_minutes": 1}, format="json", headers=headers).status_code == 404

    for invalid in (0, 14401, 1.5, True):
        assert (
            requester_client.post(
                collection, {"time_spent_minutes": invalid}, format="json", headers=headers
            ).status_code
            == 422
        )

    response = agent_client.post(collection, {"time_spent_minutes": 1}, format="json", headers=headers)
    assert response.status_code == 201, response.data
    entry = response.data["data"]
    url = f"{collection}/{entry['id']}"
    assert requester_client.get(url).data["data"]["can_manage"] is False
    assert requester_client.patch(url, {"time_spent_minutes": 2}, format="json").status_code == 403
    assert requester_client.delete(url).status_code == 403

    other_ticket = create_ticket(requester_client)
    assert (
        agent_client.post(
            f"{other_ticket}/work-logs", {"time_spent_minutes": 1}, format="json", headers=headers
        ).status_code
        == 422
    )
    wrong_url = f"{other_ticket}/work-logs/{entry['id']}"
    assert agent_client.patch(wrong_url, {"time_spent_minutes": 2}, format="json").status_code == 404
    assert agent_client.delete(wrong_url).status_code == 404


@pytest.mark.django_db
def test_work_log_list_paginates_without_per_row_queries(
    create_ticket, requester_client, requester_user, django_assert_max_num_queries
):
    ticket_path = create_ticket(requester_client)
    ticket = SupportTicket.objects.get(key=ticket_path.rsplit("/", 1)[1])
    entries = TicketWorkLog.objects.bulk_create(
        [TicketWorkLog(ticket=ticket, author=requester_user, time_spent_minutes=i) for i in range(1, 13)]
    )
    collection = f"{ticket_path}/work-logs"

    with django_assert_max_num_queries(5):
        listed = requester_client.get(collection, {"page_size": 10})
    assert listed.status_code == 200
    assert listed.data["meta"]["pagination"]["count"] == 12
    assert [row["id"] for row in listed.data["data"]] == [entry.pk for entry in reversed(entries[2:])]

    remaining = requester_client.get(collection, {"page_size": 10, "page": 2})
    assert [row["id"] for row in remaining.data["data"]] == [entries[1].pk, entries[0].pk]

    with django_assert_max_num_queries(4):
        detail = requester_client.get(f"{collection}/{entries[0].pk}")
    assert detail.status_code == 200
    assert detail.data["data"]["author"]["id"] == requester_user.pk
