"""Append-only audit activity log for support tickets."""

from django.conf import settings
from django.db import models

from core.support_desk.contracts import ActivityEventType
from core.support_desk.exceptions import ImmutableActivityError


class TicketActivity(models.Model):
    """Immutable audit trail for state changes and events on a ticket."""

    ticket = models.ForeignKey(
        "support_desk.SupportTicket",
        on_delete=models.CASCADE,
        related_name="activities",
    )
    event_type = models.CharField(
        max_length=64,
        choices=ActivityEventType.choices(),
        db_index=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    actor_name = models.CharField(max_length=255)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    payload = models.JSONField(default=dict)
    correlation_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        verbose_name = "Ticket Activity"
        verbose_name_plural = "Ticket Activities"
        ordering = ["occurred_at", "id"]
        indexes = [
            models.Index(fields=["ticket", "occurred_at"], name="idx_activity_ticket_occurred"),
        ]

    def __str__(self) -> str:
        return f"{self.ticket.key} - {self.event_type} by {self.actor_name} at {self.occurred_at}"

    #: System-generated events that must not count as "activity" for staleness / sorting purposes.
    PASSIVE_EVENTS = frozenset(
        {
            ActivityEventType.SLA_BREACHED.value,
            ActivityEventType.SLA_PAUSED.value,
            ActivityEventType.SLA_RESUMED.value,
        }
    )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ImmutableActivityError("Ticket activity logs are immutable and cannot be edited.")
        super().save(*args, **kwargs)
        if self.event_type not in self.PASSIVE_EVENTS:
            # Cheap UPDATE: no version bump, so it never causes optimistic-lock conflicts.
            self._meta.get_field("ticket").related_model.objects.filter(pk=self.ticket_id).update(last_activity_at=self.occurred_at)

    def delete(self, *args, **kwargs):
        raise ImmutableActivityError("Ticket activity logs cannot be deleted.")
