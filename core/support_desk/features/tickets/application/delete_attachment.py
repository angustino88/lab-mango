"""Delete attachment command use case."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType
from core.support_desk.exceptions import (
    PermissionDeniedError,
    RecordNotFoundError,
)
from core.support_desk.features.tickets.application.policies import is_support_agent
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.attachment import TicketAttachment


@dataclass(frozen=True, slots=True)
class DeleteAttachmentInput:
    attachment_id: int


def delete_attachment(command: DeleteAttachmentInput, *, actor: Any) -> TicketAttachment:
    """Soft-delete an attachment from a support ticket."""
    attachment = (
        TicketAttachment.objects.select_related("ticket")
        .filter(pk=command.attachment_id, deleted_at__isnull=True)
        .first()
    )
    if not attachment:
        raise RecordNotFoundError(f"Attachment {command.attachment_id} not found.")

    is_uploader = attachment.uploaded_by_id == actor.pk
    if not (is_uploader or is_support_agent(actor)):
        raise PermissionDeniedError("You do not have permission to delete this attachment.")

    with transaction.atomic():
        attachment.deleted_at = timezone.now()
        attachment.save(update_fields=["deleted_at"])

        actor_name = getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "Unknown")
        TicketActivity.objects.create(
            ticket=attachment.ticket,
            event_type=ActivityEventType.ATTACHMENT_REMOVED.value,
            actor=actor,
            actor_name=actor_name,
            payload={
                "attachment_id": attachment.pk,
                "filename": attachment.filename,
            },
        )

    return attachment
