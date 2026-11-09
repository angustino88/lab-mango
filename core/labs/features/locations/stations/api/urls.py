from django.urls import path

from . import views
from .views import StationStatusSummaryAPIView

urlpatterns = [
    path("stations/status-summary", StationStatusSummaryAPIView.as_view(), name="station-status-summary"),
    path("stations", views.StationListCreateAPIView.as_view(), name="station-list-create"),
    path("stations/options", views.StationOptionsAPIView.as_view(), name="station-options"),
    path("stations/filters", views.StationFiltersAPIView.as_view(), name="station-filters"),
    path("stations/reference-data", views.StationReferenceDataAPIView.as_view(), name="station-reference-data"),
    path("stations/<int:station_id>", views.StationDetailAPIView.as_view(), name="station-detail"),
    path("stations/<int:station_id>/actions/place", views.StationPlaceAPIView.as_view(), name="station-action-place"),
    path("stations/<int:station_id>/actions/change-status", views.StationStatusAPIView.as_view(), name="station-action-change-status"),
    path("stations/<int:station_id>/slots", views.StationSlotListCreateAPIView.as_view(), name="station-slot-list-create"),
    path("stations/<int:station_id>/slots/<int:slot_id>", views.StationSlotDetailAPIView.as_view(), name="station-slot-detail"),
    path("stations/<int:station_id>/history", views.StationHistoryAPIView.as_view(), name="station-history"),
    path("station-types", views.StationTypeListCreateAPIView.as_view(), name="station-type-list-create"),
    path("station-types/options", views.StationTypeOptionsAPIView.as_view(), name="station-type-options"),
    path("station-types/<int:type_id>", views.StationTypeDetailAPIView.as_view(), name="station-type-detail"),
]
