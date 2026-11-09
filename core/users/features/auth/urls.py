from django.conf import settings
from django.urls import include, path

urlpatterns = [
    path("", include("core.users.features.auth.aad_login.urls")),
    path("", include("core.users.features.auth.refresh_token.urls")),
    path("", include("core.users.features.auth.logout.urls")),
]

if not settings.ENTRA_SSO_ONLY:
    urlpatterns += [
        path("", include("core.users.features.auth.login.urls")),
        path("", include("core.users.features.auth.send_otp.urls")),
    ]
