from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.base import AgentReportedModel


class SessionAccessType(models.TextChoices):
    """How the user got access to the computer for one session (owner decision O22)."""

    BOOKED = "booked", _("Booked")
    AD_HOC = "ad_hoc", _("Ad hoc (no booking)")
    UNVERIFIED_BOOKING = "unverified_booking", _("Booking not verified")


class LabSessionLog(AgentReportedModel, TimeStampedModel, UserStampedModel):
    """Immutable history of completed remote computing sessions.

    The pushed values are final. ``access_type``, ``booking``, ``bench`` and ``user`` are derived
    from them and master data when the session is stored, and may be recomputed.
    """

    login_time = models.DateTimeField(null=True, blank=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    computing_equipment = models.ForeignKey(
        "labs.Equipment",
        related_name="session_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    host_name = models.CharField(max_length=255, null=True, blank=True)
    remote_host = models.CharField(max_length=255, null=True, blank=True)
    remote_user = models.CharField(max_length=255, null=True, blank=True)
    remote_user_display_name = models.CharField(max_length=255, null=True, blank=True)
    remote_ip = models.GenericIPAddressField(null=True, blank=True)
    booking_code = models.CharField(max_length=255, null=True, blank=True)
    active_duration_seconds = models.FloatField(null=True, blank=True)
    access_type = models.CharField(
        max_length=32,
        choices=SessionAccessType.choices,
        null=True,
        blank=True,
        help_text=_("How the user got access. Null only on rows stored before access types existed."),
    )
    booking = models.ForeignKey(
        "labs.BenchBooking",
        related_name="session_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The verified booking; set only when the access type is booked."),
    )
    bench = models.ForeignKey(
        "labs.Bench",
        related_name="session_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The bench the computer was placed on at login time."),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="lab_session_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("The app user whose username matches the remote login name."),
    )

    @property
    def duration(self) -> timedelta | None:
        if self.login_time is None or self.logout_time is None:
            return None
        return self.logout_time - self.login_time

    @property
    def duration_minutes(self) -> float | None:
        if self.active_duration_seconds is not None:
            return self.active_duration_seconds / 60

        duration = self.duration
        return duration.total_seconds() / 60 if duration is not None else None

    def clean(self) -> None:
        super().clean()
        errors: dict[str, ValidationError] = {}

        if self.login_time is not None and self.logout_time is not None:
            if self.logout_time <= self.login_time:
                errors["logout_time"] = ValidationError(
                    _("Logout time must be later than login time."),
                    code="invalid_session_period",
                )
            elif (
                self.active_duration_seconds is not None
                and self.active_duration_seconds > (self.duration.total_seconds())
            ):
                errors["active_duration_seconds"] = ValidationError(
                    _("Active duration cannot exceed the session duration."),
                    code="active_duration_exceeds_session",
                )

        if self.active_duration_seconds is not None and self.active_duration_seconds < 0:
            errors["active_duration_seconds"] = ValidationError(
                _("Active duration cannot be negative."),
                code="negative_active_duration",
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args: Any, **kwargs: Any) -> None:
        for field_name in (
            "remote_ip",
            "host_name",
            "remote_host",
            "remote_user",
            "remote_user_display_name",
            "booking_code",
        ):
            value = getattr(self, field_name)
            if isinstance(value, str):
                setattr(self, field_name, value.strip() or None)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        identity = self.remote_user or "unknown user"
        machine = self.host_name or self.remote_host or "unknown host"
        return f"{identity} on {machine} at {self.login_time}"

    class Meta:
        app_label = "labs"
        ordering = ("-login_time", "-created")
        verbose_name = _("Lab session log")
        verbose_name_plural = _("Lab session logs")
        constraints = [
            models.UniqueConstraint(
                fields=("computing_equipment", "agent_id", "event_id"),
                name="unique_session_report_per_agent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(login_time__isnull=True)
                    | models.Q(logout_time__isnull=True)
                    | models.Q(logout_time__gt=models.F("login_time"))
                ),
                name="labsess_valid_period",
            ),
            models.CheckConstraint(
                condition=models.Q(active_duration_seconds__isnull=True)
                | models.Q(active_duration_seconds__gte=0),
                name="labsess_active_duration_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(access_type__isnull=True)
                    | models.Q(access_type=SessionAccessType.AD_HOC, booking_code__isnull=True)
                    | models.Q(
                        access_type__in=(SessionAccessType.BOOKED, SessionAccessType.UNVERIFIED_BOOKING),
                        booking_code__isnull=False,
                    )
                ),
                name="labsess_access_type_matches_code",
            ),
            models.CheckConstraint(
                # access_type IS NOT NULL is explicit: a comparison with NULL is unknown, and a CHECK
                # constraint passes on unknown, which would let an unclassified row link a booking.
                condition=models.Q(booking__isnull=True)
                | models.Q(access_type__isnull=False, access_type=SessionAccessType.BOOKED),
                name="labsess_booking_only_when_booked",
            ),
        ]
        indexes = [
            models.Index(
                fields=["computing_equipment", "login_time"],
                name="session_equipment_login_idx",
            ),
            models.Index(fields=["remote_user", "login_time"], name="session_remote_user_login_idx"),
            models.Index(fields=["booking_code"], name="session_booking_code_idx"),
            models.Index(fields=["host_name", "login_time"], name="session_host_login_idx"),
            models.Index(fields=["bench", "login_time"], name="session_bench_login_idx"),
            models.Index(fields=["user", "login_time"], name="session_user_login_idx"),
            models.Index(fields=["access_type", "login_time"], name="session_access_login_idx"),
        ]
