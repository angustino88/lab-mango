import hashlib
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any

from django.conf import settings
from django.core.paginator import Paginator
from django.utils import timezone
from django.utils.functional import cached_property
from rest_framework import serializers
from rest_framework.exceptions import ParseError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from core.common.cache import get_namespace_version, safe_cache_get, safe_cache_set


class PageNumberQuerySerializer(serializers.Serializer):
    """Document the standard page-number query parameters for collection endpoints."""

    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100)


PAGE_QUERY_PARAMS = frozenset(PageNumberQuerySerializer().fields)


def with_page_query(query_serializer: type[serializers.Serializer]) -> type[serializers.Serializer]:
    """Add the documented ``page`` and ``page_size`` parameters to a paginated list's query.

    The paginator reads both from the request; declaring them puts them in the OpenAPI
    contract beside the paginated response. Option selectors never page (ADR 002), so
    wrap the list contract, not a serializer shared with an options endpoint.
    """
    return type(
        f"{query_serializer.__name__}WithPage",
        (query_serializer, PageNumberQuerySerializer),
        {"__module__": query_serializer.__module__},
    )


_CLOCK_PARAM_WINDOW = timedelta(minutes=2)


def _has_clock_param(params: Any) -> bool:
    """Whether a bound SQL parameter looks like ``timezone.now()`` taken while building the query."""
    now = timezone.now()
    for param in params or ():
        if isinstance(param, datetime):
            aware = param if timezone.is_aware(param) else timezone.make_aware(param, dt_timezone.utc)
            if abs(now - aware) <= _CLOCK_PARAM_WINDOW:
                return True
    return False


class _CachedCountPaginator(Paginator):
    """Django Paginator that caches exact ``COUNT(*)`` per versioned namespace and SQL filter."""

    def __init__(self, object_list: Any, per_page: int, *, cache_namespace: str, cache_ttl: int, **kwargs: Any):
        super().__init__(object_list, per_page, **kwargs)
        self._cache_namespace = cache_namespace
        self._cache_ttl = cache_ttl

    @cached_property
    def count(self) -> int:
        query = getattr(self.object_list, "query", None)
        if query is None or self._cache_ttl <= 0:
            return super().count
        ns_ver = get_namespace_version(self._cache_namespace)
        if ns_ver == 0:
            return super().count
        try:
            counted = self.object_list.order_by()
            sql, params = counted.query.get_compiler(using=counted.db).as_sql()
        except Exception:  # noqa: BLE001
            return super().count
        if _has_clock_param(params):
            # A filter bound to "now" in Python yields a new key per request: never hits, only pollutes.
            return super().count
        sql_key = f"{sql}|{params!r}"
        sql_hash = hashlib.sha256(sql_key.encode("utf-8")).hexdigest()[:32]
        cache_key = f"api:count:{self._cache_namespace}:v{ns_ver}:{sql_hash}"
        cached = safe_cache_get(cache_key)
        if cached is not None:
            return int(cached)
        total = super().count
        safe_cache_set(cache_key, int(total), timeout=self._cache_ttl)
        return total


class ResultsSetPagination(PageNumberPagination):
    """Canonical bounded page-number pagination for the redesigned API."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        namespace = getattr(view, "read_cache_namespace", None) if view is not None else None
        count_ttl = int(getattr(settings, "API_PAGINATION_COUNT_CACHE_TTL", 15) or 0)
        if namespace and count_ttl > 0 and getattr(settings, "API_READ_CACHE_ENABLED", False):
            self.django_paginator_class = lambda object_list, per_page, **kw: _CachedCountPaginator(  # type: ignore[assignment]
                object_list,
                per_page,
                cache_namespace=namespace,
                cache_ttl=count_ttl,
                **kw,
            )
        return super().paginate_queryset(queryset, request, view=view)

    def get_page_size(self, request):
        raw_page_size = request.query_params.get(self.page_size_query_param)
        if raw_page_size is not None:
            if not raw_page_size.isascii() or not raw_page_size.isdecimal() or int(raw_page_size) < 1:
                raise ParseError({"page_size": "Enter a positive integer."})
            if int(raw_page_size) > self.max_page_size:
                raise ParseError({"page_size": f"Ensure this value is less than or equal to {self.max_page_size}."})
        return super().get_page_size(request)

    def get_paginated_response(self, data):
        return Response(
            {
                "data": data,
                "meta": {
                    "pagination": {
                        "count": self.page.paginator.count,
                        "page": self.page.number,
                        "page_size": self.get_page_size(self.request),
                        "next": self.get_next_link(),
                        "previous": self.get_previous_link(),
                    }
                },
            }
        )
