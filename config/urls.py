from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from django.http import HttpResponse
from drf_spectacular.views import SpectacularSwaggerView

from core.users.features.auth.admin_login.api import DjangoAdminSiteCustomLoginView

def healthz(request):
    return HttpResponse("OK", status=200)

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("ready", healthz, name="ready"),
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    # Admin login redirects to Entra in production; must precede admin.site.urls.
    path(f"{settings.ADMIN_URL}login/", DjangoAdminSiteCustomLoginView.as_view(), name="admin-login"),
    path(settings.ADMIN_URL, admin.site.urls),
    # allauth
    # API
    path("api/", include("config.api_router")),
    # Internal routing sync API (dedicated private listener/mount, separate from /api/)
    path("internal/", include("core.routing.urls")),
    # Agent platform API (operator lifecycle and device routes)
    path("", include("core.agents.urls")),
    # Users (profile pages namespace)
    path("users/", include("core.users.urls", namespace="users")),
    # OpenAPI schema
    path("api/schema/", include("config.features.schema.urls")),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-swagger-ui",
    ),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if not settings.ENTRA_SSO_ONLY:
    urlpatterns += [path("accounts/", include("allauth.urls"))]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,  document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    # Only mount the toolbar when it is installed; it is not in production INSTALLED_APPS.
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
