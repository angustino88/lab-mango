from django.urls import path

from . import views
from .views import RoomStatusSummaryAPIView

urlpatterns = [
    path("rooms/status-summary", RoomStatusSummaryAPIView.as_view(), name="room-status-summary"),
    path("rooms", views.RoomListCreateAPIView.as_view(), name="room-list-create"),
    path("rooms/options", views.RoomOptionsAPIView.as_view(), name="room-options"),
    path("rooms/filters", views.RoomFiltersAPIView.as_view(), name="room-filters"),
    path("rooms/<int:room_id>", views.RoomDetailAPIView.as_view(), name="room-detail"),
    path("rooms/<int:room_id>/slots", views.RoomSlotListAPIView.as_view(), name="room-slot-list"),
    path("rooms/<int:room_id>/actions/generate-slots", views.RoomSlotGenerateAPIView.as_view(), name="room-action-generate-slots"),
    path(
        "rooms/<int:room_id>/actions/change-lifecycle",
        views.RoomLifecycleAPIView.as_view(),
        name="room-action-change-lifecycle",
    ),
    path("rooms/<int:room_id>/actions/change-status", views.RoomStatusAPIView.as_view(), name="room-action-change-status"),
    path("rooms/<int:room_id>/history", views.RoomHistoryAPIView.as_view(), name="room-history"),
    path(
        "rooms/<int:room_id>/observations",
        views.RoomObservationListCreateAPIView.as_view(),
        name="room-observation-list-create",
    ),
]
