"""Traceable link between a support ticket and a Lab Mango resource."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from core.support_desk.contracts import RESOURCE_TYPE_CHOICES


class TicketResourceLink(models.Model):
    """Traceable link between a support ticket and a Lab Mango resource."""

    ticket = models.ForeignKey(
        "support_desk.SupportTicket",
        on_delete=models.CASCADE,
        related_name="resource_links",
    )
    resource_type = models.CharField(
        max_length=50,
        choices=RESOURCE_TYPE_CHOICES,
        db_index=True,
    )
    resource_id = models.CharField(max_length=64, db_index=True)
    snapshot = models.JSONField(
        default=dict,
        help_text="Immutable snapshot of resource name, code, parent context at link time.",
    )

    linked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    linked_at = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True, db_index=True)
    unlinked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    unlinked_at = models.DateTimeField(null=True, blank=True)
    unlink_reason = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Ticket Resource Link"
        verbose_name_plural = "Ticket Resource Links"
        ordering = ["-linked_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket", "resource_type", "resource_id"],
                condition=Q(is_active=True),
                name="unique_active_ticket_resource_link",
            )
        ]
        indexes = [
            models.Index(fields=["resource_type", "resource_id", "ticket"], name="idx_res_link_lookup"),
            models.Index(fields=["ticket", "is_active"], name="idx_res_link_ticket_active"),
        ]

    def __str__(self) -> str:
        status_str = "active" if self.is_active else "unlinked"
        return f"{self.ticket.key} -> {self.resource_type}:{self.resource_id} ({status_str})"
