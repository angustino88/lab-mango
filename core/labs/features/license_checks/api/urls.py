"""URL routing for the license-check staff API."""

from django.urls import path

from .views import (
    LicenseCheckDetailAPIView,
    LicenseCheckListCreateAPIView,
    LicenseCheckPresetListAPIView,
    LicenseCheckRunListAPIView,
    LicenseObservationListAPIView,
)

urlpatterns = [
    path("license-checks", LicenseCheckListCreateAPIView.as_view(), name="license-check-list-create"),
    path("license-checks/presets", LicenseCheckPresetListAPIView.as_view(), name="license-check-presets"),
    path("license-checks/<int:check_id>", LicenseCheckDetailAPIView.as_view(), name="license-check-detail"),
    path("license-checks/<int:check_id>/runs", LicenseCheckRunListAPIView.as_view(), name="license-check-runs"),
    path("license-observations", LicenseObservationListAPIView.as_view(), name="license-observation-list"),
]
