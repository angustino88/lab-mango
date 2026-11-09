from django.urls import path

from .api import ListGroupUserView

urlpatterns = [
    path("user-groups", ListGroupUserView.as_view(), name="user-groups"),
]
