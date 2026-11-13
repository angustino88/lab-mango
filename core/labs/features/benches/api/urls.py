from django.urls import path

from . import views
from .reference_data import urlpatterns as reference_urlpatterns
from .views import BenchStatusSummaryAPIView

urlpatterns = [
    path("benches/status-summary", BenchStatusSummaryAPIView.as_view(), name="bench-status-summary"),
    path("benches", views.BenchListCreateAPIView.as_view(), name="bench-list-create"),
    path("benches/filters", views.BenchFiltersAPIView.as_view(), name="bench-filters"),
    path("benches/options", views.BenchSelectAPIView.as_view(), name="bench-options"),
    path("benches/reference-data", views.BenchReferenceDataAPIView.as_view(), name="bench-reference-data"),
    path("benches/<int:bench_id>", views.BenchDetailAPIView.as_view(), name="bench-detail"),
    path("benches/<int:bench_id>/equipment", views.BenchEquipmentListAPIView.as_view(), name="bench-equipment-list"),
    path("benches/<int:bench_id>/actions/place", views.BenchPlaceAPIView.as_view(), name="bench-action-place"),
    path(
        "benches/<int:bench_id>/actions/change-lifecycle",
        views.BenchLifecycleAPIView.as_view(),
        name="bench-action-change-lifecycle",
    ),
    path("benches/<int:bench_id>/actions/favorite", views.BenchFavoriteAPIView.as_view(), name="bench-action-favorite"),
    path("benches/<int:bench_id>/actions/unfavorite", views.BenchUnfavoriteActionAPIView.as_view(), name="bench-action-unfavorite"),
    path("bench-groups", views.BenchGroupListCreateAPIView.as_view(), name="bench-group-list-create"),
    path("bench-groups/options", views.BenchGroupOptionsAPIView.as_view(), name="bench-group-options"),
    path("bench-groups/<int:reference_id>", views.BenchGroupDetailAPIView.as_view(), name="bench-group-detail"),
    path("bench-types", views.BenchTypeListCreateAPIView.as_view(), name="bench-type-list-create"),
    path("bench-types/options", views.BenchTypeOptionsAPIView.as_view(), name="bench-type-options"),
    path("bench-types/<int:reference_id>", views.BenchTypeDetailAPIView.as_view(), name="bench-type-detail"),
]
urlpatterns += reference_urlpatterns
