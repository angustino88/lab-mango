"""HTTP filtering backends for equipment list endpoints."""

from django.core.exceptions import FieldError
from django.db.models import Q
from rest_framework.filters import BaseFilterBackend


class CustomSearchFilter(BaseFilterBackend):
    """Apply case-insensitive search across fields declared by the view."""

    search_param = "search"

    def filter_queryset(self, request, queryset, view):
        search_term = request.query_params.get(self.search_param, "").strip()
        if not search_term:
            return queryset

        query = Q()
        for field in getattr(view, "text_search_fields", ()):
            query |= Q(**{f"{field}__icontains": search_term})

        if not query.children:
            return queryset

        try:
            return queryset.filter(query).distinct()
        except FieldError as exc:
            raise ValueError(f"Invalid search field configured on {view.__class__.__name__}") from exc
