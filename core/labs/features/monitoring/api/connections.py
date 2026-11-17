"""Device connection and expected-device endpoints under the Labs staff access policy."""

from datetime import timezone as datetime_timezone

from django.utils.cache import patch_vary_headers
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.summary_serializers import choice_field
from core.common.domain.errors import BadRequest
from core.labs.features.base import CommandAPIView, operation
from core.labs.features.base.serializers import NamedReferenceSerializer, UIDNamedReferenceSerializer
from core.labs.features.monitoring.application.manage import (
    CreateExpectedDeviceInput,
    LinkDeviceConnectionInput,
    UpdateExpectedDeviceInput,
    create_expected_device,
    delete_expected_device,
    link_device_connection,
    update_expected_device,
)
from core.labs.features.monitoring.queries.connections import (
    device_connection_history,
    device_connection_summary,
    get_device_connection,
    list_device_connections,
)
from core.labs.features.monitoring.queries.expected import get_expected_device, list_expected_devices
from core.labs.models.monitoring import DeviceConnectionState, DeviceMatchStatus

FRESHNESS_CHOICES = (("fresh", "Fresh"), ("stale", "Stale"), ("unknown", "Unknown"))
PRESENCE_CHOICES = (("present", "Present"), ("missing", "Missing"), ("unconfirmed", "Unconfirmed"))


def _utc_datetime(**kwargs) -> serializers.DateTimeField:
    return serializers.DateTimeField(
        default_timezone=datetime_timezone.utc, format="%Y-%m-%dT%H:%M:%S.%fZ", read_only=True, **kwargs
    )


@extend_schema_field(NamedReferenceSerializer(allow_null=True))
class BenchReferenceField(serializers.Field):
    """The computing unit's current bench as ``{id, name}``, from the query's annotations."""

    def __init__(self, **kwargs):
        kwargs.setdefault("read_only", True)
        kwargs.setdefault("source", "*")
        super().__init__(**kwargs)

    def to_representation(self, value):
        bench_id = getattr(value, "bench_id", None)
        return None if bench_id is None else {"id": bench_id, "name": getattr(value, "bench_name", "") or ""}


class DeviceConnectionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    computing = UIDNamedReferenceSerializer()
    bench = BenchReferenceField()
    equipment = UIDNamedReferenceSerializer(allow_null=True)
    interface = NamedReferenceSerializer(allow_null=True)
    interface_name = serializers.CharField()
    collector_key = serializers.CharField()
    observation_key = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    serial_number = serializers.CharField(allow_blank=True)
    state = choice_field(DeviceConnectionState.choices)
    match_status = choice_field(DeviceMatchStatus.choices)
    freshness = choice_field(FRESHNESS_CHOICES)
    is_attention_required = serializers.BooleanField(source="needs_attention")
    expected_device_id = serializers.IntegerField(allow_null=True)
    observed_at = _utc_datetime()
    received_at = _utc_datetime()


class DeviceConnectionChangeSerializer(serializers.Serializer):
    state = choice_field(DeviceConnectionState.choices)
    observed_at = _utc_datetime()
    sequence = serializers.IntegerField()
    is_complete = serializers.BooleanField()


class DeviceConnectionDetailSerializer(DeviceConnectionSerializer):
    first_seen_at = _utc_datetime()
    history = DeviceConnectionChangeSerializer(many=True, source="history_changes")


class DeviceConnectionSummarySerializer(serializers.Serializer):
    connected = serializers.IntegerField()
    needs_matching = serializers.IntegerField()
    unconfirmed = serializers.IntegerField()
    missing = serializers.IntegerField()
    computing_units = serializers.IntegerField()


class DeviceConnectionQuerySerializer(PageNumberQuerySerializer):
    computing_id = serializers.IntegerField(min_value=1, required=False)
    bench_id = serializers.IntegerField(min_value=1, required=False)
    state = serializers.ChoiceField(choices=DeviceConnectionState.choices, required=False)
    # HTML-style query parsing turns a missing boolean into False; default None keeps "not given".
    is_attention_required = serializers.BooleanField(required=False, allow_null=True, default=None)
    q = serializers.CharField(required=False, max_length=100, trim_whitespace=True)


class BenchScopeQuerySerializer(serializers.Serializer):
    bench_id = serializers.IntegerField(min_value=1, required=False)


class LinkDeviceConnectionRequestSerializer(serializers.Serializer):
    equipment_id = serializers.IntegerField(min_value=1)


class ExpectedDeviceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    computing = UIDNamedReferenceSerializer()
    bench = BenchReferenceField()
    equipment = UIDNamedReferenceSerializer()
    presence = choice_field(PRESENCE_CHOICES)
    last_seen_at = _utc_datetime(allow_null=True)
    is_disconnect_alert_enabled = serializers.BooleanField(source="notify_on_disconnect")
    created_at = _utc_datetime(source="created")


class ExpectedDeviceQuerySerializer(PageNumberQuerySerializer):
    computing_id = serializers.IntegerField(min_value=1, required=False)
    bench_id = serializers.IntegerField(min_value=1, required=False)
    presence = serializers.ChoiceField(choices=PRESENCE_CHOICES, required=False)


class CreateExpectedDeviceRequestSerializer(serializers.Serializer):
    computing_id = serializers.IntegerField(min_value=1)
    equipment_id = serializers.IntegerField(min_value=1)
    is_disconnect_alert_enabled = serializers.BooleanField(
        source="notify_on_disconnect", required=False, default=False
    )


class UpdateExpectedDeviceRequestSerializer(serializers.Serializer):
    is_disconnect_alert_enabled = serializers.BooleanField(source="notify_on_disconnect")


class _MonitoringAPIView(CommandAPIView):
    # Monitoring reads change every few seconds and are per-user; never share a cached copy.

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = (
            "no-store" if request.method != "GET" or response.status_code >= 400 else "private, no-cache"
        )
        patch_vary_headers(response, ("Accept", "Accept-Language"))
        return response


def _optional(params, *names):
    return {name: params[name] for name in names if params.get(name) not in (None, "")}


class DeviceConnectionListAPIView(AppListAPIView, _MonitoringAPIView):
    """List observed devices lab-wide or for one computing unit, connected first."""

    schema_tags = ("Monitoring",)
    get_contract = OperationContract(
        query=DeviceConnectionQuerySerializer,
        success=ResponseContract.paginated("DeviceConnectionList", DeviceConnectionSerializer),
        bad_request=ResponseContract.problem(400),
    )

    def handle_get(self, request):
        if request._request.read(1):
            raise BadRequest("GET does not accept a body.", code="unexpected_body")
        params, error = self.validate_query()
        if error is not None:
            return error
        assert params is not None
        filters = _optional(params, "computing_id", "bench_id", "state")
        if params.get("q"):
            filters["search"] = params["q"]
        if params.get("is_attention_required") is not None:
            filters["attention"] = params["is_attention_required"]
        return self._execute(lambda: list_device_connections(**filters))


class DeviceConnectionSummaryAPIView(_MonitoringAPIView):
    """Count connected, unmatched, unconfirmed and expected-but-missing devices."""

    schema_tags = ("Monitoring",)
    get_contract = OperationContract(
        query=BenchScopeQuerySerializer,
        success=ResponseContract.success("DeviceConnectionSummary", DeviceConnectionSummarySerializer),
        bad_request=ResponseContract.problem(400),
    )

    def handle_get(self, request):
        params, error = self.validate_query()
        if error is not None:
            return error
        assert params is not None
        return self._execute(lambda: device_connection_summary(**_optional(params, "bench_id")))


class DeviceConnectionDetailAPIView(_MonitoringAPIView):
    """Read one observed device with its recent connection history."""

    schema_tags = ("Monitoring",)
    get_contract = operation("DeviceConnectionDetail", DeviceConnectionDetailSerializer)

    def handle_get(self, request, connection_id, **kwargs):
        def read():
            connection = get_device_connection(connection_id=connection_id)
            # Read by DeviceConnectionDetailSerializer.history (source="history_changes").
            setattr(connection, "history_changes", device_connection_history(connection))
            return connection

        return self._execute(read)


class DeviceConnectionLinkActionAPIView(_MonitoringAPIView):
    """Record the observed serial on an inventory unit and re-match its observations."""

    schema_tags = ("Monitoring",)
    post_contract = operation(
        "DeviceConnectionLinkAction", DeviceConnectionSerializer, request=LinkDeviceConnectionRequestSerializer
    )

    def handle_post(self, request, connection_id, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assert serializer is not None
        command = LinkDeviceConnectionInput(connection_id, serializer.validated_data["equipment_id"])

        def link():
            link_device_connection(command, actor=request.user)
            return get_device_connection(connection_id=connection_id)

        return self._execute(link)


class ExpectedDeviceListCreateAPIView(AppListAPIView, _MonitoringAPIView):
    """List expected devices with their presence, or expect a device on a computing unit."""

    schema_tags = ("Monitoring",)
    get_contract = OperationContract(
        query=ExpectedDeviceQuerySerializer,
        success=ResponseContract.paginated("ExpectedDeviceList", ExpectedDeviceSerializer),
        bad_request=ResponseContract.problem(400),
    )
    post_contract = operation(
        "ExpectedDeviceCreate", ExpectedDeviceSerializer, request=CreateExpectedDeviceRequestSerializer, created=True
    )

    def project_result(self, result):
        return get_expected_device(expected_device_id=result.pk)

    def handle_get(self, request):
        params, error = self.validate_query()
        if error is not None:
            return error
        assert params is not None
        return self._execute(
            lambda: list_expected_devices(**_optional(params, "computing_id", "bench_id", "presence"))
        )

    def handle_post(self, request):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assert serializer is not None
        command = CreateExpectedDeviceInput(**serializer.validated_data)
        return self._execute(lambda: create_expected_device(command, actor=request.user), project=True)


class ExpectedDeviceDetailAPIView(_MonitoringAPIView):
    """Change disconnect alerts for an expected device, or stop expecting it."""

    schema_tags = ("Monitoring",)
    patch_contract = operation(
        "ExpectedDeviceUpdate", ExpectedDeviceSerializer, request=UpdateExpectedDeviceRequestSerializer
    )
    delete_contract = operation(delete=True)

    def project_result(self, result):
        return get_expected_device(expected_device_id=result.pk)

    def handle_patch(self, request, expected_device_id, **kwargs):
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assert serializer is not None
        command = UpdateExpectedDeviceInput(expected_device_id, serializer.validated_data["notify_on_disconnect"])
        return self._execute(lambda: update_expected_device(command, actor=request.user), project=True)

    def handle_delete(self, request, expected_device_id, **kwargs):
        return self._execute(
            lambda: delete_expected_device(expected_device_id=expected_device_id, actor=request.user), delete=True
        )
