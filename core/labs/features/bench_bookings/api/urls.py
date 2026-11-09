from django.urls import path

from . import views
from .reference_data import urlpatterns as reference_urlpatterns

urlpatterns = [
    path("bench-bookings", views.BenchBookingCreateAPIView.as_view(), name="bench-booking-create"),
    path(
        "bench-bookings/<int:booking_id>",
        views.BenchBookingDetailAPIView.as_view(),
        name="bench-booking-detail",
    ),
    path(
        "bench-bookings/<int:booking_id>/actions/cancel",
        views.BenchBookingCancelActionAPIView.as_view(),
        name="bench-booking-action-cancel",
    ),
    path(
        "bench-bookings/<int:booking_id>/actions/approve",
        views.BenchBookingApproveActionAPIView.as_view(),
        name="bench-booking-action-approve",
    ),
    path(
        "bench-bookings/<int:booking_id>/actions/reject",
        views.BenchBookingRejectActionAPIView.as_view(),
        name="bench-booking-action-reject",
    ),
    path(
        "bench-bookings/<int:booking_id>/actions/complete",
        views.BenchBookingCompleteActionAPIView.as_view(),
        name="bench-booking-action-complete",
    ),
    path(
        "bench-bookings/code/<str:booking_code>",
        views.BenchBookingCodeDetailAPIView.as_view(),
        name="bench-booking-code-detail",
    ),
    path(
        "bench-bookings/code/<str:booking_code>/actions/cancel",
        views.BenchBookingCancelByCodeActionAPIView.as_view(),
        name="bench-booking-code-action-cancel",
    ),
    path("lab-projects", views.LabProjectListAPIView.as_view(), name="lab-project-list"),
    path("lab-projects/options", views.LabProjectOptionsAPIView.as_view(), name="lab-project-options"),
    path("lab-projects/<int:project_id>", views.LabProjectDetailAPIView.as_view(), name="lab-project-detail"),
]
urlpatterns += reference_urlpatterns
