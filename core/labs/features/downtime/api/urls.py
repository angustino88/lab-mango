from django.urls import path

from . import views

urlpatterns = [
    path("downtimes", views.DowntimeListCreateAPIView.as_view(), name="downtime-list-create"),
    path("downtimes/<int:downtime_id>", views.DowntimeDetailAPIView.as_view(), name="downtime-detail"),
    path("downtimes/<int:downtime_id>/actions/end", views.DowntimeEndAPIView.as_view(), name="downtime-action-end"),
    path(
        "downtimes/<int:downtime_id>/actions/cancel",
        views.DowntimeCancelAPIView.as_view(),
        name="downtime-action-cancel",
    ),
]
