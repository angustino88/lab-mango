"""URL routing for the monitoring event HTTP API."""

from django.urls import path

from .connections import (
    DeviceConnectionDetailAPIView,
    DeviceConnectionLinkActionAPIView,
    DeviceConnectionListAPIView,
    DeviceConnectionSummaryAPIView,
    ExpectedDeviceDetailAPIView,
    ExpectedDeviceListCreateAPIView,
    LegacyDeviceSuggestionListAPIView,
)
from .views import (
    MonitoringEventDetailAPIView,
    MonitoringEventExportAPIView,
    MonitoringEventListCreateAPIView,
)

urlpatterns = [
    path("device-connections", DeviceConnectionListAPIView.as_view(), name="device-connection-list"),
    path("device-connections/summary", DeviceConnectionSummaryAPIView.as_view(), name="device-connection-summary"),
    path(
        "device-connections/<int:connection_id>",
        DeviceConnectionDetailAPIView.as_view(),
        name="device-connection-detail",
    ),
    path(
        "device-connections/<int:connection_id>/actions/link",
        DeviceConnectionLinkActionAPIView.as_view(),
        name="device-connection-action-link",
    ),
    path("expected-devices", ExpectedDeviceListCreateAPIView.as_view(), name="expected-device-list-create"),
    path(
        "expected-devices/legacy-suggestions",
        LegacyDeviceSuggestionListAPIView.as_view(),
        name="expected-device-legacy-suggestions",
    ),
    path(
        "expected-devices/<int:expected_device_id>",
        ExpectedDeviceDetailAPIView.as_view(),
        name="expected-device-detail",
    ),
    path("monitoring-events", MonitoringEventListCreateAPIView.as_view(), name="monitoring-event-list-create"),
    path("monitoring-events/<int:pk>", MonitoringEventDetailAPIView.as_view(), name="monitoring-event-detail"),
    path("monitoring-events/export", MonitoringEventExportAPIView.as_view(), name="monitoring-event-export"),
]
