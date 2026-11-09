"""Support ticket status model."""

from django.db import models

from core.support_desk.contracts import SYSTEM_STATE_CHOICES, SystemState


class SupportStatus(models.Model):
    """Admin-configurable status mapped to a fixed system state."""

    name = models.CharField(max_length=50, unique=True)
    system_state = models.CharField(
        max_length=20,
        choices=SYSTEM_STATE_CHOICES,
        default=SystemState.OPEN.value,
        db_index=True,
    )
    color_hex = models.CharField(max_length=7, blank=True, default="", help_text="Optional '#RRGGBB' badge colour.")
    is_initial = models.BooleanField(default=False)
    is_final = models.BooleanField(
        default=False,
        help_text="Terminal status (e.g. Closed). Entering it stamps closed_at; auto-close moves tickets here.",
    )
    pauses_sla = models.BooleanField(
        default=False,
        help_text="While a ticket is in this status (e.g. Waiting for Customer) SLA clocks are paused.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Support Status"
        verbose_name_plural = "Support Statuses"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.system_state})"
