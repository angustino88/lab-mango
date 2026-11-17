"""URL routing for the monitoring event HTTP API."""

from django.urls import path

from .connections import DeviceConnectionListAPIView
from .views import (
    MonitoringEventDetailAPIView,
    MonitoringEventExportAPIView,
    MonitoringEventListCreateAPIView,
)

urlpatterns = [
    path("device-connections", DeviceConnectionListAPIView.as_view(), name="device-connection-list"),
    path("monitoring-events", MonitoringEventListCreateAPIView.as_view(), name="monitoring-event-list-create"),
    path("monitoring-events/<int:pk>", MonitoringEventDetailAPIView.as_view(), name="monitoring-event-detail"),
    path("monitoring-events/export", MonitoringEventExportAPIView.as_view(), name="monitoring-event-export"),
]
