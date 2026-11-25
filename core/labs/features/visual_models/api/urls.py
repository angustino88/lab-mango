from django.urls import path

from .views import ModelDetailView, ModelListView

urlpatterns = [
    path("visual-models", ModelListView.as_view(), name="visual-model-list"),
    path("visual-models/<str:scope>/<str:target_key>", ModelDetailView.as_view(), name="visual-model-detail"),
]
