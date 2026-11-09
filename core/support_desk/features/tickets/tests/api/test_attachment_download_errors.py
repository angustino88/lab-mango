"""Execute download guards and the global mapper, not mocked domain exceptions.

Only the persistence boundary is substituted with synthetic model instances;
the real permission/policy checks, scan guards and file response execute.
"""

from types import SimpleNamespace
from typing import cast

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.urls import path
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from jsonschema import validate
from rest_framework.test import APIRequestFactory, force_authenticate

from core.support_desk.features.tickets.api.views import TicketAttachmentDownloadAPIView
from core.support_desk.models.attachment import TicketAttachment
from core.support_desk.models.ticket import SupportTicket


@pytest.fixture
def download_schema():
    return SchemaGenerator(
        patterns=[path("attachments/<int:attachment_id>/download", TicketAttachmentDownloadAPIView.as_view())]
    ).get_schema(public=True)


@pytest.fixture
def attachment_boundary(monkeypatch, tmp_path):
    ticket = SupportTicket(pk=1, requester_id=1, created_by_id=1)
    attachment = TicketAttachment(
        pk=7, ticket=ticket, filename="synthetic.txt", content_type="text/plain", scan_status="clean"
    )
    storage = FileSystemStorage(location=tmp_path)
    attachment.file.storage = storage
    attachment.file.name = storage.save("synthetic.txt", ContentFile(b"synthetic download"))
    state = {"attachment": attachment}

    class AttachmentQuery:
        def select_related(self, *fields):
            assert fields == ("ticket",)
            return self

        def filter(self, **filters):
            assert filters == {"pk": 7, "deleted_at__isnull": True}
            return self

        def first(self):
            value = state["attachment"]
            return value if value is not None and value.deleted_at is None else None

    # No policy is replaced: synthetic requester has cached empty Labs roles
    # and no support groups, while the synthetic administrator is a superuser.
    monkeypatch.setattr(TicketAttachment, "objects", AttachmentQuery())
    monkeypatch.setattr(
        "core.support_desk.features.tickets.application.policies.TicketWatcher.objects",
        SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(exists=lambda: False)),
    )
    return state


def call_download(role="requester"):
    request = APIRequestFactory().get("/attachments/7/download")
    if role != "anonymous":
        groups = SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(exists=lambda: False))
        force_authenticate(
            request,
            user=cast(
                AbstractBaseUser,
                SimpleNamespace(
                    pk=1 if role != "other" else 2,
                    is_authenticated=True,
                    is_superuser=role == "admin",
                    _labs_roles_cache=frozenset(),
                    groups=groups,
                ),
            ),
        )
    return async_to_sync(TicketAttachmentDownloadAPIView.as_view())(request, attachment_id=7)


@pytest.mark.parametrize(
    "case,status,code",
    [
        ("missing", 404, "not_found"),
        ("deleted", 404, "not_found"),
        ("other", 404, "not_found"),
        ("restricted", 403, "permission_denied"),
        ("pending", 409, "attachment_scan_pending"),
        ("infected", 422, "attachment_infected"),
        ("empty_file", 404, "not_found"),
        ("missing_binary", 404, "not_found"),
        ("anonymous", 401, "unauthenticated"),
    ],
)
def test_download_documented_errors_execute_actual_guards(attachment_boundary, download_schema, case, status, code):
    attachment = attachment_boundary["attachment"]
    if case == "missing":
        attachment_boundary["attachment"] = None
    elif case == "deleted":
        attachment.deleted_at = timezone.now()
    elif case == "restricted":
        attachment.is_restricted = True
    elif case in {"pending", "infected"}:
        attachment.scan_status = case
    elif case == "empty_file":
        attachment.file.name = ""
    elif case == "missing_binary":
        attachment.file.storage.delete(attachment.file.name)
    response = call_download(case if case in {"other", "anonymous"} else "requester")
    assert response.status_code == status
    assert set(response.data) == {"error"}
    assert response.data["error"]["code"] == code
    operation = download_schema["paths"]["/attachments/{attachment_id}/download"]["get"]
    assert set(operation["responses"]) == {"200", "401", "403", "404", "409", "422"}
    validate(
        response.data,
        {
            **operation["responses"][str(status)]["content"]["application/json"]["schema"],
            "components": download_schema["components"],
        },
    )


@pytest.mark.parametrize("role,restricted", [("requester", False), ("admin", True)])
def test_clean_download_preserves_binary_response(attachment_boundary, download_schema, role, restricted):
    attachment_boundary["attachment"].is_restricted = restricted
    response = call_download(role)
    try:
        assert response.status_code == 200
        assert response["Content-Type"] == "text/plain"
        assert response["Content-Disposition"] == 'attachment; filename="synthetic.txt"'
        assert b"".join(response.streaming_content) == b"synthetic download"
        success = download_schema["paths"]["/attachments/{attachment_id}/download"]["get"]["responses"]["200"]
        assert success["content"]["application/octet-stream"]["schema"] == {"type": "string", "format": "binary"}
    finally:
        response.close()
