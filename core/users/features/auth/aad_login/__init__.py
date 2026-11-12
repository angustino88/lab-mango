from django.urls import path

from .api import CSRFTokenView, UserAADLoginView

urlpatterns = [
    path("csrf-token", CSRFTokenView.as_view(), name="csrf-token"),
    path("aad-login", UserAADLoginView.as_view(), name="aad-login"),
]
