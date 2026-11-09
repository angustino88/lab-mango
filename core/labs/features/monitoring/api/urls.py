"""URL routing for the monitoring event HTTP API."""
from django.urls import path

from .views import (
    ExportLabMonitoringAPIView,
    ListCreateLabMonitoringAPIView,
    MonitoringEventDetailAPIView,
    MonitoringEventExportAPIView,
    MonitoringEventListCreateAPIView,
)

urlpatterns = [
    path("monitoring-events", MonitoringEventListCreateAPIView.as_view(), name="monitoring-event-list-create"),
    path("monitoring-events/<int:pk>", MonitoringEventDetailAPIView.as_view(), name="monitoring-event-detail"),
    path("monitoring-events/export", MonitoringEventExportAPIView.as_view(), name="monitoring-event-export"),
    # Compatibility aliases
    path("lab-monitoring", ListCreateLabMonitoringAPIView.as_view(), name="lab-monitoring"),
    path("lab-monitoring/export", ExportLabMonitoringAPIView.as_view(), name="lab-monitoring-export"),
]
