"""Multipart upload fields reach validation with their declared types."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.support_desk.models.attachment import TicketAttachment


def _ticket_key(client, support_setup) -> str:
    response = client.post(
        "/api/support/tickets",
        {
            "subject": "Upload fields",
            "description": "Desc",
            "category_id": support_setup["category"].id,
            "priority_id": support_setup["priority_med"].id,
        },
        format="json",
    )
    assert response.status_code == 201
    return response.json()["data"]["key"]


def _upload(client, key: str, **fields):
    return client.post(
        f"/api/support/tickets/{key}/attachments",
        {"file": SimpleUploadedFile("log.txt", b"line", content_type="text/plain"), **fields},
        format="multipart",
    )


@pytest.mark.django_db
def test_reply_attachment_with_comment_id_form_field(support_setup, requester_client):
    key = _ticket_key(requester_client, support_setup)
    comment = requester_client.post(
        f"/api/support/tickets/{key}/comments", {"body": "see log", "visibility": "public"}, format="json"
    )
    assert comment.status_code == 201
    comment_id = comment.json()["data"]["id"]

    response = _upload(requester_client, key, comment_id=str(comment_id))

    assert response.status_code == 201, response.json()
    assert TicketAttachment.objects.get(pk=response.json()["data"]["id"]).comment_id == comment_id


@pytest.mark.django_db
def test_agent_restricts_with_boolean_form_field(support_setup, requester_client, agent_client):
    key = _ticket_key(requester_client, support_setup)

    response = _upload(agent_client, key, is_restricted="true")

    assert response.status_code == 201, response.json()
    assert response.json()["data"]["is_restricted"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("fields", [{"comment_id": "abc"}, {"is_restricted": "maybe"}])
def test_malformed_form_fields_are_still_rejected(support_setup, requester_client, fields):
    key = _ticket_key(requester_client, support_setup)

    response = _upload(requester_client, key, **fields)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == next(iter(fields))
