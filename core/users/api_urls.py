"""Users module API URL aggregator.

All user-domain endpoints are declared in their feature-level urls.py and
collected here. config/api_router.py does a single include() of this file.
"""
from django.urls import include, path

urlpatterns = [
    path("", include("core.users.features.auth.urls")),
    path("", include("core.users.features.profile.urls")),
    path("", include("core.users.features.groups.urls")),
]
