"""Directional links between tickets (blocks / duplicates / relates to / caused by)."""

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from core.support_desk.contracts import LINK_TYPE_CHOICES


class TicketLink(models.Model):
    """``source`` <link_type> ``target`` (e.g. SUP-12 *blocks* SUP-15)."""

    source = models.ForeignKey(
        "support_desk.SupportTicket",
        on_delete=models.CASCADE,
        related_name="outgoing_links",
    )
    target = models.ForeignKey(
        "support_desk.SupportTicket",
        on_delete=models.CASCADE,
        related_name="incoming_links",
    )
    link_type = models.CharField(max_length=20, choices=LINK_TYPE_CHOICES)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ticket Link"
        verbose_name_plural = "Ticket Links"
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["source", "target", "link_type"], name="unique_ticket_link"),
            models.CheckConstraint(condition=~Q(source=F("target")), name="ticket_link_no_self_reference"),
        ]
        indexes = [
            models.Index(fields=["target", "link_type"], name="idx_ticket_link_target"),
        ]

    def __str__(self) -> str:
        return f"{self.source_id} {self.link_type} {self.target_id}"
