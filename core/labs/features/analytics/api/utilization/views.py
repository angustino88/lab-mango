"""Legacy utilization parsing, defaults and query calls remain compatible."""

from datetime import datetime
from typing import ClassVar

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.labs.features.base.common import FeatureAPIView

from ...public import (
    get_bench_efficiency_rankings,
    get_project_utilization,
    get_timeframe_utilization,
    get_user_booking_compliance,
    get_user_utilization,
)
from .serializers import (
    DateRangeAnalysisQuerySerializer,
    LabEfficiencySerializer,
    LabUsageTimeframeSerializer,
    ProjectUsageSerializer,
    TimeframeQuerySerializer,
    UserBookingEfficiencySerializer,
    UserLabUsageSerializer,
)


class _LegacyRangeAPIView(FeatureAPIView):
    schema_tags = ("Analytics",)
    default_top: ClassVar[int | None] = 5
    ranked: ClassVar[bool] = True

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        from_str = request.query_params.get("from_date_time")
        to_str = request.query_params.get("to_date_time")
        if not from_str or not to_str:
            return self.respond_problem(
                "bad_request", code="missing_dates", errors={"date": ["from_date_time and to_date_time are required."]}
            )
        try:
            from_dt = datetime.fromisoformat(from_str.replace(" ", "+"))
            to_dt = datetime.fromisoformat(to_str.replace(" ", "+"))
        except ValueError:
            return self.respond_problem(
                "bad_request", code="invalid_date_format", errors={"date": ["Invalid ISO datetime format."]}
            )
        if not self.ranked:
            return self.respond_data(self.query(from_date_time=from_dt, to_date_time=to_dt))
        order = request.query_params.get("order", "desc")
        top_raw = request.query_params.get("top", str(self.default_top) if self.default_top is not None else None)
        top_n = int(top_raw) if top_raw and top_raw.isdigit() else self.default_top
        return self.respond_data(self.query(from_date_time=from_dt, to_date_time=to_dt, sort_order=order, top_n=top_n))


class LabEfficiencyAPIView(_LegacyRangeAPIView):
    """Efficiency and duration utilization for computing assets in laboratory benches."""

    default_top = None
    query = staticmethod(get_bench_efficiency_rankings)
    get_contract = OperationContract(
        query=DateRangeAnalysisQuerySerializer,
        success=ResponseContract.success("LabEfficiency", LabEfficiencySerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )


class ProjectUsageAPIView(_LegacyRangeAPIView):
    """Aggregate duration and booking consumption grouped by project."""

    query = staticmethod(get_project_utilization)
    get_contract = OperationContract(
        query=DateRangeAnalysisQuerySerializer,
        success=ResponseContract.success("ProjectUsage", ProjectUsageSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )


class UserLabUsageAPIView(_LegacyRangeAPIView):
    """Existing session usage report."""

    query = staticmethod(get_user_utilization)
    get_contract = OperationContract(
        query=DateRangeAnalysisQuerySerializer,
        success=ResponseContract.success("UserLabUsage", UserLabUsageSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )


class UserBookingEfficiencyAPIView(_LegacyRangeAPIView):
    """Existing booking-duration report."""

    query = staticmethod(get_user_booking_compliance)
    get_contract = OperationContract(
        query=DateRangeAnalysisQuerySerializer,
        success=ResponseContract.success("UserBookingEfficiency", UserBookingEfficiencySerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )


class LabUsageTimeframeAPIView(_LegacyRangeAPIView):
    """Aggregate utilization partitioned across 12 daily 2-hour interval buckets."""

    ranked = False
    query = staticmethod(get_timeframe_utilization)
    get_contract = OperationContract(
        query=TimeframeQuerySerializer,
        success=ResponseContract.success("LabUsageTimeframe", LabUsageTimeframeSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

