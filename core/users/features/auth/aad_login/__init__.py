from django.urls import path

from .api import UserAADLoginView

urlpatterns = [
    path("aad-login", UserAADLoginView.as_view(), name="aad-login"),
]
