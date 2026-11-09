"""Support ticket comment model."""

from django.conf import settings
from django.db import models

from core.support_desk.contracts import CommentVisibility
from core.support_desk.exceptions import CommentImmutableVisibilityError


class TicketComment(models.Model):
    """Conversation entry on a support ticket."""

    ticket = models.ForeignKey(
        "support_desk.SupportTicket",
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_comments",
    )
    body = models.TextField()
    visibility = models.CharField(
        max_length=20,
        choices=[(v.value, v.name.title()) for v in CommentVisibility],
        default=CommentVisibility.PUBLIC.value,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Ticket Comment"
        verbose_name_plural = "Ticket Comments"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["ticket", "created_at"], name="idx_comment_ticket_created"),
        ]

    def __str__(self) -> str:
        return f"Comment {self.id} on {self.ticket.key} ({self.visibility})"

    def save(self, *args, **kwargs):
        if self.pk:
            original = TicketComment.objects.filter(pk=self.pk).values("visibility").first()
            if original and original["visibility"] != self.visibility:
                raise CommentImmutableVisibilityError("Comment visibility cannot be modified after creation.")
        super().save(*args, **kwargs)
