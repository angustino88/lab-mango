"""Labs-owned durable delivery ledger; orchestration belongs to bench_bookings."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class BookingNotification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.UUIDField()
    dedupe_key = models.CharField(max_length=64, unique=True)
    booking = models.ForeignKey(
        "labs.BenchBooking",
        on_delete=models.PROTECT,
        related_name="notifications",
        null=True,
        blank=True,
    )
    equipment_booking = models.ForeignKey(
        "labs.EquipmentBooking",
        on_delete=models.PROTECT,
        related_name="notifications",
        null=True,
        blank=True,
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="booking_notifications"
    )
    channel = models.CharField(max_length=8, choices=(("email", "Email"), ("teams", "Teams")))
    kind = models.CharField(max_length=16)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    available_at = models.DateTimeField(default=timezone.now)
    state = models.CharField(max_length=12, default="pending")
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    outcome = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        app_label = "labs"
        indexes = [models.Index(fields=("state", "available_at"), name="booking_notice_ready_idx")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(booking__isnull=False, equipment_booking__isnull=True)
                    | models.Q(booking__isnull=True, equipment_booking__isnull=False)
                ),
                name="booking_notice_one_booking",
            ),
            models.CheckConstraint(condition=models.Q(channel__in=("email", "teams")), name="booking_notice_channel"),
            models.CheckConstraint(
                condition=models.Q(kind__in=("created", "updated", "start", "inactive")), name="booking_notice_kind"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=("pending", "leased", "sent", "failed", "skipped", "expired")),
                name="booking_notice_state",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state="leased", lease_token__isnull=False, lease_until__isnull=False)
                    | (~models.Q(state="leased") & models.Q(lease_token__isnull=True, lease_until__isnull=True))
                ),
                name="booking_notice_lease",
            ),
        ]
