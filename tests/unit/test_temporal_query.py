"""Neutral temporal query bounds, independent of booking and database queries."""

from datetime import date, datetime, timedelta
from datetime import timezone as datetime_timezone
from zoneinfo import ZoneInfo

import pytest
from django.http import QueryDict
from django.test import override_settings
from django.utils import timezone
from rest_framework import serializers

from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.temporal_query import TemporalBoundField, TemporalRangeQueryMixin


class OptionalRangeQuery(TemporalRangeQueryMixin, PageNumberQuerySerializer):
    temporal_range_fields = ("window_after", "window_before")
    window_after = TemporalBoundField(required=False)
    window_before = TemporalBoundField(required=False)
    text = serializers.CharField(required=False)
    flag = serializers.BooleanField(required=False)


class DateRangeQuery(TemporalRangeQueryMixin, serializers.Serializer):
    temporal_range_fields = ("day_after", "day_before")
    day_after = TemporalBoundField(mode="date", required=False)
    day_before = TemporalBoundField(mode="date", required=False)


@pytest.mark.parametrize("value", ["2026-11-02", "2026-11-02T00:00:00Z", "2026-11-02T07:00:00+07:00"])
def test_optional_range_accepts_dates_and_aware_datetimes(value):
    query = OptionalRangeQuery(data={"window_after": value, "page": 2})
    assert query.is_valid(), query.errors
    assert isinstance(query.validated_data["window_after"], datetime)
    assert query.validated_data["page"] == 2


@override_settings(TIME_ZONE="Asia/Bangkok")
def test_date_uses_default_timezone_even_if_active_timezone_differs():
    with timezone.override("UTC"):
        query = OptionalRangeQuery(data={"window_after": "2026-11-02"})
        assert query.is_valid(), query.errors
        assert query.validated_data["window_after"] == datetime(2026, 11, 2, tzinfo=ZoneInfo("Asia/Bangkok"))


@pytest.mark.parametrize("zone,day", [("America/Havana", "2020-11-01"), ("America/Santiago", "2019-09-08")])
def test_date_only_midnight_retains_django_dst_behavior(zone, day):
    with override_settings(TIME_ZONE=zone):
        query = OptionalRangeQuery(data={"window_after": day})
        assert query.is_valid(), query.errors
        expected = timezone.make_aware(
            datetime.combine(date.fromisoformat(day), datetime.min.time()), timezone.get_default_timezone()
        )
        assert query.validated_data["window_after"] == expected
        assert query.validated_data["window_after"].fold == expected.fold


@pytest.mark.parametrize(
    "value, message",
    [
        ("2026-02-30", "Enter a valid ISO date."),
        ("2026-11-02T12:00:00", "Enter YYYY-MM-DD or an offset-aware RFC3339 datetime."),
        (" 2026-11-02", "Enter YYYY-MM-DD or an offset-aware RFC3339 datetime."),
        ("2026-11-02 ", "Enter YYYY-MM-DD or an offset-aware RFC3339 datetime."),
        ("2026-11-02T12:00:00+24:00", "Enter a valid RFC3339 UTC offset."),
        ("2026-11-02T12:00:00+01:60", "Enter a valid RFC3339 UTC offset."),
        ("2026-11-02T25:00:00Z", "Enter a valid RFC3339 datetime."),
        ("2026-11-02T12:00:60Z", "Enter a valid RFC3339 datetime."),
    ],
)
def test_invalid_mixed_bounds_keep_format_errors(value, message):
    query = OptionalRangeQuery(data={"window_before": value})
    assert not query.is_valid()
    assert str(query.errors["window_before"][0]) == message
    assert query.errors["window_before"][0].code == "invalid_format"


@pytest.mark.parametrize(
    "mode,valid,invalid",
    [("date", "2026-11-02", "2026-11-02T00:00:00Z"), ("datetime", "2026-11-02T00:00:00Z", "2026-11-02")],
)
def test_explicit_modes_accept_only_declared_grammar(mode, valid, invalid):
    field = TemporalBoundField(mode=mode)
    parsed = field.run_validation(valid)
    assert type(parsed) is (date if mode == "date" else datetime)
    with pytest.raises(serializers.ValidationError) as exc:
        field.run_validation(invalid)
    assert exc.value.get_codes() == ["invalid_format"]


@pytest.mark.parametrize("value", ["", " "])
def test_blank_bound_is_rejected(value):
    query = OptionalRangeQuery(data={"window_after": value})
    assert not query.is_valid()
    assert "window_after" in query.errors


@pytest.mark.parametrize("bound", ["window_after", "window_before"])
@pytest.mark.parametrize("value,code", [("", "blank"), (" ", "invalid_format")])
def test_querydict_blank_temporal_bound_is_rejected(bound, value, code):
    query = OptionalRangeQuery(data=QueryDict(f"{bound}={value}"))
    assert not query.is_valid()
    assert query.errors[bound][0].code == code


@pytest.mark.parametrize("after,before", [("", "2026-02-30"), ("2026-02-30", "")])
def test_querydict_blank_and_invalid_bound_report_both_errors(after, before):
    query = OptionalRangeQuery(data=QueryDict(f"window_after={after}&window_before={before}"))

    assert not query.is_valid()
    assert list(query.errors) == ["window_after", "window_before"]
    assert {key: [(str(error), error.code) for error in errors] for key, errors in query.errors.items()} == {
        "window_after": [
            ("This field may not be blank.", "blank") if after == "" else ("Enter a valid ISO date.", "invalid_format")
        ],
        "window_before": [
            ("This field may not be blank.", "blank")
            if before == ""
            else ("Enter a valid ISO date.", "invalid_format")
        ],
    }


def test_querydict_two_blank_bounds_are_both_reported():
    query = OptionalRangeQuery(data=QueryDict("window_after=&window_before="))

    assert not query.is_valid()
    assert list(query.errors) == ["window_after", "window_before"]
    assert {key: [error.code for error in errors] for key, errors in query.errors.items()} == {
        "window_after": ["blank"],
        "window_before": ["blank"],
    }


def test_querydict_blank_bound_keeps_parent_non_temporal_validation_errors():
    query = OptionalRangeQuery(data=QueryDict("window_after=&page=0"))

    assert not query.is_valid()
    assert list(query.errors) == ["page", "window_after"]
    assert query.errors["page"][0].code == "min_value"
    assert str(query.errors["page"][0]) == "Ensure this value is greater than or equal to 1."
    assert query.errors["window_after"][0].code == "blank"


class MultipleTextErrorParent(serializers.Serializer):
    text = serializers.CharField(required=False)
    flag = serializers.BooleanField(required=False)
    page = serializers.IntegerField(required=False, min_value=1)

    def to_internal_value(self, data):
        super().to_internal_value(data)
        raise serializers.ValidationError(
            {
                "text": [
                    serializers.ErrorDetail("First text error.", code="first"),
                    serializers.ErrorDetail("Second text error.", code="second"),
                ],
                "page": [serializers.ErrorDetail("Parent page error.", code="parent_page")],
            }
        )


class MultipleErrorsQuery(TemporalRangeQueryMixin, MultipleTextErrorParent):
    """Trigger multiple framework errors on one field while retaining normal bound parsing."""

    temporal_range_fields = ("window_after", "window_before")
    window_after = TemporalBoundField(required=False)
    window_before = TemporalBoundField(required=False)


class OverlappingTemporalErrorParent(serializers.Serializer):
    window_after = TemporalBoundField(required=False)
    window_before = TemporalBoundField(required=False)

    def to_internal_value(self, data):
        super().to_internal_value(data)
        raise serializers.ValidationError(
            {"window_after": [serializers.ErrorDetail("Parent temporal error.", code="parent_temporal")]}
        )


class OverlappingTemporalErrorsQuery(TemporalRangeQueryMixin, OverlappingTemporalErrorParent):
    """Trigger parent validation on the same key as request-level bound checks."""

    temporal_range_fields = ("window_after", "window_before")


def test_querydict_blank_bound_preserves_multiple_parent_errors_and_orders_fields():
    query = MultipleErrorsQuery(data=QueryDict("text=invalid&window_after="))

    assert not query.is_valid()
    assert list(query.errors) == ["text", "page", "window_after"]
    assert [(str(error), error.code) for error in query.errors["text"]] == [
        ("First text error.", "first"),
        ("Second text error.", "second"),
    ]
    assert [(str(error), error.code) for error in query.errors["page"]] == [("Parent page error.", "parent_page")]
    assert [(str(error), error.code) for error in query.errors["window_after"]] == [
        ("This field may not be blank.", "blank")
    ]


def test_duplicate_temporal_value_preserves_same_field_parent_error_in_stable_order():
    query = OverlappingTemporalErrorsQuery(data=QueryDict("window_after=2026-11-02&window_after=2026-11-03"))

    assert not query.is_valid()
    assert list(query.errors) == ["window_after"]
    assert [(str(error), error.code) for error in query.errors["window_after"]] == [
        ("Parent temporal error.", "parent_temporal"),
        ("Provide this parameter only once.", "duplicate"),
    ]


class NonFieldErrorParent(serializers.Serializer):
    text = serializers.CharField(required=False)
    flag = serializers.BooleanField(required=False)
    page = serializers.IntegerField(required=False, min_value=1)

    def to_internal_value(self, data):
        super().to_internal_value(data)
        raise serializers.ValidationError(
            {
                "page": [serializers.ErrorDetail("Parent page error.", code="parent_page")],
                "non_field_errors": [serializers.ErrorDetail("Parent-level error.", code="parent_error")],
            }
        )


class NonFieldErrorQuery(TemporalRangeQueryMixin, NonFieldErrorParent):
    """Raise a parent-level error after normal field parsing."""

    temporal_range_fields = ("window_after", "window_before")
    window_after = TemporalBoundField(required=False)
    window_before = TemporalBoundField(required=False)


def test_querydict_blank_bound_preserves_parent_non_field_error_in_documented_order():
    query = NonFieldErrorQuery(data=QueryDict("text=invalid&window_after="))

    assert not query.is_valid()
    assert list(query.errors) == ["page", "window_after", "non_field_errors"]
    assert [(str(error), error.code) for error in query.errors["page"]] == [("Parent page error.", "parent_page")]
    assert [(str(error), error.code) for error in query.errors["non_field_errors"]] == [
        ("Parent-level error.", "parent_error")
    ]
    assert [(str(error), error.code) for error in query.errors["window_after"]] == [
        ("This field may not be blank.", "blank")
    ]


@pytest.mark.parametrize("bound", ["window_after", "window_before"])
def test_unrelated_blank_querydict_filters_unchanged_with_temporal_blank(bound):
    unrelated = QueryDict("text=&flag=&page=&page_size=")
    combined = unrelated.copy()
    combined[bound] = ""

    baseline = OptionalRangeQuery(data=unrelated)
    query = OptionalRangeQuery(data=combined)

    assert baseline.is_valid(), baseline.errors
    assert not query.is_valid()
    assert query.errors == {bound: ["This field may not be blank."]}
    assert combined.getlist("text") == unrelated.getlist("text")
    assert combined.getlist("flag") == unrelated.getlist("flag")


def test_non_temporal_duplicate_querydict_values_keep_html_input_semantics():
    baseline = OptionalRangeQuery(data=QueryDict("text=first&text=second&flag=&page="))
    combined = OptionalRangeQuery(data=QueryDict("text=first&text=second&flag=&page=&window_after="))

    assert baseline.is_valid(), baseline.errors
    assert not combined.is_valid()
    assert set(combined.errors) == {"window_after"}


@pytest.mark.parametrize("data", [{"window_after": "2026-11-02"}, {"window_before": "2026-11-09"}, {}])
def test_single_or_missing_bounds_are_optional(data):
    query = OptionalRangeQuery(data=data)
    assert query.is_valid(), query.errors
    assert set(query.validated_data) == set(data)


@pytest.mark.parametrize("before", ["2026-11-02T00:00:00Z", "2026-11-01T23:59:59Z"])
def test_equal_or_reversed_instants_attribute_error_to_upper_bound(before):
    query = OptionalRangeQuery(data={"window_after": "2026-11-02T07:00:00+07:00", "window_before": before})
    assert not query.is_valid()
    assert str(query.errors["window_before"][0]) == "Must be later than window_after."
    assert query.errors["window_before"][0].code == "invalid_range"


def test_date_mode_compares_calendar_values_without_timezone_conversion():
    query = DateRangeQuery(data={"day_after": "2026-11-02", "day_before": "2026-11-03"})
    assert query.is_valid(), query.errors
    assert query.validated_data == {"day_after": date(2026, 11, 2), "day_before": date(2026, 11, 3)}
    equal = DateRangeQuery(data={"day_after": "2026-11-02", "day_before": "2026-11-02"})
    assert not equal.is_valid()
    assert equal.errors["day_before"][0].code == "invalid_range"


def test_datetime_fraction_and_signed_offsets_remain_accepted():
    query = OptionalRangeQuery(data={"window_after": "2026-11-02T00:00:00.123456789-05:00"})
    assert query.is_valid(), query.errors
    assert query.validated_data["window_after"].utcoffset() == -timedelta(hours=5)
    assert query.validated_data["window_after"].microsecond == 123456
    assert query.validated_data["window_after"].astimezone(datetime_timezone.utc).hour == 5
