"""URL patterns for agent operator lifecycle and device API."""

from django.urls import path

from .views import (
    AgentDecommissionActionAPIView,
    AgentDetailAPIView,
    AgentGrantCreateAPIView,
    AgentListCreateAPIView,
    AgentRevokeActionAPIView,
    AgentEnrollmentAPIView,
    AgentActivityAPIView,
    AgentHeartbeatAPIView,
    AgentInfoAPIView,
)

urlpatterns = [
    path("api/agents", AgentListCreateAPIView.as_view(), name="agent-list-create"),
    path("api/agents/<int:pk>", AgentDetailAPIView.as_view(), name="agent-detail"),
    path("api/agents/<int:pk>/enrollment-grants", AgentGrantCreateAPIView.as_view(), name="agent-grant-create"),
    path("api/agents/<int:pk>/actions/revoke", AgentRevokeActionAPIView.as_view(), name="agent-action-revoke"),
    path(
        "api/agents/<int:pk>/actions/decommission",
        AgentDecommissionActionAPIView.as_view(),
        name="agent-action-decommission",
    ),
    path("agent/info", AgentInfoAPIView.as_view(), name="agent-info"),
    path("agent/enrollments", AgentEnrollmentAPIView.as_view(), name="agent-enrollment"),
    path("agent/heartbeat", AgentHeartbeatAPIView.as_view(), name="agent-heartbeat"),
    path("agent/equipment/activity", AgentActivityAPIView.as_view(), name="agent-equipment-activity"),
]
