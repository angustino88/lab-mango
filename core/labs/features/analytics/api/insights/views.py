"""Existing strict-window insight endpoints."""

from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.request import Request
from rest_framework.response import Response

from core.labs.features.base.common import FeatureAPIView

from ...public import get_booked_vs_used, get_dashboard_summary, get_equipment_availability
from .serializers import (
    BookedVsUsedSerializer,
    DashboardSummarySerializer,
    EquipmentAvailabilitySerializer,
    InsightRangeQuerySerializer,
)


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for dashboard summary. Use /api/labs/dashboard/summary instead.",
    ),
)
class DashboardSummaryAPIView(FeatureAPIView):
    """Headline KPI cards with previous-period trend for a date window."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        query=InsightRangeQuerySerializer,
        success=ResponseContract.success("DashboardSummaryAnalytics", DashboardSummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        response["Link"] = '</api/labs/dashboard/summary>; rel="successor-version"'
        return response

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        data = get_dashboard_summary(
            from_date_time=filters["from_date_time"],
            to_date_time=filters["to_date_time"],
        )
        return self.respond(data)


class BookedVsUsedAPIView(FeatureAPIView):
    """Reserved bench hours compared with recorded session hours for a date window."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        query=InsightRangeQuerySerializer,
        success=ResponseContract.success("BookedVsUsedAnalytics", BookedVsUsedSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        data = get_booked_vs_used(
            from_date_time=filters["from_date_time"],
            to_date_time=filters["to_date_time"],
        )
        return self.respond(data)


class EquipmentAvailabilityAPIView(FeatureAPIView):
    """Equipment uptime and outage counts derived from status history for a date window."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        query=InsightRangeQuerySerializer,
        success=ResponseContract.success("EquipmentAvailabilityAnalytics", EquipmentAvailabilitySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        data = get_equipment_availability(
            from_date_time=filters["from_date_time"],
            to_date_time=filters["to_date_time"],
        )
        return self.respond(data)
