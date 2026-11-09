"""Opt-in transport parsing for optional temporal query bounds; no queryset semantics."""

import re
from datetime import date, datetime, time
from typing import Any, Literal

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.settings import api_settings

Mode = Literal["date_or_datetime", "date", "datetime"]
_MODES = ("date_or_datetime", "date", "datetime")

# [0-9] + re.ASCII: never accept non-ASCII Unicode digits.
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
_DATETIME_PATTERN = re.compile(
    r"(?P<base>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.(?P<frac>[0-9]+))?"
    r"(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})",
    re.ASCII,
)

_INVALID_FORMAT_MESSAGES: dict[str, str] = {
    "date_or_datetime": "Enter YYYY-MM-DD or an offset-aware RFC3339 datetime.",
    "date": "Enter a valid ISO date.",
    "datetime": "Use an RFC 3339 datetime with timezone.",
}


@extend_schema_field(
    {
        "type": "string",
        "description": "ISO date (YYYY-MM-DD) and/or RFC 3339 datetime with offset, depending on the field's mode.",
    }
)
class TemporalBoundField(serializers.Field):
    """Parse a strict date, aware datetime, or either; date midnights use default TIME_ZONE."""

    def __init__(self, *, mode: Mode = "date_or_datetime", **kwargs: Any) -> None:
        if mode not in _MODES:
            raise ValueError("Unknown temporal bound mode.")
        self.mode = mode
        super().__init__(**kwargs)

    def to_internal_value(self, data: Any) -> date | datetime:
        if not isinstance(data, str):
            raise serializers.ValidationError("Not a valid string.", code="invalid")
        if data == "":
            raise serializers.ValidationError("This field may not be blank.", code="blank")

        if self.mode != "datetime" and _DATE_PATTERN.fullmatch(data):
            try:
                parsed_date = date.fromisoformat(data)
            except ValueError as exc:
                raise serializers.ValidationError("Enter a valid ISO date.", code="invalid_format") from exc
            if self.mode == "date":
                return parsed_date
            return timezone.make_aware(datetime.combine(parsed_date, time.min), timezone.get_default_timezone())

        match = _DATETIME_PATTERN.fullmatch(data) if self.mode != "date" else None
        if match is None:
            raise serializers.ValidationError(_INVALID_FORMAT_MESSAGES[self.mode], code="invalid_format")

        offset = match["offset"]
        if offset in ("Z", "-00:00"):  # RFC 3339: "-00:00" means UTC with unknown local offset.
            offset = "+00:00"
        else:
            hours, minutes = (int(part) for part in offset[1:].split(":"))
            if hours > 23 or minutes > 59:
                raise serializers.ValidationError("Enter a valid RFC3339 UTC offset.", code="invalid_format")

        # RFC 3339 allows any number of fractional digits; Python < 3.11 accepts only 3 or 6.
        # Normalize to microseconds (extra digits are truncated).
        fraction = f".{match['frac'][:6].ljust(6, '0')}" if match["frac"] else ""
        try:
            return datetime.fromisoformat(f"{match['base']}{fraction}{offset}")
        except ValueError as exc:
            raise serializers.ValidationError("Enter a valid RFC3339 datetime.", code="invalid_format") from exc

    def to_representation(self, value: date | datetime) -> str:
        return value.isoformat()


def _check_temporal_config(cls: type) -> None:
    """Fail at import time, not at request time, if the declared pair is unusable."""
    pair = cls.temporal_range_fields  # type: ignore[attr-defined]
    if not (isinstance(pair, tuple) and len(pair) == 2 and all(isinstance(name, str) for name in pair)):
        raise ImproperlyConfigured(f"{cls.__name__}.temporal_range_fields must be a tuple of two field names.")
    if pair[0] == pair[1]:
        raise ImproperlyConfigured(f"{cls.__name__}.temporal_range_fields must name two different fields.")

    declared = getattr(cls, "_declared_fields", {})
    modes = set()
    for name in pair:
        field = declared.get(name)
        if not isinstance(field, TemporalBoundField):
            raise ImproperlyConfigured(f"{cls.__name__}.{name} must be a declared TemporalBoundField.")
        modes.add(field.mode)
    if len(modes) != 1:
        # date vs datetime cannot be compared; date_or_datetime vs date can also mix types.
        raise ImproperlyConfigured(
            f"{cls.__name__}: both temporal bounds must use the same mode, got {sorted(modes)}."
        )


class TemporalRangeQueryMixin:
    """Check a declared pair after the containing query serializer validates fields.

    Set ``allow_equal_bounds = True`` for closed ranges where ``lower == upper`` is valid.
    The default (False) suits half-open ``[lower, upper)`` ranges, where equal bounds are empty.
    """

    temporal_range_fields: tuple[str, str]
    allow_equal_bounds: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "temporal_range_fields"):  # abstract intermediates may omit it
            _check_temporal_config(cls)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if not hasattr(self, "temporal_range_fields"):
            raise ImproperlyConfigured(f"{type(self).__name__} must define temporal_range_fields.")
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        # DRF treats QueryDict as HTML input and silently skips blank optional fields, and
        # takes the last value of a repeated parameter. Check only the declared bounds here.
        bound_errors: dict[str, list[serializers.ErrorDetail]] = {}
        if hasattr(data, "getlist"):
            for key in self.temporal_range_fields:
                values = data.getlist(key)
                if len(values) > 1:
                    bound_errors[key] = [
                        serializers.ErrorDetail("Provide this parameter only once.", code="duplicate")
                    ]
                elif values == [""]:
                    bound_errors[key] = [serializers.ErrorDetail("This field may not be blank.", code="blank")]

        try:
            attrs = super().to_internal_value(data)  # type: ignore[misc]
        except serializers.ValidationError as exc:
            if not bound_errors:
                raise
            detail = exc.detail if isinstance(exc.detail, dict) else {api_settings.NON_FIELD_ERRORS_KEY: exc.detail}
            raise serializers.ValidationError(self._ordered_errors(detail, bound_errors)) from exc

        if bound_errors:
            raise serializers.ValidationError(bound_errors)
        return attrs

    def _ordered_errors(
        self, detail: dict[str, Any], bound_errors: dict[str, list[serializers.ErrorDetail]]
    ) -> dict[str, Any]:
        """Keep error ordering aligned with declared fields and the temporal bound pair."""
        field_order = list(self.fields)  # type: ignore[attr-defined]
        temporal_order = list(self.temporal_range_fields)
        ordered: dict[str, Any] = {}

        for field_name in field_order:
            if field_name in detail and field_name not in temporal_order:
                ordered[field_name] = detail[field_name]
        for field_name in temporal_order:
            if field_name in detail or field_name in bound_errors:
                parent_errors = detail.get(field_name, [])
                temporal_errors = bound_errors.get(field_name, [])
                ordered[field_name] = [*parent_errors, *temporal_errors]
        for field_name, errors in detail.items():
            if field_name not in ordered:
                ordered[field_name] = errors
        for field_name, errors in bound_errors.items():
            if field_name not in ordered:
                ordered[field_name] = errors

        return ordered

    def _bound_value(self, attrs: dict[str, Any], name: str) -> Any:
        """Read a bound from validated attrs, honoring the field's ``source``."""
        value: Any = attrs
        source_attrs = self.fields[name].source_attrs  # type: ignore[attr-defined]
        if not source_attrs:
            return None
        for key in source_attrs:
            if not isinstance(value, dict) or key not in value:
                return None
            value = value[key]
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)  # type: ignore[misc]
        lower_name, upper_name = self.temporal_range_fields
        lower = self._bound_value(attrs, lower_name)
        upper = self._bound_value(attrs, upper_name)
        if lower is None or upper is None:
            return attrs
        invalid = lower > upper if self.allow_equal_bounds else lower >= upper
        if invalid:
            message = (
                f"Must not be earlier than {lower_name}."
                if self.allow_equal_bounds
                else f"Must be later than {lower_name}."
            )
            raise serializers.ValidationError({upper_name: [serializers.ErrorDetail(message, code="invalid_range")]})
        return attrs
