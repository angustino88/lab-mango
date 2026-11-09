"""URL configuration for the expense HTTP API."""
from django.urls import path

from .views import (
    DeprecatedFinancialReportAPIView,
    ExpensePaymentListCreateAPIView,
    FinancialReportAPIView,
    RoomExpenseListCreateAPIView,
    RoomFinancialReportAPIView,
)

urlpatterns = [
    path(
        "rooms/<int:room_id>/expenses",
        RoomExpenseListCreateAPIView.as_view(),
        name="room-expense-list",
    ),
    path(
        "rooms/<int:room_id>/expenses/report",
        RoomFinancialReportAPIView.as_view(),
        name="room-financial-report",
    ),
    path(
        "expenses/<int:expense_id>/payments",
        ExpensePaymentListCreateAPIView.as_view(),
        name="expense-payment-list",
    ),
    path(
        "expenses/report",
        FinancialReportAPIView.as_view(),
        name="expense-financial-report",
    ),
    path(
        "financial-report",
        DeprecatedFinancialReportAPIView.as_view(),
        name="financial-report",
    ),
]
