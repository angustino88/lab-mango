from django.urls import path

from . import views

urlpatterns = [
    path("telemetry/metrics", views.MetricListAPIView.as_view(), name="telemetry-metric-list"),
    path(
        "telemetry/device-profiles",
        views.DeviceProfileListCreateAPIView.as_view(),
        name="telemetry-device-profile-list-create",
    ),
    path(
        "telemetry/device-profiles/<int:profile_id>",
        views.DeviceProfileDetailAPIView.as_view(),
        name="telemetry-device-profile-detail",
    ),
    path(
        "telemetry/device-profiles/<int:profile_id>/actions/approve",
        views.DeviceProfileApproveAPIView.as_view(),
        name="telemetry-device-profile-approve",
    ),
    path("telemetry/devices", views.DeviceListAPIView.as_view(), name="telemetry-device-list"),
    path("telemetry/devices/<int:device_id>", views.DeviceDetailAPIView.as_view(), name="telemetry-device-detail"),
    path(
        "telemetry/devices/<int:device_id>/actions/claim",
        views.DeviceClaimAPIView.as_view(),
        name="telemetry-device-claim",
    ),
    path(
        "telemetry/devices/<int:device_id>/actions/retire",
        views.DeviceRetireAPIView.as_view(),
        name="telemetry-device-retire",
    ),
    path("telemetry/gateways", views.GatewayCreateAPIView.as_view(), name="telemetry-gateway-create"),
    path(
        "telemetry/gateways/<int:device_id>/actions/bind-scope",
        views.GatewayScopeAPIView.as_view(),
        name="telemetry-gateway-bind-scope",
    ),
    path("telemetry/sources", views.SourceCreateAPIView.as_view(), name="telemetry-source-create"),
    path("telemetry/sources/<int:device_id>", views.SourceDetailAPIView.as_view(), name="telemetry-source-detail"),
    path(
        "telemetry/sources/<int:device_id>/channels",
        views.SourceChannelListAPIView.as_view(),
        name="telemetry-source-channels",
    ),
    path(
        "telemetry/sources/<int:device_id>/actions/bind-target",
        views.SourceBindTargetAPIView.as_view(),
        name="telemetry-source-bind-target",
    ),
    path("telemetry/channels/<int:channel_id>", views.ChannelDetailAPIView.as_view(), name="telemetry-channel-detail"),
    path(
        "telemetry/channels/<int:channel_id>/actions/bind-target",
        views.ChannelBindTargetAPIView.as_view(),
        name="telemetry-channel-bind-target",
    ),
    path(
        "telemetry/channels/<int:channel_id>/actions/unbind",
        views.ChannelUnbindAPIView.as_view(),
        name="telemetry-channel-unbind",
    ),
    path(
        "telemetry/targets/<str:target_type>/<int:resource_id>",
        views.TargetOverviewAPIView.as_view(),
        name="telemetry-target-overview",
    ),
]
