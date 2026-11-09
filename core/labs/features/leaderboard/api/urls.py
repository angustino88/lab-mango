"""URL routes for the leaderboard HTTP API."""
from django.urls import path

from .views import (
    DeprecatedLabProfileAPIView,
    DeprecatedLabWeeklyUsageHeatmapAPIView,
    DeprecatedLeaderboardDashboardSummaryAPIView,
    DeprecatedUserProfileAPIView,
    DeprecatedUserWeeklyUsageHeatmapAPIView,
    LabDashboardAPIView,
    LabProfileAPIView,
    LabWeeklyUsageHeatmapAPIView,
    LeaderboardExportAPIView,
    LeaderboardLabAPIView,
    LeaderboardPersonaAPIView,
    UserProfileAPIView,
    UserWeeklyUsageHeatmapAPIView,
)

urlpatterns = [
    path("leaderboard/persona", LeaderboardPersonaAPIView.as_view(), name="leaderboard-persona"),
    path("leaderboard/lab", LeaderboardLabAPIView.as_view(), name="leaderboard-lab"),
    path("leaderboard/export", LeaderboardExportAPIView.as_view(), name="leaderboard-export"),
    # Canonical disambiguated bench and user profile/heatmap routes
    path("benches/<int:pk>/profile", LabProfileAPIView.as_view(), name="bench-profile"),
    path("benches/<int:pk>/weekly-usage", LabWeeklyUsageHeatmapAPIView.as_view(), name="bench-weekly-usage-heatmap"),
    path("leaderboard/users/<int:pk>/profile", UserProfileAPIView.as_view(), name="leaderboard-user-profile"),
    path("leaderboard/users/<int:pk>/weekly-usage", UserWeeklyUsageHeatmapAPIView.as_view(), name="leaderboard-user-weekly-usage-heatmap"),
    path("lab-dashboard", LabDashboardAPIView.as_view(), name="lab-dashboard"),
    # Compatibility aliases (marked deprecated in OpenAPI)
    path("profile/<int:pk>", DeprecatedLabProfileAPIView.as_view(), name="lab-profile"),
    path("weekly-usage/<int:pk>", DeprecatedLabWeeklyUsageHeatmapAPIView.as_view(), name="lab-weekly-usage-heatmap"),
    path("users/profile/<int:pk>", DeprecatedUserProfileAPIView.as_view(), name="user-profile"),
    path("users/weekly-usage/<int:pk>", DeprecatedUserWeeklyUsageHeatmapAPIView.as_view(), name="user-weekly-usage-heatmap"),
    path("lab-dashboard/summary", DeprecatedLeaderboardDashboardSummaryAPIView.as_view(), name="dashboard-summary"),
]
