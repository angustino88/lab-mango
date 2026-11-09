from django.urls import path

from .api import UserAADChallengeView, UserAADLoginView

urlpatterns = [
    path("aad-login/challenge", UserAADChallengeView.as_view(), name="aad-login-challenge"),
    path("aad-login", UserAADLoginView.as_view(), name="aad-login"),
]
