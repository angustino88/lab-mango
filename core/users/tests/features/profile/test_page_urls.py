from django.test import override_settings
from django.urls import include, path, resolve, reverse

urlpatterns = [
    path("users/", include("core.users.urls", namespace="users")),
]


@override_settings(ROOT_URLCONF=__name__)
def test_user_detail_page_route_preserves_public_url_contract():
    url = reverse("users:detail", kwargs={"username": "jdoe"})

    assert url == "/users/jdoe/"
    assert resolve(url).view_name == "users:detail"
