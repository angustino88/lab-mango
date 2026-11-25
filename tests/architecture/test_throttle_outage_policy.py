"""Architecture guardrail: every throttle on API traffic declares what a cache outage does.

Stock DRF throttles raise whatever the cache raises, which turns a Redis outage into a 500 on every
request they guard. Each throttle must either mix in ``OutageAwareThrottleMixin`` with an explicit
``outage_policy`` or be listed below as a reviewed fail-closed throttle.
"""

from typing import Any

from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.settings import api_settings
from rest_framework.throttling import ScopedRateThrottle

from core.common.api.throttling import throttle_outage_policy

# Reviewed: authentication endpoints fail closed by design. Their views route Redis errors to
# 503 service_unavailable + Retry-After (core/users/features/auth/api.py::auth_exception_handler),
# covered by core/users/tests/features/auth/test_cache_outage.py.
REVIEWED_FAIL_CLOSED = {
    (ScopedRateThrottle, "auth_login"),
    (ScopedRateThrottle, "auth_refresh"),
    (ScopedRateThrottle, "auth_otp"),
}


def _walk_views(patterns):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _walk_views(entry.url_patterns)
        elif isinstance(entry, URLPattern):
            view_class = getattr(entry.callback, "view_class", None) or getattr(entry.callback, "cls", None)
            if isinstance(view_class, type):
                yield view_class


def test_default_throttles_declare_an_outage_policy():
    default_classes: Any = api_settings.DEFAULT_THROTTLE_CLASSES  # classes at runtime
    for throttle_class in default_classes:
        assert throttle_outage_policy(throttle_class) == "allow", throttle_class


def test_every_view_throttle_declares_an_outage_policy():
    violations = set()
    for view_class in set(_walk_views(get_resolver().url_patterns)):
        for throttle_class in getattr(view_class, "throttle_classes", ()) or ():
            if throttle_outage_policy(throttle_class) is not None:
                continue
            scope = getattr(view_class, "throttle_scope", None)
            if (throttle_class, scope) in REVIEWED_FAIL_CLOSED:
                continue
            violations.add(f"{view_class.__module__}.{view_class.__qualname__}: {throttle_class.__name__}")
    assert not violations, "Throttles without an outage policy:\n" + "\n".join(sorted(violations))
