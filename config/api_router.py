from django.conf import settings
from django.urls import include, path
from rest_framework.routers import DefaultRouter, SimpleRouter

if settings.DEBUG:
    router = DefaultRouter(trailing_slash=False)
else:
    router = SimpleRouter(trailing_slash=False)

app_name = "api"
urlpatterns = router.urls + [
    path("", include("core.users.api_urls")),
    path("", include("core.labs.api_urls")),
    path("", include("core.websocket.urls")),
    path("", include("core.support_desk.api_urls")),
]
