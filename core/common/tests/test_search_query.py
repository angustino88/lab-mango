"""Free-text search is `q`; the former `search` alias is removed (request standard QRY-7)."""

from core.common.api.search import SearchQueryMixin


class _Query(SearchQueryMixin):
    pass


class _LegacyTarget(SearchQueryMixin):
    search_target = "search"


def _validated(serializer_class, data):
    serializer = serializer_class(data=data)
    assert serializer.is_valid(), serializer.errors
    return serializer.validated_data


def test_q_is_the_parameter():
    assert _validated(_Query, {"q": "bench"}) == {"q": "bench"}


def test_q_lands_under_the_owner_target_key():
    assert _validated(_LegacyTarget, {"q": "bench"}) == {"search": "bench"}


def test_search_is_no_longer_a_field():
    assert "search" not in _Query().fields
