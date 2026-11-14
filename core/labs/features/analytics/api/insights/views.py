"""Existing strict-window insight endpoints."""

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.labs.features.base.common import FeatureAPIView

from ...public import get_booked_vs_used, get_equipment_availability
from .serializers import (
    BookedVsUsedSerializer,
    EquipmentAvailabilitySerializer,
    InsightRangeQuerySerializer,
)


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
