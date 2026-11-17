from rest_framework import serializers
from rest_framework.exceptions import ParseError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


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


class ResultsSetPagination(PageNumberPagination):
    """Canonical bounded page-number pagination for the redesigned API."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100

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
