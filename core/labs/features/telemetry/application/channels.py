"""Create channels from a device profile, edit them, and link them to the target they measure.

Race guards: the source (or channel) row is locked before channels or bindings change; one target per channel
at any instant is the exclusion constraint `telemetry_channel_one_target`, and one `(source, unit_id, metric)`
is `telemetry_modbus_channel_uniq`. Idempotency: binding a channel to its current target returns the open
binding; unbinding an unbound channel is a no-op.
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.telemetry.contracts import TargetRef
from core.labs.features.telemetry.exceptions import ChannelAddressInUse, DeviceStateConflict, ProfileNotApproved
from core.labs.models import Equipment
from core.labs.models.telemetry import (
    ChannelTargetBinding,
    DeviceProfile,
    DeviceProfileStatus,
    DeviceProtocol,
    MetricDefinition,
    ModbusChannelSettings,
    TelemetryChannel,
    TelemetryDevice,
    TelemetryDeviceKind,
    TelemetryDeviceRole,
    TelemetryDeviceState,
    TelemetryTarget,
)

from .targets import bump_gateways, constraint_name, ensure_same_room, ensure_target, placement_of, raise_invalid

LABEL_MAX_LENGTH = 120


@dataclass(frozen=True, slots=True)
class CreateChannelsFromProfileInput:
    source_id: int
    unit_id: int
    profile_id: int
    metrics: tuple[str, ...] | None = None
    target: TargetRef | None = None
    label: str = ""
    field_device_equipment_id: int | None = None


@dataclass(frozen=True, slots=True)
class UpdateChannelInput:
    channel_id: int
    label: str | None = None
    is_enabled: bool | None = None
    field_device_equipment_id: int | None = None
    set_field_device: bool = False


@dataclass(frozen=True, slots=True)
class BindChannelTargetInput:
    channel_id: int
    target: TargetRef


@dataclass(frozen=True, slots=True)
class UnbindChannelInput:
    channel_id: int


@dataclass(frozen=True, slots=True)
class BindSourceTargetInput:
    source_id: int
    target: TargetRef


def _claimed_source(source_id: int) -> tuple[TelemetryDevice, TelemetryTarget]:
    """The locked claimed source and its install location (claimed sources always have one: DB check)."""
    source = TelemetryDevice.objects.select_for_update().get(pk=source_id)
    if (
        source.role != TelemetryDeviceRole.SOURCE
        or source.state != TelemetryDeviceState.CLAIMED
        or source.installed_at is None
    ):
        raise DeviceStateConflict("Channels belong to a claimed source.")
    return source, source.installed_at


def _bind(channel: TelemetryChannel, target: TelemetryTarget, *, actor) -> ChannelTargetBinding:
    current = channel.target_bindings.filter(valid_to__isnull=True).first()
    if current is not None and current.target_id == target.pk:
        return current
    now = timezone.now()
    if current is not None:
        current.valid_to = now
        current.save(actor=actor, update_fields=["valid_to", "modified"])
    binding = ChannelTargetBinding(channel=channel, target=target, valid_from=now)
    binding.save(actor=actor)
    return binding


@transaction.atomic
def create_channels_from_profile(command: CreateChannelsFromProfileInput, *, actor) -> list[TelemetryChannel]:
    """One channel per profile metric at a Modbus unit ID, optionally already measuring `target`."""
    source, installed_at = _claimed_source(command.source_id)
    errors: dict[str, str] = {}
    if source.kind != TelemetryDeviceKind.MODBUS_TCP:
        errors["source_id"] = "Profiles at a unit ID apply to Modbus devices."
    if not 1 <= command.unit_id <= 247:
        errors["unit_id"] = "Use a Modbus unit ID between 1 and 247."
    if len(command.label) > LABEL_MAX_LENGTH:
        errors["label"] = f"Use at most {LABEL_MAX_LENGTH} characters."
    if (
        command.field_device_equipment_id is not None
        and not Equipment.objects.filter(pk=command.field_device_equipment_id).exists()
    ):
        errors["field_device_equipment_id"] = "Select an existing equipment item."
    profile = DeviceProfile.objects.filter(pk=command.profile_id).first()
    if profile is None:
        raise_invalid({**errors, "profile_id": "Select an existing device profile."})
    if profile.protocol != DeviceProtocol.MODBUS:
        errors["profile_id"] = "Select a Modbus device profile."
    if errors:
        raise_invalid(errors)
    if profile.status != DeviceProfileStatus.APPROVED:
        raise ProfileNotApproved()
    metrics = list(command.metrics or profile.read_map.keys())
    unknown = sorted(set(metrics) - set(profile.read_map))
    if unknown:
        raise_invalid({"metrics": f"Not in this profile: {', '.join(unknown)}."})
    active = set(MetricDefinition.objects.filter(key__in=metrics, is_active=True).values_list("key", flat=True))
    if missing := sorted(set(metrics) - active):
        raise_invalid({"metrics": f"Unknown or inactive metrics: {', '.join(missing)}."})

    target = ensure_target(command.target) if command.target is not None else None
    measured = ensure_same_room(measured=target, installed=installed_at) if target is not None else None
    channels = []
    try:
        with transaction.atomic():
            for metric in metrics:
                channel = TelemetryChannel(
                    source=source,
                    metric_id=metric,
                    label=command.label.strip(),
                    field_device_equipment_id=command.field_device_equipment_id,
                )
                channel.save(actor=actor)
                ModbusChannelSettings.objects.create(
                    channel=channel, source=source, metric_id=metric, unit_id=command.unit_id, profile=profile
                )
                if target is not None:
                    _bind(channel, target, actor=actor)
                channels.append(channel)
    except IntegrityError as error:
        if constraint_name(error) == "telemetry_modbus_channel_uniq":
            raise ChannelAddressInUse() from error
        raise
    bump_gateways([placement_of(source.installed_at_id), measured])
    return channels


@transaction.atomic
def update_channel(command: UpdateChannelInput, *, actor) -> TelemetryChannel:
    """Rename, enable/disable, or link the physical sensor asset of a channel."""
    channel = TelemetryChannel.objects.select_for_update().select_related("source").get(pk=command.channel_id)
    errors: dict[str, str] = {}
    if command.label is not None:
        if len(command.label) > LABEL_MAX_LENGTH:
            errors["label"] = f"Use at most {LABEL_MAX_LENGTH} characters."
        channel.label = command.label.strip()
    if command.is_enabled is not None:
        channel.is_enabled = command.is_enabled
    if command.set_field_device:
        if (
            command.field_device_equipment_id is not None
            and not Equipment.objects.filter(pk=command.field_device_equipment_id).exists()
        ):
            errors["field_device_equipment_id"] = "Select an existing equipment item."
        channel.field_device_equipment_id = command.field_device_equipment_id
    if errors:
        raise_invalid(errors)
    channel.save(actor=actor)
    bump_gateways([placement_of(channel.source.installed_at_id)])
    return channel


@transaction.atomic
def bind_channel_target(command: BindChannelTargetInput, *, actor) -> ChannelTargetBinding:
    """From now on, readings of this channel are about `target` (in the source's room)."""
    channel = TelemetryChannel.objects.select_for_update().get(pk=command.channel_id)
    source, installed_at = _claimed_source(channel.source_id)
    target = ensure_target(command.target)
    measured = ensure_same_room(measured=target, installed=installed_at)
    binding = _bind(channel, target, actor=actor)
    bump_gateways([placement_of(source.installed_at_id), measured])
    return binding


@transaction.atomic
def unbind_channel(command: UnbindChannelInput, *, actor) -> TelemetryChannel:
    """Stop attributing this channel's readings to anything (sensor removed or not yet placed)."""
    channel = TelemetryChannel.objects.select_for_update().select_related("source").get(pk=command.channel_id)
    current = channel.target_bindings.filter(valid_to__isnull=True).first()
    if current is not None:
        current.valid_to = timezone.now()
        current.save(actor=actor, update_fields=["valid_to", "modified"])
        bump_gateways([placement_of(channel.source.installed_at_id)])
    return channel


@transaction.atomic
def bind_source_target(command: BindSourceTargetInput, *, actor) -> list[ChannelTargetBinding]:
    """Link every channel of a source to one target in one step."""
    source, installed_at = _claimed_source(command.source_id)
    target = ensure_target(command.target)
    measured = ensure_same_room(measured=target, installed=installed_at)
    channels = list(source.channels.select_for_update().order_by("pk"))
    bindings = [_bind(channel, target, actor=actor) for channel in channels]
    bump_gateways([placement_of(source.installed_at_id), measured])
    return bindings


__all__ = [
    "BindChannelTargetInput",
    "BindSourceTargetInput",
    "CreateChannelsFromProfileInput",
    "UnbindChannelInput",
    "UpdateChannelInput",
    "bind_channel_target",
    "bind_source_target",
    "create_channels_from_profile",
    "unbind_channel",
    "update_channel",
]
