"""Update comment command use case."""

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
class UpdateCommentInput:
    comment_id: int
    body: str


def update_comment(command: UpdateCommentInput, *, actor: Any) -> TicketComment:
    """Edit an existing ticket comment within the allowed window."""
    comment = TicketComment.objects.select_related("ticket").filter(pk=command.comment_id).first()
    if not comment:
        raise RecordNotFoundError(f"Comment {command.comment_id} not found.")

    if comment.author_id != actor.pk:
        raise CommentAuthorMismatchError("You can only edit comments you authored.")

    if not can_edit_or_delete_comment(actor, comment):
        raise CommentEditWindowExpiredError(
            "The window to edit this comment has expired or the comment was deleted."
        )

    old_body = comment.body
    with transaction.atomic():
        comment.body = command.body
        comment.edited_at = timezone.now()
        comment.save(update_fields=["body", "edited_at"])

        actor_name = getattr(actor, "get_full_name", lambda: "")() or getattr(actor, "username", "Unknown")
        TicketActivity.objects.create(
            ticket=comment.ticket,
            event_type=ActivityEventType.COMMENT_EDITED.value,
            actor=actor,
            actor_name=actor_name,
            payload={
                "comment_id": comment.pk,
                "old_body": old_body,
                "new_body": comment.body,
            },
        )

    return comment
