from django.urls import path

from .api import UserLogoutView

urlpatterns = [
    path("logout", UserLogoutView.as_view(), name="logout"),
]
