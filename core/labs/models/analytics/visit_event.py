"""Event-level analytics for laboratory access and usage."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import AnalyticsEvent


class LaboratoryVisitEvent(AnalyticsEvent):
    """One append-only laboratory visit attributed to a user.

    The visitor relation intentionally uses ``SET_NULL`` so historic event
    counts remain valid after account retention or removal workflows. The
    facility identifier is an external operational key until a stable lab
    aggregate is available in this application.
    """

    visitor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="laboratory_visit_events",
    )
    facility_identifier = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Stable identifier supplied by the laboratory access system."),
    )

    class Meta(AnalyticsEvent.Meta):
        indexes = [
            models.Index(fields=("visitor", "occurred_at"), name="lab_visit_visitor_at_idx"),
            models.Index(fields=("facility_identifier", "occurred_at"), name="lab_visit_facility_at_idx"),
        ]

    def __str__(self) -> str:
        return f"Visit {self.pk} at {self.occurred_at:%Y-%m-%d %H:%M}"
