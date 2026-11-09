from django.urls import path

from .api import UserRefreshTokenView

urlpatterns = [
    path("refresh-token", UserRefreshTokenView.as_view(), name="refresh-token"),
]
