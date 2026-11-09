from django.urls import path

from .api import GetMeView

urlpatterns = [
    path("users/me", GetMeView.as_view(), name="user-me"),
]
