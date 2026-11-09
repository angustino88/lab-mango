from django.urls import include, path

urlpatterns = [path("api/", include("core.users.features.auth.urls"))]
urlpatterns += [path("users/", include("core.users.urls", namespace="users"))]
