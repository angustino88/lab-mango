"""Routes of the lab sessions feature (the agent push route lives in core.agents)."""

from django.urls import path

from . import views

urlpatterns = [
    path("lab-sessions", views.SessionLogListAPIView.as_view(), name="lab-session-list"),
]
