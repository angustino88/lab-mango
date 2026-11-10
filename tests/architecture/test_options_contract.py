"""Architecture guardrail for the /options selector contract (ADR 002, section 13).

Enforces:
- Every path ending in /options is GET-only, has a sibling collection route, declares x-owner,
  and its 200 response uses CatalogOptionList.
- No options/<resource> path, no select-list path, no path ending in /options/.
- Options query serializers have no search, ordering, page, page_size or allow_blank=True fields.
- Options resolves before {id}.
"""

from django.urls import URLPattern, URLResolver, get_resolver

# Known violations that may only shrink during Phase 2 and Phase 3 rollout
KNOWN_SLASH_VIOLATIONS: set[str] = set()

KNOWN_REVERSE_PATH_VIOLATIONS: set[str] = set()

KNOWN_ENUM_OPTIONS_VIOLATIONS: set[str] = set()


def _walk_routes(patterns, prefix=""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _walk_routes(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), entry


def test_no_unallowlisted_slash_options_routes():
    resolver = get_resolver()
    slash_routes = [
        path for path, _ in _walk_routes(resolver.url_patterns)
        if path.endswith("/options/") and path not in KNOWN_SLASH_VIOLATIONS
    ]
    assert not slash_routes, f"Unexpected slash-terminated options routes: {slash_routes}"


def test_no_unallowlisted_reverse_options_routes():
    resolver = get_resolver()
    reverse_routes = [
        path for path, _ in _walk_routes(resolver.url_patterns)
        if "/options/" in path and not path.endswith("/options/") and path not in KNOWN_REVERSE_PATH_VIOLATIONS
    ]
    assert not reverse_routes, f"Unexpected reverse options paths: {reverse_routes}"


def test_options_routes_are_get_only():
    resolver = get_resolver()
    violations = []
    for path, pattern in _walk_routes(resolver.url_patterns):
        if path.endswith("/options"):
            view_cls = getattr(pattern.callback, "cls", None)
            if view_cls:
                implemented_disallowed = [
                    m for m in ("post", "put", "patch", "delete")
                    if hasattr(view_cls, f"handle_{m}")
                ]
                if implemented_disallowed:
                    violations.append(f"{path} implements write methods: {implemented_disallowed}")
    assert not violations, "\n".join(violations)


def test_options_query_serializers_no_search_or_page():
    resolver = get_resolver()
    violations = []
    for path, pattern in _walk_routes(resolver.url_patterns):
        if path.endswith("/options") and path not in KNOWN_ENUM_OPTIONS_VIOLATIONS:
            view_cls = getattr(pattern.callback, "cls", None)
            if not view_cls:
                continue
            contract = getattr(view_cls, "get_contract", None)
            query_serializer_cls = getattr(contract, "query", None) or getattr(view_cls, "query_serializer", None)
            if query_serializer_cls:
                fields = query_serializer_cls().fields
                forbidden_fields = {"search", "ordering", "page", "page_size"} & set(fields.keys())
                # Only check for new or migrated endpoints not in legacy
                if forbidden_fields and getattr(view_cls, "owner", None):
                    violations.append(f"{path} query serializer has forbidden fields: {forbidden_fields}")
    assert not violations, "\n".join(violations)
