"""Telemetry configuration HTTP mapping only; each handler calls one command or selector.

Access: coordinators and admins (`LAB_OPERATIONS_ACCESS`, inherited); approving a device profile additionally
needs the lab admin role, enforced in the command (`ProfileApprovalForbidden`, 403).
"""

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PAGE_QUERY_PARAMS, PageNumberQuerySerializer, with_page_query
from core.labs.features.base import CommandAPIView, operation
from core.labs.features.telemetry import application as commands
from core.labs.features.telemetry import queries

from .serializers import (
    BindTargetSerializer,
    ChannelSerializer,
    ChannelsFromProfileSerializer,
    ChannelUpdateSerializer,
    DeviceDetailSerializer,
    DeviceListQuerySerializer,
    DeviceProfileCreateSerializer,
    DeviceProfileListQuerySerializer,
    DeviceProfileSerializer,
    DeviceSerializer,
    GatewayCreateSerializer,
    MetricSerializer,
    ScopeBindingSerializer,
    SourceClaimSerializer,
    SourceCreateSerializer,
    SourceUpdateSerializer,
    TargetOverviewSerializer,
    optional_target,
    required_target,
    target_reference,
)


class TelemetryAPIView(AppListAPIView, CommandAPIView):
    schema_tags = ("Telemetry",)

    def filters(self):
        values, error = self.validate_query()
        filters = {key: value for key, value in (values or {}).items() if key not in PAGE_QUERY_PARAMS}
        if "q" in filters:
            filters["search"] = filters.pop("q")
        return filters, error

    def body(self, *, partial: bool = False):
        serializer, error = self.validate_request(partial=partial)
        return (dict(serializer.validated_data) if serializer is not None else {}), error


def _device(device):
    return queries.get_device(device_id=device.pk)


def _modbus(values):
    return commands.ModbusSettingsInput(**values) if values else None


# ---- reference data ----------------------------------------------------------------------------


class MetricListAPIView(TelemetryAPIView):
    get_contract = operation("TelemetryMetricList", MetricSerializer, query=PageNumberQuerySerializer, many=True)

    def handle_get(self, request, **kwargs):
        _, error = self.filters()
        return error or self._execute(queries.list_metrics)


class DeviceProfileListCreateAPIView(TelemetryAPIView):
    get_contract = operation(
        "TelemetryDeviceProfileList",
        DeviceProfileSerializer,
        query=with_page_query(DeviceProfileListQuerySerializer),
        many=True,
    )
    post_contract = operation(
        "TelemetryDeviceProfileCreate", DeviceProfileSerializer, request=DeviceProfileCreateSerializer, created=True
    )

    def handle_get(self, request, **kwargs):
        filters, error = self.filters()
        return error or self._execute(lambda: queries.list_device_profiles(**filters))

    def handle_post(self, request, **kwargs):
        values, error = self.body()
        if error is not None:
            return error
        command = commands.CreateDeviceProfileInput(**values)
        return self._execute(
            lambda: commands.create_device_profile(command, actor=self.acting_user),
            project=lambda profile: queries.get_device_profile(profile_id=profile.pk),
        )


class DeviceProfileDetailAPIView(TelemetryAPIView):
    get_contract = operation("TelemetryDeviceProfileDetail", DeviceProfileSerializer)

    def handle_get(self, request, profile_id, **kwargs):
        return self._execute(lambda: queries.get_device_profile(profile_id=profile_id))


class DeviceProfileApproveAPIView(TelemetryAPIView):
    post_contract = operation("TelemetryDeviceProfileApprove", DeviceProfileSerializer, forbidden=True)

    def handle_post(self, request, profile_id, **kwargs):
        return self._execute(
            lambda: commands.approve_device_profile(
                commands.ApproveDeviceProfileInput(profile_id), actor=self.acting_user
            ),
            project=lambda profile: queries.get_device_profile(profile_id=profile.pk),
        )


# ---- devices -----------------------------------------------------------------------------------


class DeviceListAPIView(TelemetryAPIView):
    get_contract = operation(
        "TelemetryDeviceList", DeviceSerializer, query=with_page_query(DeviceListQuerySerializer), many=True
    )

    def handle_get(self, request, **kwargs):
        filters, error = self.filters()
        return error or self._execute(lambda: queries.list_devices(**filters))


class DeviceDetailAPIView(TelemetryAPIView):
    get_contract = operation("TelemetryDeviceDetail", DeviceDetailSerializer)

    def handle_get(self, request, device_id, **kwargs):
        return self._execute(lambda: queries.get_device(device_id=device_id))


class DeviceClaimAPIView(TelemetryAPIView):
    post_contract = operation("TelemetryDeviceClaim", DeviceDetailSerializer, request=SourceClaimSerializer)

    def handle_post(self, request, device_id, **kwargs):
        values, error = self.body()
        if error is not None:
            return error
        installed_at = required_target(values, "install_location")
        command = commands.ClaimSourceInput(
            device_id=device_id, installed_at=installed_at, **{**values, "modbus": _modbus(values.get("modbus"))}
        )
        return self._execute(lambda: commands.claim_source(command, actor=self.acting_user), project=_device)


class DeviceRetireAPIView(TelemetryAPIView):
    post_contract = operation("TelemetryDeviceRetire", DeviceDetailSerializer)

    def handle_post(self, request, device_id, **kwargs):
        command = commands.RetireDeviceInput(device_id)
        return self._execute(lambda: commands.retire_device(command, actor=self.acting_user), project=_device)


class GatewayCreateAPIView(TelemetryAPIView):
    post_contract = operation(
        "TelemetryGatewayCreate", DeviceDetailSerializer, request=GatewayCreateSerializer, created=True
    )

    def handle_post(self, request, **kwargs):
        values, error = self.body()
        if error is not None:
            return error
        command = commands.RegisterGatewayInput(**values)
        return self._execute(lambda: commands.register_gateway(command, actor=self.acting_user), project=_device)


class GatewayScopeAPIView(TelemetryAPIView):
    post_contract = operation("TelemetryGatewayBindScope", ScopeBindingSerializer, request=BindTargetSerializer)

    def handle_post(self, request, device_id, **kwargs):
        values, error = self.body()
        if error is not None:
            return error
        target = required_target(values, "target")
        command = commands.BindGatewayScopeInput(gateway_id=device_id, target=target)
        return self._execute(
            lambda: commands.bind_gateway_scope(command, actor=self.acting_user),
            project=lambda binding: {
                "gateway_id": binding.gateway_id,
                "target": target_reference(binding.target),
                "started_at": binding.valid_from,
            },
        )


class SourceCreateAPIView(TelemetryAPIView):
    post_contract = operation(
        "TelemetrySourceCreate", DeviceDetailSerializer, request=SourceCreateSerializer, created=True
    )

    def handle_post(self, request, **kwargs):
        values, error = self.body()
        if error is not None:
            return error
        installed_at = required_target(values, "install_location")
        command = commands.RegisterSourceInput(
            installed_at=installed_at, **{**values, "modbus": _modbus(values.get("modbus"))}
        )
        return self._execute(lambda: commands.register_source(command, actor=self.acting_user), project=_device)


class SourceDetailAPIView(TelemetryAPIView):
    patch_contract = operation("TelemetrySourceUpdate", DeviceDetailSerializer, request=SourceUpdateSerializer)

    def handle_patch(self, request, device_id, **kwargs):
        values, error = self.body(partial=True)
        if error is not None:
            return error
        installed_at = optional_target(values, "install_location")
        command = commands.UpdateSourceInput(
            device_id=device_id, installed_at=installed_at, **{**values, "modbus": _modbus(values.get("modbus"))}
        )
        return self._execute(lambda: commands.update_source(command, actor=self.acting_user), project=_device)


class SourceChannelListAPIView(TelemetryAPIView):
    get_contract = operation(
        "TelemetrySourceChannelList", ChannelSerializer, query=PageNumberQuerySerializer, many=True
    )
    post_contract = operation(
        "TelemetrySourceChannelsFromProfile",
        DeviceDetailSerializer,
        request=ChannelsFromProfileSerializer,
        created=True,
    )

    def handle_get(self, request, device_id, **kwargs):
        _, error = self.filters()
        return error or self._execute(lambda: queries.list_source_channels(source_id=device_id))

    def handle_post(self, request, device_id, **kwargs):
        values, error = self.body()
        if error is not None:
            return error
        metrics = values.pop("metrics", None)
        target = optional_target(values, "target")
        command = commands.CreateChannelsFromProfileInput(
            source_id=device_id, metrics=tuple(metrics) if metrics else None, target=target, **values
        )
        return self._execute(
            lambda: commands.create_channels_from_profile(command, actor=self.acting_user),
            project=lambda _: queries.get_device(device_id=device_id),
        )


class SourceBindTargetAPIView(TelemetryAPIView):
    post_contract = operation("TelemetrySourceBindTarget", DeviceDetailSerializer, request=BindTargetSerializer)

    def handle_post(self, request, device_id, **kwargs):
        values, error = self.body()
        if error is not None:
            return error
        target = required_target(values, "target")
        command = commands.BindSourceTargetInput(source_id=device_id, target=target)
        return self._execute(
            lambda: commands.bind_source_target(command, actor=self.acting_user),
            project=lambda _: queries.get_device(device_id=device_id),
        )


# ---- channels ----------------------------------------------------------------------------------


def _channel(channel):
    return queries.get_channel(channel_id=channel.pk)


class ChannelDetailAPIView(TelemetryAPIView):
    get_contract = operation("TelemetryChannelDetail", ChannelSerializer)
    patch_contract = operation("TelemetryChannelUpdate", ChannelSerializer, request=ChannelUpdateSerializer)

    def handle_get(self, request, channel_id, **kwargs):
        return self._execute(lambda: queries.get_channel(channel_id=channel_id))

    def handle_patch(self, request, channel_id, **kwargs):
        values, error = self.body(partial=True)
        if error is not None:
            return error
        command = commands.UpdateChannelInput(
            channel_id=channel_id,
            label=values.get("label"),
            is_enabled=values.get("is_enabled"),
            field_device_equipment_id=values.get("field_device_equipment_id"),
            set_field_device="field_device_equipment_id" in values,
        )
        return self._execute(lambda: commands.update_channel(command, actor=self.acting_user), project=_channel)


class ChannelBindTargetAPIView(TelemetryAPIView):
    post_contract = operation("TelemetryChannelBindTarget", ChannelSerializer, request=BindTargetSerializer)

    def handle_post(self, request, channel_id, **kwargs):
        values, error = self.body()
        if error is not None:
            return error
        target = required_target(values, "target")
        command = commands.BindChannelTargetInput(channel_id=channel_id, target=target)
        return self._execute(
            lambda: commands.bind_channel_target(command, actor=self.acting_user),
            project=lambda _: queries.get_channel(channel_id=channel_id),
        )


class ChannelUnbindAPIView(TelemetryAPIView):
    post_contract = operation("TelemetryChannelUnbind", ChannelSerializer)

    def handle_post(self, request, channel_id, **kwargs):
        command = commands.UnbindChannelInput(channel_id)
        return self._execute(
            lambda: commands.unbind_channel(command, actor=self.acting_user),
            project=lambda _: queries.get_channel(channel_id=channel_id),
        )


# ---- per-target overview -----------------------------------------------------------------------


class TargetOverviewAPIView(TelemetryAPIView):
    get_contract = operation("TelemetryTargetOverview", TargetOverviewSerializer)

    def handle_get(self, request, target_type, resource_id, **kwargs):
        return self._execute(lambda: queries.target_overview(target_type=target_type, resource_id=resource_id))
