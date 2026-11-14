"""HTTP API views for the leaderboard and operational dashboard feature domain."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.domain.errors import InvalidQuery
from core.labs.features.base import LABS_MEMBER_READ_ACCESS, FeatureAPIView

from ..helpers import parse_date_range
from ..public import (
    compute_leaderboard_lab,
    compute_leaderboard_persona,
    get_dashboard_labs,
    get_dashboard_summary,
    get_lab_profile,
    get_lab_weekly_usage,
    get_user_profile,
    get_user_weekly_usage,
)
from .serializers import (
    DashboardPaginatedResponseSerializer,
    DashboardSummaryDataSerializer,
    DashboardUnpaginatedResponseSerializer,
    LabProfileSerializer,
    LeaderboardDateRangeQuerySerializer,
    LeaderboardExportQuerySerializer,
    LeaderboardLabSerializer,
    LeaderboardPersonaSerializer,
    UserProfileSerializer,
    WeeklyUsageSlotSerializer,
)


def _date_range(request: Request):
    """Parse the optional date range (default: last 30 days); invalid input is a 400 InvalidQuery."""
    try:
        return parse_date_range(request, timezone.now() - timedelta(days=30))
    except DRFValidationError as error:
        messages = [str(detail) for detail in error.detail]
        raise InvalidQuery(messages[0], code="invalid_date_format", details={"date": messages}) from error


class LeaderboardPersonaAPIView(FeatureAPIView):
    """User performance rankings and operational metrics."""
    permission_classes = LABS_MEMBER_READ_ACCESS

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        query=LeaderboardDateRangeQuerySerializer,
        success=ResponseContract.success("LeaderboardPersona", LeaderboardPersonaSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        start_date, end_date = _date_range(request)
        data = compute_leaderboard_persona(start_date, end_date)
        return self.respond(data)


class LeaderboardLabAPIView(FeatureAPIView):
    """Laboratory and bench utilization rankings."""
    permission_classes = LABS_MEMBER_READ_ACCESS

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        query=LeaderboardDateRangeQuerySerializer,
        success=ResponseContract.success("LeaderboardLab", LeaderboardLabSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        start_date, end_date = _date_range(request)
        data = compute_leaderboard_lab(start_date, end_date)
        return self.respond(data)


class LeaderboardExportAPIView(FeatureAPIView):
    """Export leaderboard performance data."""
    permission_classes = LABS_MEMBER_READ_ACCESS

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        query=LeaderboardExportQuerySerializer,
        success=ResponseContract.success("LeaderboardExport", LeaderboardPersonaSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        start_date, end_date = _date_range(request)
        export_type = request.query_params.get("type", "persona")
        # Serialize with the row type's own serializer so the wire keys match the schema (NAM-3).
        if export_type == "lab":
            rows = LeaderboardLabSerializer(compute_leaderboard_lab(start_date, end_date), many=True).data
        else:
            rows = LeaderboardPersonaSerializer(compute_leaderboard_persona(start_date, end_date), many=True).data
        return Response({"data": rows})


class LabProfileAPIView(FeatureAPIView):
    """Retrieve laboratory bench performance profile."""
    permission_classes = LABS_MEMBER_READ_ACCESS

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        query=LeaderboardDateRangeQuerySerializer,
        success=ResponseContract.success("LabProfile", LabProfileSerializer),
        not_found=ResponseContract.not_found(),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, pk: int, *args, **kwargs) -> Response:
        start_date, end_date = _date_range(request)
        return self.respond_data(get_lab_profile(pk, start_date, end_date))


class LabWeeklyUsageHeatmapAPIView(FeatureAPIView):
    """Weekly utilization heatmap for a specific laboratory bench."""
    permission_classes = LABS_MEMBER_READ_ACCESS

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        success=ResponseContract.success("LabWeeklyUsage", WeeklyUsageSlotSerializer, many=True),
        not_found=ResponseContract.not_found(),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, pk: int, *args, **kwargs) -> Response:
        return self.respond_data(get_lab_weekly_usage(pk))


class UserProfileAPIView(FeatureAPIView):
    """User profile ranking and session summary."""
    permission_classes = LABS_MEMBER_READ_ACCESS

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        query=LeaderboardDateRangeQuerySerializer,
        success=ResponseContract.success("UserProfile", UserProfileSerializer),
        not_found=ResponseContract.not_found(),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, pk: int, *args, **kwargs) -> Response:
        start_date, end_date = _date_range(request)
        return self.respond_data(get_user_profile(pk, start_date, end_date))


class UserWeeklyUsageHeatmapAPIView(FeatureAPIView):
    """Weekly usage heatmap for an individual user."""
    permission_classes = LABS_MEMBER_READ_ACCESS

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        success=ResponseContract.success("UserWeeklyUsage", WeeklyUsageSlotSerializer, many=True),
        not_found=ResponseContract.not_found(),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, pk: int, *args, **kwargs) -> Response:
        return self.respond_data(get_user_weekly_usage(pk))


class DashboardSummaryAPIView(FeatureAPIView):
    """High-level asset count and status distribution summary."""
    permission_classes = LABS_MEMBER_READ_ACCESS

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        success=ResponseContract.success("DashboardSummary", DashboardSummaryDataSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        data = get_dashboard_summary()
        return self.respond_data(data)


class LabDashboardAPIView(FeatureAPIView):
    """Laboratory dashboard overview with polymorphic paginated or unpaginated list."""
    permission_classes = LABS_MEMBER_READ_ACCESS

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        success=ResponseContract.polymorphic(
            "LabDashboardResponse",
            [
                DashboardUnpaginatedResponseSerializer,
                DashboardPaginatedResponseSerializer,
            ],
        ),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        data = get_dashboard_labs()
        return self.respond_data(data)


__all__ = [
    "DashboardSummaryAPIView",
    "LabDashboardAPIView",
    "LabProfileAPIView",
    "LabWeeklyUsageHeatmapAPIView",
    "LeaderboardExportAPIView",
    "LeaderboardLabAPIView",
    "LeaderboardPersonaAPIView",
    "UserProfileAPIView",
    "UserWeeklyUsageHeatmapAPIView",
]
