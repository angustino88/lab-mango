"""The thing a telemetry reading is about: a room, station, bench or equipment item."""

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel


class TelemetryTargetType(models.TextChoices):
    ROOM = "room", _("Room")
    STATION = "station", _("Station")
    BENCH = "bench", _("Bench")
    EQUIPMENT = "equipment", _("Equipment")


TARGET_FIELDS: tuple[str, ...] = tuple(choice.value for choice in TelemetryTargetType)


def _exactly(target_type: str) -> Q:
    """`target_type` names the one non-null resource foreign key; the other three are null."""
    condition = Q(target_type=target_type)
    for field in TARGET_FIELDS:
        condition &= Q(**{f"{field}__isnull": field != target_type})
    return condition


class TelemetryTarget(TimeStampedModel):
    """One row per measured resource, so readings, bindings and rollups reference a single key.

    Exactly one resource foreign key is set and matches `target_type` (database check). Rows are created
    on first use and never deleted while readings or bindings reference them (`PROTECT`). A new target
    type is one more nullable foreign key plus an extension of `target_type_matches_resource`.
    Owner: telemetry feature.
    """

    target_type = models.CharField(max_length=16, choices=TelemetryTargetType.choices)
    room = models.ForeignKey(
        "labs.Room", on_delete=models.PROTECT, null=True, blank=True, related_name="telemetry_targets"
    )
    station = models.ForeignKey(
        "labs.Station", on_delete=models.PROTECT, null=True, blank=True, related_name="telemetry_targets"
    )
    bench = models.ForeignKey(
        "labs.Bench", on_delete=models.PROTECT, null=True, blank=True, related_name="telemetry_targets"
    )
    equipment = models.ForeignKey(
        "labs.Equipment", on_delete=models.PROTECT, null=True, blank=True, related_name="telemetry_targets"
    )

    class Meta:
        app_label = "labs"
        constraints = [
            models.CheckConstraint(
                condition=_exactly("room") | _exactly("station") | _exactly("bench") | _exactly("equipment"),
                name="telemetry_target_type_matches_resource",
            ),
            models.UniqueConstraint(fields=["room"], name="telemetry_target_room_uniq"),
            models.UniqueConstraint(fields=["station"], name="telemetry_target_station_uniq"),
            models.UniqueConstraint(fields=["bench"], name="telemetry_target_bench_uniq"),
            models.UniqueConstraint(fields=["equipment"], name="telemetry_target_equipment_uniq"),
        ]

    @property
    def resource_id(self) -> int:
        return getattr(self, f"{self.target_type}_id")

    def __str__(self) -> str:
        return f"{self.target_type}:{self.resource_id}"
