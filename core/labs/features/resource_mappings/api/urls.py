"""Slashless URL routes for resource mapping reads."""

from django.urls import path

from .views import BenchMappingAPIView, EquipmentMappingAPIView, RoomMappingAPIView, StationMappingAPIView

urlpatterns = [
    path("rooms/<int:resource_id>/mapping", RoomMappingAPIView.as_view(), name="room-mapping"),
    path("stations/<int:resource_id>/mapping", StationMappingAPIView.as_view(), name="station-mapping"),
    path("benches/<int:resource_id>/mapping", BenchMappingAPIView.as_view(), name="bench-mapping"),
    path("equipment/<int:resource_id>/mapping", EquipmentMappingAPIView.as_view(), name="equipment-mapping"),
]
