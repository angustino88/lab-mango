"""URL routes for the analytics HTTP API."""

from django.urls import path

from .distribution.views import (
    BenchGroupSummaryAPIView,
    DeprecatedLabGroupSummaryAPIView,
    EquipmentStatusSummaryAPIView,
)
from .finance.views import FinanceBreakdownAPIView, FinanceMonthlyTrendsAPIView, FinanceSummaryAPIView
from .insights.views import BookedVsUsedAPIView, DashboardSummaryAPIView, EquipmentAvailabilityAPIView
from .observations.views import BookingCountAPIView, LabCountAPIView, LabVisitsAPIView, UserCountAPIView
from .storage.views import StorageQuotaAPIView
from .utilization.views import (
    LabEfficiencyAPIView,
    LabUsageTimeframeAPIView,
    ProjectUsageAPIView,
    UserBookingEfficiencyAPIView,
    UserLabUsageAPIView,
)

urlpatterns = [
    path("finance/summary", FinanceSummaryAPIView.as_view(), name="analytics-finance-summary"),
    path("finance/monthly-trends", FinanceMonthlyTrendsAPIView.as_view(), name="analytics-finance-monthly-trends"),
    path(
        "finance/expense-type-breakdown",
        FinanceBreakdownAPIView.as_view(),
        name="analytics-finance-expense-type-breakdown",
    ),
    path("bench-group", BenchGroupSummaryAPIView.as_view(), name="analytics-bench-group"),
    path("lab-group", DeprecatedLabGroupSummaryAPIView.as_view(), name="analytics-lab-group"),
    path("lab-equipment-status", EquipmentStatusSummaryAPIView.as_view(), name="analytics-equipment-status"),
    path("lab-efficiency", LabEfficiencyAPIView.as_view(), name="analytics-lab-efficiency"),
    path("project-usage", ProjectUsageAPIView.as_view(), name="analytics-project-usage"),
    path("user-lab-usage", UserLabUsageAPIView.as_view(), name="analytics-user-lab-usage"),
    path("user-booking-efficiency", UserBookingEfficiencyAPIView.as_view(), name="analytics-user-booking-efficiency"),
    path("lab-usage-by-timeframe", LabUsageTimeframeAPIView.as_view(), name="analytics-lab-usage-timeframe"),
    path("storage-quota", StorageQuotaAPIView.as_view(), name="analytics-storage-quota"),
    path("lab-visits", LabVisitsAPIView.as_view(), name="analytics-lab-visits"),
    path("booking", BookingCountAPIView.as_view(), name="analytics-booking-count"),
    path("lab-count", LabCountAPIView.as_view(), name="analytics-lab-count"),
    path("user-count", UserCountAPIView.as_view(), name="analytics-user-count"),
    path("dashboard-summary", DashboardSummaryAPIView.as_view(), name="analytics-dashboard-summary"),
    path("booked-vs-used", BookedVsUsedAPIView.as_view(), name="analytics-booked-vs-used"),
    path("equipment-availability", EquipmentAvailabilityAPIView.as_view(), name="analytics-equipment-availability"),
]
