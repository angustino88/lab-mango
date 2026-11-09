from django.urls import path

from .api import UserAvatarView

urlpatterns = [
    path("users/avatar", UserAvatarView.as_view(), name="user-avatar"),
]
