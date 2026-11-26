"""Stable business errors of the telemetry feature (codes never change once released)."""

from core.common.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed


class TargetNotFound(NotFound):
    """The named room, station, bench or equipment item does not exist or is deleted."""

    code = "telemetry_target_not_found"
    default_message = "The selected room, station, bench or equipment item does not exist."


class TargetNotLocated(ValidationFailed):
    """The target has no physical placement (bench without station slot, unassigned equipment, roomless station)."""

    code = "telemetry_target_not_located"
    default_message = "This item has no room yet. Place it in a room (through a station or bench) first."


class TargetOutsideInstallRoom(ValidationFailed):
    """A channel may only measure something in the room its source is installed in."""

    code = "telemetry_target_outside_install_room"
    default_message = "A device can only measure things in the room where it is installed."


class GatewayKindMismatch(ValidationFailed):
    """The scope's target type does not fit the gateway kind."""

    code = "telemetry_gateway_scope_type_mismatch"
    default_message = "This gateway kind cannot cover that kind of target."


class RoomGatewayExists(Conflict):
    """Another room gateway already covers this room (constraint `telemetry_scope_one_room_host`)."""

    code = "telemetry_room_gateway_exists"
    default_message = "Another gateway already covers this room. Retire or move it first."


class DeviceAlreadyRegistered(Conflict):
    """The device UID or the equipment asset is already used by another telemetry device."""

    code = "telemetry_device_already_registered"
    default_message = "This device or equipment asset is already registered."


class DeviceStateConflict(Conflict):
    """The device is in a state that does not allow this action (e.g. retired, or not a source)."""

    code = "telemetry_device_state_conflict"
    default_message = "This action is not allowed for the device in its current state."


class ModbusAddressInUse(Conflict):
    """Another source already uses this network address and port (`telemetry_modbus_address_uniq`)."""

    code = "telemetry_modbus_address_in_use"
    default_message = "Another device already uses this IP address and port."


class ChannelAddressInUse(Conflict):
    """The source already reads this metric at this unit ID (`telemetry_modbus_channel_uniq`)."""

    code = "telemetry_channel_address_in_use"
    default_message = "This device already reads that measurement at that Modbus address."


class ChannelsStillBound(Conflict):
    """Moving a source to another room would leave channels measuring targets outside it."""

    code = "telemetry_channels_still_bound"
    default_message = "Some measurements of this device are linked to items in its current room. Unlink them first."


class ProfileNotApproved(ValidationFailed):
    """Channels may only use approved device profiles."""

    code = "telemetry_profile_not_approved"
    default_message = "Only an approved device profile can be used."


class ProfileApprovalForbidden(Forbidden):
    """Only lab admins approve device profiles: an approved profile decides how every reading is decoded."""

    code = "telemetry_profile_approval_forbidden"
    default_message = "Only a lab admin can approve a device profile."


__all__ = [
    "ChannelAddressInUse",
    "ChannelsStillBound",
    "DeviceAlreadyRegistered",
    "DeviceStateConflict",
    "GatewayKindMismatch",
    "ModbusAddressInUse",
    "ProfileApprovalForbidden",
    "ProfileNotApproved",
    "RoomGatewayExists",
    "TargetNotFound",
    "TargetNotLocated",
    "TargetOutsideInstallRoom",
]


class GatewayNotRegistered(Forbidden):
    """The authenticated agent's computer is not a claimed telemetry gateway."""

    code = "telemetry_gateway_not_registered"
    default_message = "This computer is not registered as a telemetry gateway."


class GatewayHasNoScope(Conflict):
    """A gateway may only submit readings while it covers a room, station or equipment item."""

    code = "telemetry_gateway_without_scope"
    default_message = "This gateway has no scope yet. Set the room, station or equipment it covers first."
