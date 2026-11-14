"""Free-text search is `q`; `search` is a deprecated alias (request standard QRY-7, CMP-3)."""

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


def test_search_is_mapped_onto_the_same_term():
    assert _validated(_Query, {"search": "bench"}) == {"q": "bench"}
    assert _validated(_LegacyTarget, {"q": "bench"}) == {"search": "bench"}


def test_blank_search_means_no_search():
    assert _validated(_Query, {"search": ""}) == {}


def test_both_names_together_are_rejected():
    serializer = _Query(data={"q": "a", "search": "b"})
    assert not serializer.is_valid()
    assert "search" in serializer.errors
