"""User-domain page URL aggregator."""

from django.urls import include, path

app_name = "users"

urlpatterns = [
    path("", include("core.users.features.profile.page_urls")),
]
