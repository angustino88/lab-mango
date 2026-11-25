from django.urls import path

from ..targets import TARGETS
from .views import AssetDetailView, AssetListView, SelectionDetailView, SelectionListView

urlpatterns = [
    path("visual-model-assets", AssetListView.as_view(), name="visual-model-asset-list"),
    path("visual-model-assets/<int:asset_id>", AssetDetailView.as_view(), name="visual-model-asset-detail"),
]
# One concrete route per resource kind: the model a station, bench, device or catalog row shows.
for segment in TARGETS:
    urlpatterns += [
        path(
            f"visual-model-selections/{segment}",
            SelectionListView.as_view(),
            {"segment": segment},
            name=f"visual-model-selection-list-{segment}",
        ),
        path(
            f"{segment}/<int:pk>/visual-model",
            SelectionDetailView.as_view(),
            {"segment": segment},
            name=f"visual-model-selection-{segment}",
        ),
    ]
