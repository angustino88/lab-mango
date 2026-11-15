"""Free-text search query parameter (response standard COL-3, request standard QRY-7).

``q`` is the only parameter; the former ``search`` alias is removed.
"""

from typing import Any

from rest_framework import serializers


class SearchQueryMixin(serializers.Serializer):
    """Adds ``q``; validated data carries the term under ``search_target``.

    ``search_target`` is the key the owner's query code reads (``q`` by default), so internal code keeps its name.
    """

    search_target = "q"

    q = serializers.CharField(required=False, min_length=1, max_length=200, help_text="Free-text search term.")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        term = attrs.pop("q", None)
        if term:
            attrs[self.search_target] = term
        return attrs


__all__ = ["SearchQueryMixin"]
