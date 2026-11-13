"""Existing count and facility-visit HTTP behavior."""

from drf_api_contracts import OperationContract, ResponseContract, ResponseSchemaFactory
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from core.labs.features.base.common import FeatureAPIView

from ...public import (
    RecordFacilityVisitInput,
    get_active_bench_metrics,
    get_active_user_metrics,
    get_booking_volume_metrics,
    get_facility_visit_metrics,
    record_facility_visit,
)
from .serializers import (
    AnalyticsAggregatedLogSerializer,
    AnalyticsCountTrendSerializer,
    LabVisitLogCreateSerializer,
    LabVisitLogResponseSerializer,
    UnitQuerySerializer,
)


class _AnalyticsResponseEnvelopeSerializer(serializers.Serializer):
    """Schema-only envelope; create the proxy fresh to retain its explicit many=False."""

    def get_fields(self):
        # DRF deep-copies declared fields, losing the proxy's constructor-only `many`.
        # A fresh proxy keeps the array alternative processable by spectacular.
        return {
            "data": ResponseSchemaFactory.polymorphic(
                f"{type(self).__name__}Payload",
                [AnalyticsCountTrendSerializer, AnalyticsAggregatedLogSerializer(many=True)],
            ),
        }


def _metric_filters(query) -> dict:
    """Map validated query values to selector keywords; absent values stay ``None``."""
    query = query or {}
    return {key: query.get(key) for key in ("unit", "date_after", "date_before")}


def _analytics_response_schema(name: str) -> serializers.Serializer:
    """Document the responder's envelope without changing payload validation."""
    return type(name, (_AnalyticsResponseEnvelopeSerializer,), {"__module__": __name__})()


class BookingCountAPIView(FeatureAPIView):
    """Aggregate booking count and trend or bucketed changelog statistics."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        query=UnitQuerySerializer,
        success=ResponseContract.from_schema(
            _analytics_response_schema("BookingCountAnalyticsResponse"),
        ),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        return self.respond_data(get_booking_volume_metrics(**_metric_filters(query)))


class LabCountAPIView(FeatureAPIView):
    """Active laboratory/bench count trend or historical aggregated measurements."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        query=UnitQuerySerializer,
        success=ResponseContract.from_schema(
            _analytics_response_schema("LabCountAnalyticsResponse"),
        ),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        return self.respond_data(get_active_bench_metrics(**_metric_filters(query)))


class UserCountAPIView(FeatureAPIView):
    """Active user count trend or historical aggregated measurements."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        query=UnitQuerySerializer,
        success=ResponseContract.from_schema(
            _analytics_response_schema("UserCountAnalyticsResponse"),
        ),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        return self.respond_data(get_active_user_metrics(**_metric_filters(query)))


class LabVisitsAPIView(FeatureAPIView):
    """Retrieve visit trend metrics or record an access visit event."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        query=UnitQuerySerializer,
        success=ResponseContract.from_schema(
            _analytics_response_schema("LabVisitAnalyticsResponse"),
        ),
        bad_request=ResponseContract.bad_request(),
    )
    post_contract = OperationContract(
        request=LabVisitLogCreateSerializer,
        success=ResponseContract.success("LabVisitCreated", LabVisitLogResponseSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        return self.respond_data(get_facility_visit_metrics(**_metric_filters(query)))

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer = LabVisitLogCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return self.respond_problem("bad_request", code="validation_failed", errors=serializer.errors)
        vd = serializer.validated_data
        cmd_input = RecordFacilityVisitInput(
            facility_identifier=vd.get("facility_identifier", ""),
            external_reference=vd.get("external_reference", ""),
        )
        event = record_facility_visit(cmd_input, actor=request.user)
        result = {"id": event.pk, "facility_identifier": event.facility_identifier, "occurred_at": event.occurred_at}
        return self.respond_data(result)
