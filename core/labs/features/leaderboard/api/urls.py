"""URL routes for the leaderboard HTTP API."""
from django.urls import path

from .views import (
    BenchAssessmentAPIView,
    LabDashboardAPIView,
    LabProfileAPIView,
    LabWeeklyUsageHeatmapAPIView,
    LeaderboardExportAPIView,
    LeaderboardLabAPIView,
    LeaderboardPersonaAPIView,
    UserAssessmentAPIView,
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
    # KPI assessments: lab coordinators and administrators only.
    path("benches/<int:pk>/assessment", BenchAssessmentAPIView.as_view(), name="bench-assessment"),
    path("leaderboard/users/<int:pk>/assessment", UserAssessmentAPIView.as_view(), name="leaderboard-user-assessment"),
    path("lab-dashboard", LabDashboardAPIView.as_view(), name="lab-dashboard"),
]
