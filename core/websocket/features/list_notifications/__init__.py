from django.urls import path

from .api import NotificationListCreateView

urlpatterns = [
    path("notifications", NotificationListCreateView.as_view(), name="notification-list-create"),
]
