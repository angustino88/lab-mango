"""Resource distribution HTTP adapters."""

from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.request import Request
from rest_framework.response import Response

from core.labs.features.base.common import FeatureAPIView

from ...public import get_bench_group_distribution, get_equipment_status_distribution
from .serializers import BenchGroupSummarySerializer, EquipmentStatusSummarySerializer


class BenchGroupSummaryAPIView(FeatureAPIView):
    """Laboratory and bench distribution summary across bench groups."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        success=ResponseContract.success("BenchGroupSummary", BenchGroupSummarySerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        return self.respond_data(get_bench_group_distribution())


class EquipmentStatusSummaryAPIView(FeatureAPIView):
    """Lifecycle and operational status distribution across equipment assets."""

    schema_tags = ("Analytics",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentStatusSummary", EquipmentStatusSummarySerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        return self.respond_data(get_equipment_status_distribution())


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for bench-group summary. Use /api/labs/analytics/bench-group instead.",
    ),
)
class DeprecatedLabGroupSummaryAPIView(BenchGroupSummaryAPIView):
    """Deprecated alias for bench-group summary.

    Use /api/labs/analytics/bench-group instead.
    """

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        response["Link"] = '</api/labs/analytics/bench-group>; rel="successor-version"'
        return response


__all__ = [
    "BenchGroupSummaryAPIView",
    "DeprecatedLabGroupSummaryAPIView",
    "EquipmentStatusSummaryAPIView",
]
