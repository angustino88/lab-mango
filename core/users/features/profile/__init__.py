from django.urls import include, path

urlpatterns = [
    path("", include("core.users.features.profile.get_me.urls")),
    path("", include("core.users.features.profile.avatar.urls")),
    path("", include("core.users.features.profile.list_users.urls")),
]
