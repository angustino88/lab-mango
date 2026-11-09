from django.urls import include, path

urlpatterns = [
    path("", include("core.users.features.groups.list_groups.urls")),
]
