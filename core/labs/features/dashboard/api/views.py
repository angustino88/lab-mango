"""HTTP API views for the laboratory dashboard feature domain."""

from __future__ import annotations

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.labs.features.base.common import FeatureAPIView

from ..queries import (
    get_dashboard_bench_detail,
    get_dashboard_summary,
    list_dashboard_benches,
)
from .serializers import (
    DashboardBenchDetailSerializer,
    DashboardBenchSerializer,
    DashboardOperationalSummarySerializer,
    DashboardQueryFilterSerializer,
)


class DashboardOverviewAPIView(FeatureAPIView, AppListAPIView):
    """Operational dashboard bench listing with real-time telemetry and schedule data."""

    schema_tags = ("Dashboard",)
    get_contract = OperationContract(
        query=DashboardQueryFilterSerializer,
        success=ResponseContract.paginated("DashboardBenchList", DashboardBenchSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        query_data, error = self.validate_query()
        if error is not None:
            return error

        filters = {
            k: v
            for k, v in (query_data or {}).items()
            if k not in ("page", "page_size") and v is not None
        }
        queryset = list_dashboard_benches(actor=request.user, **filters)
        return self.list_response_sync(queryset)


class DashboardSummaryAPIView(FeatureAPIView):
    """Operational dashboard summary metrics and status distributions."""

    schema_tags = ("Dashboard",)
    get_contract = OperationContract(
        success=ResponseContract.success(
            "DashboardOperationalSummaryData",
            DashboardOperationalSummarySerializer,
        ),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        data = get_dashboard_summary(actor=request.user)
        return self.respond_data(data)


class DashboardBenchDetailAPIView(FeatureAPIView):
    """Detailed operational view of an individual laboratory bench."""

    schema_tags = ("Dashboard",)
    get_contract = OperationContract(
        success=ResponseContract.success(
            "DashboardBenchDetailData",
            DashboardBenchDetailSerializer,
        ),
        not_found=ResponseContract.not_found(),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, bench_id: int, *args, **kwargs) -> Response:
        return self.respond(get_dashboard_bench_detail(bench_id=bench_id, actor=request.user))


__all__ = (
    "DashboardBenchDetailAPIView",
    "DashboardOverviewAPIView",
    "DashboardSummaryAPIView",
)
