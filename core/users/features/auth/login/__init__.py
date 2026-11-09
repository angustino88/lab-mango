from django.urls import path

from .api import UserLoginView

urlpatterns = [
    path("login", UserLoginView.as_view(), name="login"),
]
