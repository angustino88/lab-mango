"""Time-bounded bindings: a gateway's scope, and the target each channel measures."""

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Q
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.booking.base import TsTzRange

from .channel import TelemetryChannel
from .device import GATEWAY_KINDS, TelemetryDevice, TelemetryDeviceKind
from .target import TelemetryTarget


def _no_overlap(*, name: str, field: str, condition: Q | None = None) -> ExclusionConstraint:
    """`field` has at most one binding covering any instant; needs `btree_gist` (installed)."""
    return ExclusionConstraint(
        name=name,
        expressions=[
            (field, RangeOperators.EQUAL),
            (TsTzRange("valid_from", "valid_to", RangeBoundary()), RangeOperators.OVERLAPS),
        ],
        condition=condition,
    )


class GatewayScopeBinding(TimeStampedModel, UserStampedModel):
    """Which target (room, station or equipment) a gateway covers, over a half-open time range.

    One scope per gateway at a time, and one room gateway per room at a time (exclusion constraints).
    `gateway_kind` copies the gateway's kind so the per-room rule is a database guard. Application rule:
    the scope's target type fits the kind. Kept as history (`PROTECT`). Owner: telemetry feature.
    """

    gateway = models.ForeignKey(TelemetryDevice, on_delete=models.PROTECT, related_name="scope_bindings")
    gateway_kind = models.CharField(max_length=32, choices=[(kind.value, kind.label) for kind in GATEWAY_KINDS])
    target = models.ForeignKey(TelemetryTarget, on_delete=models.PROTECT, related_name="gateway_scope_bindings")
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "labs"
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")),
                name="telemetry_scope_valid_range",
            ),
            models.CheckConstraint(
                condition=Q(gateway_kind__in=GATEWAY_KINDS), name="telemetry_scope_gateway_kind_valid"
            ),
            _no_overlap(name="telemetry_scope_one_per_gateway", field="gateway"),
            _no_overlap(
                name="telemetry_scope_one_room_host",
                field="target",
                condition=Q(gateway_kind=TelemetryDeviceKind.ROOM_HOST),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.gateway_id} → {self.target_id}"


class ChannelTargetBinding(TimeStampedModel, UserStampedModel):
    """What a channel measures over a half-open time range.

    A channel measures one target at a time (exclusion constraint); a target may have many channels.
    Readings resolve their target from the binding covering `observed_at`. Kept as history (`PROTECT`).
    Owner: telemetry feature.
    """

    channel = models.ForeignKey(TelemetryChannel, on_delete=models.PROTECT, related_name="target_bindings")
    target = models.ForeignKey(TelemetryTarget, on_delete=models.PROTECT, related_name="channel_bindings")
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "labs"
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gt=F("valid_from")),
                name="telemetry_channel_bind_valid_range",
            ),
            _no_overlap(name="telemetry_channel_one_target", field="channel"),
        ]
        indexes = [
            models.Index(
                fields=["target"],
                condition=Q(valid_to__isnull=True),
                name="telemetry_bind_target_open_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.channel_id} → {self.target_id}"
