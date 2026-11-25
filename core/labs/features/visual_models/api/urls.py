from django.urls import path

from .views import AssetDetailView, AssetListView, AssignmentDetailView, AssignmentListView

urlpatterns = [
    path("visual-model-assets", AssetListView.as_view(), name="visual-model-asset-list"),
    path("visual-model-assets/<int:asset_id>", AssetDetailView.as_view(), name="visual-model-asset-detail"),
    path("visual-model-assignments", AssignmentListView.as_view(), name="visual-model-assignment-list"),
    path(
        "visual-model-assignments/<str:scope>/<str:target_key>",
        AssignmentDetailView.as_view(),
        name="visual-model-assignment-detail",
    ),
]
