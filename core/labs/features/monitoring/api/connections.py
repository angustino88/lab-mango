"""Typed, paginated current connection reads under the existing Labs access policy."""

from datetime import timezone as datetime_timezone

from django.utils.cache import patch_vary_headers
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import serializers

from core.common.api.api_views import AppListAPIView
from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.summary_serializers import choice_field
from core.common.domain.errors import BadRequest
from core.labs.features.base import CommandAPIView
from core.labs.features.base.serializers import NamedReferenceSerializer, UIDNamedReferenceSerializer
from core.labs.features.monitoring.queries.connections import list_device_connections
from core.labs.models.monitoring import DeviceConnectionState, DeviceMatchStatus


class DeviceConnectionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    computing = UIDNamedReferenceSerializer()
    equipment = UIDNamedReferenceSerializer(allow_null=True)
    interface = NamedReferenceSerializer(allow_null=True)
    interface_name = serializers.CharField()
    collector_key = serializers.CharField()
    observation_key = serializers.CharField()
    name = serializers.CharField(allow_blank=True)
    serial_number = serializers.CharField(allow_blank=True)
    state = choice_field(DeviceConnectionState.choices)
    match_status = choice_field(DeviceMatchStatus.choices)
    freshness = choice_field((("fresh", "Fresh"), ("stale", "Stale"), ("unknown", "Unknown")))
    observed_at = serializers.DateTimeField(default_timezone=datetime_timezone.utc, format="%Y-%m-%dT%H:%M:%S.%fZ")
    received_at = serializers.DateTimeField(default_timezone=datetime_timezone.utc, format="%Y-%m-%dT%H:%M:%S.%fZ")


class DeviceConnectionQuerySerializer(PageNumberQuerySerializer):
    computing_id = serializers.IntegerField(min_value=1)


class DeviceConnectionListAPIView(AppListAPIView, CommandAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store" if response.status_code >= 400 else "private, no-cache"
        patch_vary_headers(response, ("Accept", "Accept-Language"))
        return response

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
        return self._execute(lambda: list_device_connections(computing_id=params["computing_id"]))
