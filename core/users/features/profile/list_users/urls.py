from django.urls import path

from .api import ListUsersView, RetrieveUserView

urlpatterns = [
    path("users/<int:pk>", RetrieveUserView.as_view(), name="user-detail"),
    path("users", ListUsersView.as_view(), name="user-list"),
]
