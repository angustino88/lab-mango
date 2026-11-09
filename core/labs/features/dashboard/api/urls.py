"""URL configuration for the dashboard HTTP API."""

from django.urls import path

from .views import (
    DashboardBenchDetailAPIView,
    DashboardOverviewAPIView,
    DashboardSummaryAPIView,
)

urlpatterns = [
    path("dashboard", DashboardOverviewAPIView.as_view(), name="dashboard-overview"),
    path("dashboard/summary", DashboardSummaryAPIView.as_view(), name="dashboard-summary"),
    path(
        "dashboard/benches/<int:bench_id>",
        DashboardBenchDetailAPIView.as_view(),
        name="dashboard-bench-detail",
    ),
]
