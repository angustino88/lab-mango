"""HTTP API views for the leaderboard and operational dashboard feature domain."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.domain.errors import InvalidQuery
from core.labs.features.base.common import FeatureAPIView

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

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        query=LeaderboardDateRangeQuerySerializer,
        success=ResponseContract.success("LeaderboardPersona", LeaderboardPersonaSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        start_date, end_date = _date_range(request)
        data = compute_leaderboard_persona(start_date, end_date)
        return self.respond_data(data)


class LeaderboardLabAPIView(FeatureAPIView):
    """Laboratory and bench utilization rankings."""

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        query=LeaderboardDateRangeQuerySerializer,
        success=ResponseContract.success("LeaderboardLab", LeaderboardLabSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        start_date, end_date = _date_range(request)
        data = compute_leaderboard_lab(start_date, end_date)
        return self.respond_data(data)


class LeaderboardExportAPIView(FeatureAPIView):
    """Export leaderboard performance data."""

    schema_tags = ("Leaderboard",)
    get_contract = OperationContract(
        query=LeaderboardExportQuerySerializer,
        success=ResponseContract.success("LeaderboardExport", LeaderboardPersonaSerializer, many=True),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        start_date, end_date = _date_range(request)
        export_type = request.query_params.get("type", "persona")
        if export_type == "lab":
            data = compute_leaderboard_lab(start_date, end_date)
        else:
            data = compute_leaderboard_persona(start_date, end_date)
        return self.respond_data(data)


class LabProfileAPIView(FeatureAPIView):
    """Retrieve laboratory bench performance profile."""

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


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for bench profile. Use /api/labs/benches/{id}/profile instead.",
    ),
)
class DeprecatedLabProfileAPIView(LabProfileAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        pk = kwargs.get("pk")
        if pk:
            response["Link"] = f'</api/labs/benches/{pk}/profile>; rel="successor-version"'
        return response


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for bench weekly usage heatmap. Use /api/labs/benches/{id}/weekly-usage instead.",
    ),
)
class DeprecatedLabWeeklyUsageHeatmapAPIView(LabWeeklyUsageHeatmapAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        pk = kwargs.get("pk")
        if pk:
            response["Link"] = f'</api/labs/benches/{pk}/weekly-usage>; rel="successor-version"'
        return response


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for user profile. Use /api/labs/leaderboard/users/{id}/profile instead.",
    ),
)
class DeprecatedUserProfileAPIView(UserProfileAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        pk = kwargs.get("pk")
        if pk:
            response["Link"] = f'</api/labs/leaderboard/users/{pk}/profile>; rel="successor-version"'
        return response


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for user weekly usage heatmap. Use /api/labs/leaderboard/users/{id}/weekly-usage instead.",
    ),
)
class DeprecatedUserWeeklyUsageHeatmapAPIView(UserWeeklyUsageHeatmapAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        pk = kwargs.get("pk")
        if pk:
            response["Link"] = f'</api/labs/leaderboard/users/{pk}/weekly-usage>; rel="successor-version"'
        return response


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for dashboard summary. Use /api/labs/dashboard/summary instead.",
    ),
)
class DeprecatedLeaderboardDashboardSummaryAPIView(DashboardSummaryAPIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        response["Link"] = '</api/labs/dashboard/summary>; rel="successor-version"'
        return response


__all__ = [
    "DashboardSummaryAPIView",
    "DeprecatedLabProfileAPIView",
    "DeprecatedLabWeeklyUsageHeatmapAPIView",
    "DeprecatedLeaderboardDashboardSummaryAPIView",
    "DeprecatedUserProfileAPIView",
    "DeprecatedUserWeeklyUsageHeatmapAPIView",
    "LabDashboardAPIView",
    "LabProfileAPIView",
    "LabWeeklyUsageHeatmapAPIView",
    "LeaderboardExportAPIView",
    "LeaderboardLabAPIView",
    "LeaderboardPersonaAPIView",
    "UserProfileAPIView",
    "UserWeeklyUsageHeatmapAPIView",
]
