from django.urls import include, path

app_name = "websocket"

urlpatterns = [
    path("", include("core.websocket.features.list_notifications.urls")),
]
