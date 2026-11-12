"""Finance reads for lab coordinators and admins (owner decision 2026-11-11), and API keys."""

from collections.abc import Callable
from typing import Any

from django.http import HttpResponseBase
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.correlation import REQUEST_ID_HEADER, get_request_id
from core.common.api.exceptions import api_exception_handler
from core.common.api.permissions import HasAPIKeyAccess
from core.labs.features.base.common import FeatureAPIView
from core.users.public import IsLabCoordinatorReadWrite

from ...public import AnalyticsValidationError, get_finance_breakdown, get_finance_monthly_trends, get_finance_summary
from .schema import FinanceAutoSchema
from .serializers import (
    FinanceBreakdownSerializer,
    FinanceMonthlyTrendsSerializer,
    FinanceProblemResponseSerializer,
    FinanceQuerySerializer,
    FinanceSummarySerializer,
)
from .throttles import FinanceCallerThrottle


@extend_schema(parameters=[FinanceQuerySerializer])
class _FinanceAPIView(FeatureAPIView):
    permission_classes = [HasAPIKeyAccess | IsLabCoordinatorReadWrite]
    throttle_classes = [FinanceCallerThrottle]
    schema = FinanceAutoSchema()
    schema_tags = ("Analytics",)

    def get_exception_handler(self) -> Callable:
        return api_exception_handler

    def finalize_response(
        self, request: Request, response: HttpResponseBase, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        response = super().finalize_response(request, response, *args, **kwargs)
        response[REQUEST_ID_HEADER] = get_request_id(request)
        return response

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        # These bounded reports are not paginated. Reject duplicates rather than
        # silently choosing the last scalar parameter supplied by QueryDict.
        errors = {
            key: ["Unknown or repeated query parameter."]
            for key in request.query_params
            if key not in FinanceQuerySerializer().fields or len(request.query_params.getlist(key)) != 1
        }
        if errors:
            return self.respond_problem("bad_request", code="invalid_query", errors=errors)
        serializer = FinanceQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return self.respond_problem("bad_request", code="invalid_query", errors=serializer.errors)
        try:
            result = self.query(**serializer.validated_data)
        except AnalyticsValidationError as error:
            return self.respond_problem("bad_request", code="invalid_query", errors={"non_field_errors": [str(error)]})
        response = self.respond(result)
        response["Cache-Control"] = "private, no-cache"
        return response


class FinanceSummaryAPIView(_FinanceAPIView):
    """Actual cash flow, no commitments, allocations, FX or deduplication.

    Calendar months are inclusive; the next month's local midnight is exclusive.
    Date-only expense payments retain their calendar date. Procurement instants
    are bucketed in the requested zone. Refunds are signed and net is not clamped.
    Access: authenticated user or valid API key, as with existing finance reads.
    All finance reads share 30 requests/minute per user, or per IP for API keys.
    Invalid queries return invalid_query (400); exhausted budgets return rate_limited (429).
    """

    query = staticmethod(get_finance_summary)
    get_contract = OperationContract(
        query=FinanceQuerySerializer,
        success=ResponseContract.success("FinanceSummaryAnalytics", FinanceSummarySerializer),
        bad_request=ResponseContract.problem(400, FinanceProblemResponseSerializer),
        unauthorized=ResponseContract.problem(401, FinanceProblemResponseSerializer),
        forbidden=ResponseContract.problem(403, FinanceProblemResponseSerializer),
        rate_limited=ResponseContract.problem(429, FinanceProblemResponseSerializer),
    )


class FinanceMonthlyTrendsAPIView(_FinanceAPIView):
    """Monthly actual cash-flow series, zero-filled, with separate source totals.

    Same currency, access, signed-refund and timezone rules as finance summary.
    Inclusive calendar-month window is bounded to 24 months; no deduplication/FX.
    All finance reads share 30 requests/minute per user, or per IP for API keys.
    Invalid queries return invalid_query (400); exhausted budgets return rate_limited (429).
    """

    query = staticmethod(get_finance_monthly_trends)
    get_contract = OperationContract(
        query=FinanceQuerySerializer,
        success=ResponseContract.success("FinanceMonthlyTrendsAnalytics", FinanceMonthlyTrendsSerializer),
        bad_request=ResponseContract.problem(400, FinanceProblemResponseSerializer),
        unauthorized=ResponseContract.problem(401, FinanceProblemResponseSerializer),
        forbidden=ResponseContract.problem(403, FinanceProblemResponseSerializer),
        rate_limited=ResponseContract.problem(429, FinanceProblemResponseSerializer),
    )


class FinanceBreakdownAPIView(_FinanceAPIView):
    """Actual cash flow by expense type and source; purchases use procurement.

    No purchase commitment/allocation reporting. Same inclusive month window,
    timezone boundaries, signed refunds, access, no-FX and no-dedup semantics.
    All finance reads share 30 requests/minute per user, or per IP for API keys.
    Invalid queries return invalid_query (400); exhausted budgets return rate_limited (429).
    """

    query = staticmethod(get_finance_breakdown)
    get_contract = OperationContract(
        query=FinanceQuerySerializer,
        success=ResponseContract.success("FinanceBreakdownAnalytics", FinanceBreakdownSerializer),
        bad_request=ResponseContract.problem(400, FinanceProblemResponseSerializer),
        unauthorized=ResponseContract.problem(401, FinanceProblemResponseSerializer),
        forbidden=ResponseContract.problem(403, FinanceProblemResponseSerializer),
        rate_limited=ResponseContract.problem(429, FinanceProblemResponseSerializer),
    )


__all__ = ["FinanceBreakdownAPIView", "FinanceMonthlyTrendsAPIView", "FinanceSummaryAPIView"]
