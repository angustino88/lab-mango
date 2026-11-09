"""Support status transition model."""

from django.db import models


class SupportStatusTransition(models.Model):
    """Allowed transition between two support statuses."""

    from_status = models.ForeignKey(
        "support_desk.SupportStatus",
        on_delete=models.PROTECT,
        related_name="outgoing_transitions",
    )
    to_status = models.ForeignKey(
        "support_desk.SupportStatus",
        on_delete=models.PROTECT,
        related_name="incoming_transitions",
    )
    allowed_roles = models.JSONField(
        default=list,
        help_text="List of roles allowed to trigger this transition, e.g. ['agent', 'admin'].",
    )
    requires_reason = models.BooleanField(
        default=False,
        help_text="Whether this transition requires a reason from the actor.",
    )
    requires_resolution = models.BooleanField(
        default=False,
        help_text="Whether this transition requires a resolution summary.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Support Status Transition"
        verbose_name_plural = "Support Status Transitions"
        ordering = ["from_status__sort_order", "to_status__sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_status", "to_status"],
                name="unique_support_status_transition",
            )
        ]

    def __str__(self) -> str:
        return f"{self.from_status.name} -> {self.to_status.name}"
