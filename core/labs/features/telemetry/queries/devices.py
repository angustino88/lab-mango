"""Read-only selectors for gateways, sources, channels and per-target overviews.

Cross-owner reads (documented dependency): the installed room/station is derived in SQL through
`TelemetryTarget` foreign keys to rooms, stations and benches, and through the equipment feature's public
`active_bench_assignments` subquery for equipment targets. Lists use annotations and prefetches only, so the
query count does not grow with page size.
"""

from django.db.models import BigIntegerField, CharField, Count, F, Prefetch, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from core.labs.features.equipment.public import active_bench_assignments
from core.labs.features.telemetry.exceptions import TargetNotFound
from core.labs.models import Bench, Equipment, Room, Station
from core.labs.models.telemetry import (
    ChannelTargetBinding,
    GatewayScopeBinding,
    TelemetryChannel,
    TelemetryDevice,
    TelemetryDeviceRole,
    TelemetryDeviceState,
    TelemetryTarget,
)

TARGET_RELATIONS = ("room", "station", "bench", "equipment")
_TARGET_MODELS = {"room": Room, "station": Station, "bench": Bench, "equipment": Equipment}


def _installed_room(prefix: str, field: str) -> Coalesce:
    """`field` of the room the target at `prefix` sits in, whatever the target type."""
    equipment_room = active_bench_assignments(equipment_field=f"{prefix}__equipment_id").values(
        f"bench__station_slot__station__room__{field}"
    )[:1]
    return Coalesce(
        F(f"{prefix}__room__{field}"),
        F(f"{prefix}__station__room__{field}"),
        F(f"{prefix}__bench__station_slot__station__room__{field}"),
        Subquery(equipment_room),
        output_field=CharField() if field == "name" else BigIntegerField(),
    )


def _installed_station_id(prefix: str) -> Coalesce:
    equipment_station = active_bench_assignments(equipment_field=f"{prefix}__equipment_id").values(
        "bench__station_slot__station_id"
    )[:1]
    return Coalesce(
        F(f"{prefix}__station_id"),
        F(f"{prefix}__bench__station_slot__station_id"),
        Subquery(equipment_station),
        output_field=BigIntegerField(),
    )


def _target_related(prefix: str) -> list[str]:
    return [f"{prefix}__{relation}" for relation in TARGET_RELATIONS]


def _open_scopes() -> Prefetch:
    return Prefetch(
        "scope_bindings",
        queryset=GatewayScopeBinding.objects.filter(valid_to__isnull=True).select_related(*_target_related("target")),
        to_attr="open_scopes",
    )


def channel_queryset() -> QuerySet[TelemetryChannel]:
    return (
        TelemetryChannel.objects.select_related(
            "metric", "modbus_settings__profile", "field_device_equipment", "source"
        )
        .prefetch_related(
            Prefetch(
                "target_bindings",
                queryset=ChannelTargetBinding.objects.filter(valid_to__isnull=True).select_related(
                    *_target_related("target")
                ),
                to_attr="open_bindings",
            )
        )
        .order_by("modbus_settings__unit_id", "metric_id", "pk")
    )


def list_devices(
    *, role=None, kind=None, state=None, room_id=None, search=None, include_retired=False
) -> QuerySet[TelemetryDevice]:
    """Gateways and sources with install location, current scope and channel count (bounded by pagination)."""
    queryset = (
        TelemetryDevice.objects.select_related(
            "equipment", "modbus_settings", "reported_by", *_target_related("installed_at")
        )
        .prefetch_related(_open_scopes())
        .annotate(
            installed_room_id=_installed_room("installed_at", "id"),
            installed_room_name=_installed_room("installed_at", "name"),
            installed_station_id=_installed_station_id("installed_at"),
            channel_count=Count("channels", distinct=True),
        )
    )
    if role:
        queryset = queryset.filter(role=role)
    if kind:
        queryset = queryset.filter(kind=kind)
    if state:
        queryset = queryset.filter(state=state)
    elif not include_retired:
        queryset = queryset.exclude(state=TelemetryDeviceState.RETIRED)
    if room_id is not None:
        gateway_rooms = GatewayScopeBinding.objects.filter(valid_to__isnull=True, target__room_id=room_id).values(
            "gateway_id"
        )
        queryset = queryset.filter(Q(installed_room_id=room_id) | Q(pk__in=gateway_rooms))
    if search:
        term = search.strip()
        queryset = queryset.filter(
            Q(device_uid__icontains=term)
            | Q(model__icontains=term)
            | Q(manufacturer__icontains=term)
            | Q(equipment__name__icontains=term)
            | Q(equipment__sku__icontains=term)
            | Q(modbus_settings__network_host__icontains=term)
        )
    return queryset.order_by("role", "state", "pk")


def get_device(*, device_id: int) -> TelemetryDevice:
    return (
        list_devices(include_retired=True)
        .prefetch_related(Prefetch("channels", queryset=channel_queryset(), to_attr="channel_list"))
        .get(pk=device_id)
    )


def list_source_channels(*, source_id: int) -> QuerySet[TelemetryChannel]:
    TelemetryDevice.objects.filter(role=TelemetryDeviceRole.SOURCE).values("pk").get(pk=source_id)
    return channel_queryset().filter(source_id=source_id)


def get_channel(*, channel_id: int) -> TelemetryChannel:
    return channel_queryset().get(pk=channel_id)


def target_overview(*, target_type: str, resource_id: int) -> dict:
    """What is installed at a room/station/bench/equipment item, and which measurements are about it."""
    model = _TARGET_MODELS.get(target_type)
    resource = model.objects.filter(pk=resource_id).first() if model is not None else None
    if resource is None:
        raise TargetNotFound()
    target = TelemetryTarget.objects.filter(**{target_type: resource_id}).first()
    if target is None:
        devices, channels = TelemetryDevice.objects.none(), TelemetryChannel.objects.none()
    else:
        devices = list_devices().filter(installed_at=target)
        channels = channel_queryset().filter(target_bindings__target=target, target_bindings__valid_to__isnull=True)
    return {
        "target": {"type": target_type, "id": resource_id, "name": getattr(resource, "name", "") or str(resource)},
        "installed_devices": list(devices),
        "channels": list(channels),
    }


__all__ = [
    "TARGET_RELATIONS",
    "channel_queryset",
    "get_channel",
    "get_device",
    "list_devices",
    "list_source_channels",
    "target_overview",
]
