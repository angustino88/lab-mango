from django.urls import path

from . import views

urlpatterns = [
    path("resources/lookup", views.ResourceLookupAPIView.as_view(), name="resource-lookup"),
]
