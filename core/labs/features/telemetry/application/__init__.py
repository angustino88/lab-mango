"""Telemetry commands: every configuration write enters here with a frozen input and an actor."""

from .channels import (
    BindChannelTargetInput,
    BindSourceTargetInput,
    CreateChannelsFromProfileInput,
    UnbindChannelInput,
    UpdateChannelInput,
    bind_channel_target,
    bind_source_target,
    create_channels_from_profile,
    unbind_channel,
    update_channel,
)
from .gateways import BindGatewayScopeInput, RegisterGatewayInput, bind_gateway_scope, register_gateway
from .profiles import (
    ApproveDeviceProfileInput,
    CreateDeviceProfileInput,
    approve_device_profile,
    create_device_profile,
)
from .sources import (
    ClaimSourceInput,
    ModbusSettingsInput,
    RegisterSourceInput,
    RetireDeviceInput,
    UpdateSourceInput,
    claim_source,
    register_source,
    retire_device,
    update_source,
)

__all__ = [
    "ApproveDeviceProfileInput",
    "BindChannelTargetInput",
    "BindGatewayScopeInput",
    "BindSourceTargetInput",
    "ClaimSourceInput",
    "CreateChannelsFromProfileInput",
    "CreateDeviceProfileInput",
    "ModbusSettingsInput",
    "RegisterGatewayInput",
    "RegisterSourceInput",
    "RetireDeviceInput",
    "UnbindChannelInput",
    "UpdateChannelInput",
    "UpdateSourceInput",
    "approve_device_profile",
    "bind_channel_target",
    "bind_gateway_scope",
    "bind_source_target",
    "claim_source",
    "create_channels_from_profile",
    "create_device_profile",
    "register_gateway",
    "register_source",
    "retire_device",
    "unbind_channel",
    "update_channel",
    "update_source",
]
