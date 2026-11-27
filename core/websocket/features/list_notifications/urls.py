from django.urls import path

from .api import NotificationListCreateView
from .inbox import NotificationMarkAllReadView, NotificationMarkReadView, NotificationUnreadCountView

urlpatterns = [
    path("notifications", NotificationListCreateView.as_view(), name="notification-list-create"),
    path("notifications/unread-count", NotificationUnreadCountView.as_view(), name="notification-unread-count"),
    path(
        "notifications/actions/mark-all-read",
        NotificationMarkAllReadView.as_view(),
        name="notification-mark-all-read",
    ),
    path(
        "notifications/<int:notification_id>/actions/mark-read",
        NotificationMarkReadView.as_view(),
        name="notification-mark-read",
    ),
]
