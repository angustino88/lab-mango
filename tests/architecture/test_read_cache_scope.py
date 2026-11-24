"""Architecture guardrail: a globally scoped read cache must not hold user-dependent output.

``AppAPIView`` shares one cache entry across every caller when ``read_cache_scope == "global"``.
A view whose GET path reads the caller (``request.user``, ``acting_user`` or an ``actor``
argument) must use ``read_cache_scope = "user"`` instead, or prove the value is ignored.
"""

import inspect
import re

from django.urls import URLPattern, URLResolver, get_resolver

from core.common.api.api_views import AppAPIView

# Methods on the GET path that features override.
_GET_PATH_METHODS = (
    "handle_get",
    "select",
    "get_queryset",
    "prepare_list_results",
    "get_serializer_context",
)
_USER_DEPENDENT = re.compile(r"request\.user|acting_user|\bactor\s*=\s*(?!None\b)")

# Reviewed: the actor is used only for an access check that DRF permission_classes and JWT
# authentication already enforce before the cache lookup (authenticated, active user); the rows
# returned do not depend on the actor (core/reference_data/queries.py list_references).
REVIEWED_ACTOR_INDEPENDENT = {
    "core.common.api.reference_views.reference_urlpatterns.<locals>.Collection.handle_get",
}


def _walk_views(patterns):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _walk_views(entry.url_patterns)
        elif isinstance(entry, URLPattern):
            view_class = getattr(entry.callback, "view_class", None) or getattr(entry.callback, "cls", None)
            if isinstance(view_class, type) and issubclass(view_class, AppAPIView):
                yield view_class


def _user_dependent_get_methods(view_class: type[AppAPIView]) -> list[str]:
    hits = []
    for name in _GET_PATH_METHODS:
        for owner in view_class.__mro__:
            method = owner.__dict__.get(name)
            if method is None:
                continue
            if owner.__module__.startswith("core.common."):
                break  # shared plumbing; the user dependency lives in feature overrides
            try:
                source = inspect.getsource(method)
            except (OSError, TypeError):
                break
            qualified = f"{method.__module__}.{method.__qualname__}"
            if _USER_DEPENDENT.search(source) and qualified not in REVIEWED_ACTOR_INDEPENDENT:
                hits.append(qualified)
            break
    return hits


def test_globally_cached_views_do_not_read_the_caller():
    violations = {}
    for view_class in set(_walk_views(get_resolver().url_patterns)):
        if not view_class.read_cache_namespace or view_class.read_cache_scope != "global":
            continue
        if getattr(view_class, "select_uses_actor", False):
            violations[view_class.__qualname__] = ["select_uses_actor = True"]
            continue
        hits = _user_dependent_get_methods(view_class)
        if hits:
            violations[view_class.__qualname__] = hits
    assert not violations, "Globally cached views read the caller; use read_cache_scope = 'user':\n" + "\n".join(
        f"{name}: {hits}" for name, hits in sorted(violations.items())
    )


def test_guard_detects_user_dependent_handler():
    class _Leaky(AppAPIView):
        read_cache_namespace = "ns:test"
        read_cache_ttl = 30

        def handle_get(self, request, *args, **kwargs):
            return self.respond(request.user)  # never executed; only scanned

    assert _user_dependent_get_methods(_Leaky)
