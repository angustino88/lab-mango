"""Bench slot watches: a user asks to be told when a bench frees up inside a time range.

A watch never reserves anything. Notifications are an outbox ledger (one row per event, channel
and watcher) delivered by a background job; booking the freed slot is a normal booking request.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import AbstractOutboxLedger


class SlotWatchStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    CANCELLED = "cancelled", _("Cancelled")
    EXPIRED = "expired", _("Expired")


class SlotWatchKind(models.TextChoices):
    ENDING_SOON = "slot_ending_soon", _("Blocking booking ending soon")
    FREED = "slot_freed", _("Slot freed")


class SlotWatchChannel(models.TextChoices):
    EMAIL = "email", _("Email")
    TEAMS = "teams", _("Teams")
    IN_APP = "in_app", _("Web")


class BenchSlotWatch(TimeStampedModel):
    """One user's request to hear about free time on one bench within [range_start, range_end)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="bench_slot_watches",
        on_delete=models.PROTECT,
    )
    bench = models.ForeignKey("labs.Bench", related_name="slot_watches", on_delete=models.PROTECT)
    range_start = models.DateTimeField()
    range_end = models.DateTimeField()
    notify_email = models.BooleanField(default=True)
    notify_teams = models.BooleanField(default=True)
    notify_web = models.BooleanField(default=True)
    status = models.CharField(
        max_length=16,
        choices=SlotWatchStatus.choices,
        default=SlotWatchStatus.ACTIVE,
    )

    def __str__(self) -> str:
        return f"Slot watch {self.pk}: bench {self.bench_id} {self.range_start:%Y-%m-%d %H:%M}"

    def channels(self) -> tuple[str, ...]:
        wanted = (
            (self.notify_email, SlotWatchChannel.EMAIL),
            (self.notify_teams, SlotWatchChannel.TEAMS),
            (self.notify_web, SlotWatchChannel.IN_APP),
        )
        return tuple(channel.value for enabled, channel in wanted if enabled)

    class Meta:
        app_label = "labs"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(range_end__gt=models.F("range_start")),
                name="slot_watch_range_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(notify_email=True) | models.Q(notify_teams=True) | models.Q(notify_web=True),
                name="slot_watch_has_channel",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=SlotWatchStatus.values),
                name="slot_watch_status_valid",
            ),
            # Race guard for create: a repeated request for the same range returns the existing watch.
            models.UniqueConstraint(
                fields=("user", "bench", "range_start", "range_end"),
                condition=models.Q(status=SlotWatchStatus.ACTIVE),
                name="slot_watch_active_unique",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "range_end"), name="slot_watch_active_idx"),
            models.Index(fields=("user", "status"), name="slot_watch_user_idx"),
        ]


class BenchSlotNotification(AbstractOutboxLedger):
    """Delivery ledger for slot watch events; one row per event, channel and watcher."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bench_slot_notifications",
    )
    watch = models.ForeignKey(BenchSlotWatch, related_name="notifications", on_delete=models.PROTECT)
    # The booking whose end or release opened the slot. Never shown to the watcher.
    booking = models.ForeignKey(
        "labs.BenchBooking",
        related_name="slot_watch_notifications",
        on_delete=models.PROTECT,
    )
    snapshot = models.JSONField()

    class Meta(AbstractOutboxLedger.Meta):
        app_label = "labs"
        indexes = [models.Index(fields=("state", "available_at"), name="slot_notice_ready_idx")]
        constraints = [
            *AbstractOutboxLedger.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(channel__in=SlotWatchChannel.values),
                name="slot_notice_channel",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=SlotWatchKind.values),
                name="slot_notice_kind",
            ),
        ]
