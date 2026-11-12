"""Every /api/labs/ route follows the Labs access policy (core/labs/features/base/access.py).

* No Labs role: nothing.
* Plain Labs user: reads the dashboard and the leaderboard (never writes there); reads and writes bench
  bookings (own bookings are enforced per object).
* Plain Labs user also reads the organisation lookups (departments, teams) other screens need
  (equipment R9, owner decision 2026-11-10).
* Coordinator and admin: everything.

The test walks the URL configuration, so a new Labs route that is not covered fails here.
"""

import itertools

import pytest
from django.contrib.auth.models import Group
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.test import APIClient, APIRequestFactory

from core.labs.features.equipment.api.common import ORGANIZATION_PERMISSIONS
from core.users.models import URSGroup
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

MEMBER_READ_FEATURES = ("dashboard", "leaderboard", "bench_bookings")
MEMBER_WRITE_FEATURES = ("bench_bookings",)
_factory = APIRequestFactory()
_URS_IDS = itertools.count(880000)


def _walk(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern), pattern.callback


def _labs_views():
    views = {}
    for route, callback in _walk(get_resolver().url_patterns):
        if route.startswith("api/labs/"):
            view_class = getattr(callback, "view_class", None) or getattr(callback, "cls", None)
            views.setdefault(view_class, route)
    return views


def _feature(view_class) -> str:
    parts = view_class.__module__.split(".")
    return parts[3] if parts[:3] == ["core", "labs", "features"] else view_class.__module__


def _user(username, role=None):
    user = UserFactory(username=username)
    if role:
        group = Group.objects.create(name=f"access-policy-{username}")
        URSGroup.objects.create(group=group, urs_group_id=next(_URS_IDS), labs_role=role)
        user.groups.add(group)
    return user


def _permits(view_class, user, method) -> bool:
    request = getattr(_factory, method.lower())("/")
    request.user = user
    view = view_class()
    return all(permission.has_permission(request, view) for permission in view.get_permissions())


def test_every_labs_route_follows_the_policy():
    views = _labs_views()
    assert len(views) > 50, "Labs URL configuration was not found"
    no_role = _user("policy-none")
    plain = _user("policy-plain", "user")
    coordinator = _user("policy-coord", "coord")
    problems = []
    for view_class, route in sorted(views.items(), key=lambda item: item[1]):
        feature = _feature(view_class)
        methods = [m.upper() for m in ("get", "post", "put", "patch", "delete") if hasattr(view_class, f"handle_{m}")]
        read = "GET" in methods
        writes = [m for m in methods if m != "GET"]
        if read:
            expected_plain = feature in MEMBER_READ_FEATURES or view_class.permission_classes == ORGANIZATION_PERMISSIONS
            if _permits(view_class, no_role, "GET"):
                problems.append(f"{route}: no-role user can read")
            if _permits(view_class, plain, "GET") is not expected_plain:
                problems.append(f"{route}: plain user read should be {expected_plain}")
            if not _permits(view_class, coordinator, "GET"):
                problems.append(f"{route}: coordinator cannot read")
        if feature in MEMBER_READ_FEATURES and feature not in MEMBER_WRITE_FEATURES:
            writes = ["POST", "PUT", "PATCH", "DELETE"]  # read-only areas: deny even unimplemented writes
        for method in writes:
            if _permits(view_class, no_role, method):
                problems.append(f"{route}: no-role user can {method}")
            if feature not in MEMBER_WRITE_FEATURES and _permits(view_class, plain, method):
                problems.append(f"{route}: plain user can {method}")
    assert not problems, "Labs access policy violations:\n" + "\n".join(problems)


def test_plain_user_sees_dashboard_but_not_benches_or_equipment():
    client = APIClient()
    client.force_authenticate(user=_user("policy-http-plain", "user"))

    assert client.get("/api/labs/dashboard/summary").status_code == 200
    assert client.get("/api/labs/benches").status_code == 403
    assert client.get("/api/labs/equipment").status_code == 403


def test_coordinator_sees_benches():
    client = APIClient()
    client.force_authenticate(user=_user("policy-http-coord", "coord"))

    assert client.get("/api/labs/benches").status_code == 200


@pytest.mark.parametrize("enabled, expected", [(True, 200), (False, 401)])
def test_api_key_access_follows_the_setting(settings, enabled, expected):
    from rest_framework_api_key.models import APIKey

    settings.API_KEY_ACCESS_ENABLED = enabled
    _, key = APIKey.objects.create_key(name="policy-test-key")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {key}")

    assert client.get("/api/labs/dashboard/summary").status_code == expected
