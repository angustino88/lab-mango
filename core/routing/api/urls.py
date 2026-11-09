"""Internal routing sync URL patterns (no trailing slash)."""

from django.urls import path

from .views import SyncChangesView, SyncDigestView, SyncInfoView, SyncSnapshotView

urlpatterns = [
    path("info", SyncInfoView.as_view(), name="routing-sync-info"),
    path("snapshot/<str:entity>", SyncSnapshotView.as_view(), name="routing-sync-snapshot"),
    path("changes/<str:entity>", SyncChangesView.as_view(), name="routing-sync-changes"),
    path("digest/<str:entity>", SyncDigestView.as_view(), name="routing-sync-digest"),
]
