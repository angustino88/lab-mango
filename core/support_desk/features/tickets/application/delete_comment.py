"""Delete comment command use case."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType
from core.support_desk.exceptions import (
    CommentAuthorMismatchError,
    CommentEditWindowExpiredError,
    RecordNotFoundError,
)
from core.support_desk.features.tickets.application.policies import can_edit_or_delete_comment
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.comment import TicketComment


@dataclass(frozen=True, slots=True)
class DeleteCommentInput:
    comment_id: int


def delete_comment(command: DeleteCommentInput, *, actor: Any) -> TicketComment:
    """Soft-delete an existing ticket comment within the allowed window."""
    comment = TicketComment.objects.select_related("ticket").filter(pk=command.comment_id).first()
    if not comment:
        raise RecordNotFoundError(f"Comment {command.comment_id} not found.")

    if comment.author_id != actor.pk:
        raise CommentAuthorMismatchError("You can only delete comments you authored.")

    if not can_edit_or_delete_comment(actor, comment):
        raise CommentEditWindowExpiredError(
            "The window to delete this comment has expired or it has already been deleted."
        )

    with transaction.atomic():
        comment.deleted_at = timezone.now()
        comment.save(update_fields=["deleted_at"])

        actor_name = getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "Unknown")
        TicketActivity.objects.create(
            ticket=comment.ticket,
            event_type=ActivityEventType.COMMENT_DELETED.value,
            actor=actor,
            actor_name=actor_name,
            payload={
                "comment_id": comment.pk,
                "deleted_body": comment.body,
            },
        )

    return comment
