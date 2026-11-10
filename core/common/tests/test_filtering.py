"""Contract tests for the shared wire format, independent of business models."""

from unittest.mock import Mock

import pytest
from django.http import QueryDict
from rest_framework import serializers

from core.common.api.filtering import Filter, FilterSpec, PositiveIDField, QueryDateTimeField, StrictBooleanField


@pytest.fixture
def spec():
    return FilterSpec(
        [
            Filter("type_id", PositiveIDField(), "type_id", "reference", multiple=True),
            Filter("status", serializers.ChoiceField(choices=["active", "retired"]), "status", "enum", multiple=True),
            Filter("favorite", StrictBooleanField(required=False), "favorite", "boolean"),
            Filter("created_after", QueryDateTimeField(required=False), "created__gte", "datetime"),
            Filter("created_before", QueryDateTimeField(required=False), "created__lt", "datetime"),
        ],
        search_fields=("sku", "name"),
        ordering={"sku": "sku", "created_at": "created"},
        default_ordering=("sku",),
        ranges=(("created_after", "created_before"),),
        search_alias=True,
    )


def test_csv_and_combined_fields_are_typed(spec):
    serializer = spec.serializer("TestQuery")(data=QueryDict("type_id=1,2&status=active,retired&favorite=false&q=abc"))
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {
        "type_id": [1, 2],
        "status": ["active", "retired"],
        "favorite": False,
        "q": "abc",
    }


@pytest.mark.parametrize(
    "query,field",
    [
        ("type_id=", "type_id"),
        ("type_id=1,", "type_id"),
        ("type_id=1,1", "type_id"),
        ("type_id=01", "type_id"),
        ("type_id=0", "type_id"),
        ("type_id=1.0", "type_id"),
        ("type_id=1&Type=2", "Type"),
        ("type_id=1&type_id=2", "type_id"),
        ("status=unknown", "status"),
        ("favorite=1", "favorite"),
        ("favorite=False", "favorite"),
        ("q=", "q"),
        ("q=a&search=b", "search"),
        ("ordering=unknown", "ordering"),
        ("ordering=sku,-sku", "ordering"),
        ("created_after=2026-01-01T00:00:00", "created_after"),
        ("created_after=2026-02-01T00:00:00Z&created_before=2026-01-01T00:00:00Z", "created_before"),
        ("type_id=" + ",".join(str(i) for i in range(1, 52)), "type_id"),
    ],
)
def test_invalid_filters_are_rejected(spec, query, field):
    serializer = spec.serializer("TestQuery")(data=QueryDict(query))
    assert not serializer.is_valid()
    assert field in serializer.errors


def test_legacy_search_alias_is_preserved(spec):
    serializer = spec.serializer("TestQuery")(data=QueryDict("search=legacy"))
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {"q": "legacy"}


def test_apply_preserves_queryset_and_combines_filters(spec):
    queryset = Mock()
    queryset.filter.return_value = queryset
    queryset.order_by.return_value = queryset
    result = spec.apply(
        queryset, {"type_id": [1, 2], "status": ["active"], "favorite": False, "q": "abc", "ordering": ["-created_at"]}
    )
    assert result is queryset
    assert queryset.filter.call_args_list[0].kwargs == {"type_id__in": [1, 2]}
    assert queryset.filter.call_args_list[1].kwargs == {"status__in": ["active"]}
    assert queryset.filter.call_args_list[2].kwargs == {"favorite": False}
    search = queryset.filter.call_args_list[3].args[0]
    assert search.connector == "OR"
    assert search.children == [("sku__icontains", "abc"), ("name__icontains", "abc")]
    queryset.order_by.assert_called_once_with("-created", "pk")


def test_metadata_has_public_fields_without_orm_lookups(spec):
    metadata = spec.metadata()
    assert metadata["combination"] == "and"
    assert metadata["multi_value_combination"] == "or"
    assert metadata["filters"][1]["choices"] == [
        {"value": "active", "label": "active"},
        {"value": "retired", "label": "retired"},
    ]
    assert "lookup" not in str(metadata)


def test_apply_rejects_unvalidated_keys(spec):
    with pytest.raises(ValueError):
        spec.apply(Mock(), {"status__regex": ".*"})


def test_general_filter_spec_has_no_resource_fields():
    spec = FilterSpec(
        [Filter("enabled", StrictBooleanField(required=False), "enabled", "boolean")],
        ordering={"code": "code"},
    )
    serializer = spec.serializer("NonResourceQuery")(data=QueryDict("enabled=false&ordering=code"))
    assert serializer.is_valid(), serializer.errors
    assert set(serializer.fields) == {"enabled", "ordering"}
    queryset = Mock()
    queryset.filter.return_value = queryset
    spec.apply(queryset, serializer.validated_data)
    queryset.filter.assert_called_once_with(enabled=False)
    queryset.order_by.assert_called_once_with("code", "pk")


@pytest.mark.parametrize("values,expected", [({}, False), ({"flag": False}, True), ({"flag": True}, True)])
def test_distinct_only_for_supplied_filter(values, expected):
    spec = FilterSpec([Filter("flag", StrictBooleanField(), "flag", "boolean", distinct=True)])
    queryset = Mock()
    queryset.filter.return_value = queryset
    queryset.distinct.return_value = queryset
    assert spec.apply(queryset, values) is queryset
    assert queryset.distinct.call_count == int(expected)
    if values:
        queryset.filter.assert_called_once_with(flag=values["flag"])
    else:
        queryset.filter.assert_not_called()


@pytest.mark.parametrize(
    "values,expected", [({}, False), ({"search": ""}, False), ({"q": "x"}, True), ({"search": "x"}, True)]
)
def test_search_distinct_only_for_nonempty_search(values, expected):
    spec = FilterSpec([], search_fields=("name",), search_alias=True, search_distinct=True)
    queryset = Mock()
    queryset.filter.return_value = queryset
    queryset.distinct.return_value = queryset
    spec.apply(queryset, values)
    assert queryset.distinct.call_count == int(expected)


class _PlainBooleanQuery(serializers.Serializer):
    """Hosts StrictBooleanField in a plain Serializer (not FilterQuerySerializer)."""

    flag = StrictBooleanField(required=False)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", {}), ("flag=true", {"flag": True}), ("flag=false", {"flag": False})],
)
def test_strict_boolean_absent_query_param_stays_absent(raw, expected):
    # Regression: an absent boolean in a QueryDict became False and was rejected,
    # which made GET /api/support/tickets fail with 400 when called without filters.
    serializer = _PlainBooleanQuery(data=QueryDict(raw))
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == expected


def test_strict_boolean_still_rejects_non_canonical_values():
    serializer = _PlainBooleanQuery(data=QueryDict("flag=1"))
    assert not serializer.is_valid()
    assert serializer.errors["flag"][0].code == "invalid_choice"
