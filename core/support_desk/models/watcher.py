"""Ticket watchers (people who follow a ticket without owning it)."""

from django.conf import settings
from django.db import models


class TicketWatcher(models.Model):
    """A user subscribed to notifications for a ticket."""

    ticket = models.ForeignKey(
        "support_desk.SupportTicket",
        on_delete=models.CASCADE,
        related_name="watchers",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="watched_support_tickets",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ticket Watcher"
        verbose_name_plural = "Ticket Watchers"
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["ticket", "user"], name="unique_ticket_watcher"),
        ]
        indexes = [
            models.Index(fields=["user", "ticket"], name="idx_watcher_user_ticket"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} watches {self.ticket_id}"
