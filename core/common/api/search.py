"""Free-text search query parameter (response standard COL-3, request standard QRY-7).

``q`` is the parameter. ``search`` is accepted as a deprecated alias for one release (VER-3, CMP-3): the schema
marks it ``deprecated`` (``config/schema.py``) and responses to requests that use it carry ``Deprecation: true``
(``AppAPIView.finalize_response``).
"""

from typing import Any

from rest_framework import serializers

DEPRECATED_SEARCH_PARAM = "search"
SEARCH_ALIAS_DESCRIPTION = "Deprecated alias of `q` (QRY-7); send `q`. Kept for one release."


class SearchQueryMixin(serializers.Serializer):
    """Adds ``q`` and the deprecated ``search`` alias; validated data carries the term under ``search_target``.

    ``search_target`` is the key the owner's query code reads (``q`` by default), so internal code keeps its name.
    """

    search_target = "q"

    q = serializers.CharField(required=False, min_length=1, max_length=200, help_text="Free-text search term.")
    search = serializers.CharField(
        required=False, allow_blank=True, max_length=255, help_text=SEARCH_ALIAS_DESCRIPTION
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if "q" in attrs and DEPRECATED_SEARCH_PARAM in attrs:
            raise serializers.ValidationError(
                {DEPRECATED_SEARCH_PARAM: "Send `q` only; `search` is its deprecated alias."}
            )
        term = attrs.pop("q", None) or attrs.pop(DEPRECATED_SEARCH_PARAM, None) or None
        attrs.pop(DEPRECATED_SEARCH_PARAM, None)
        if term:
            attrs[self.search_target] = term
        return attrs


__all__ = ["DEPRECATED_SEARCH_PARAM", "SEARCH_ALIAS_DESCRIPTION", "SearchQueryMixin"]
