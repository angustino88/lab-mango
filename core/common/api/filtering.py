"""Declarative, allowlisted collection filters and frontend metadata.

Specs never select models or establish visibility. Apply them only to a queryset
returned by the owning feature's selector. CSV fields are strings on the wire;
their validated values are typed lists. ORM paths are server configuration only.
"""

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from django.db.models import Q, QuerySet
from rest_framework import serializers


class CSVField(serializers.CharField):
    """Bounded set encoded as one comma-separated query parameter."""

    def __init__(self, child: serializers.Field, *, max_items: int = 50, **kwargs: Any) -> None:
        self.child = child
        self.max_items = max_items
        super().__init__(trim_whitespace=False, **kwargs)

    def to_internal_value(self, data: Any) -> Any:
        raw = super().to_internal_value(data)
        items = raw.split(",")
        if len(items) > self.max_items:
            raise serializers.ValidationError(f"At most {self.max_items} values are allowed.", code="max_items")
        if any(not item or item != item.strip() for item in items):
            raise serializers.ValidationError(
                "Empty values and surrounding whitespace are invalid.", code="invalid_format"
            )
        values = [self.child.run_validation(item) for item in items]
        if len(set(values)) != len(values):
            raise serializers.ValidationError("Duplicate values are invalid.", code="duplicate_values")
        return values


class PositiveIDField(serializers.IntegerField):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(min_value=1, max_value=2**53 - 1, **kwargs)

    def to_internal_value(self, data: Any) -> int:
        if not isinstance(data, str) or not data.isascii() or not data.isdecimal() or data.startswith("0"):
            raise serializers.ValidationError("Enter a positive decimal identifier.", code="invalid_format")
        return super().to_internal_value(data)


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data: Any) -> bool:
        if data not in ("true", "false"):
            raise serializers.ValidationError("Use true or false.", code="invalid_choice")
        return data == "true"


class QueryDateTimeField(serializers.DateTimeField):
    """Query datetimes must carry an explicit RFC 3339 timezone."""

    def to_internal_value(self, data: Any) -> Any:
        if not isinstance(data, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", data
        ):
            raise serializers.ValidationError("Use an RFC 3339 datetime with timezone.", code="invalid_format")
        return super().to_internal_value(data)


@dataclass(frozen=True)
class Filter:
    """A public parameter, its typed validator, and a fixed server-side lookup."""

    name: str
    field: serializers.Field
    lookup: str
    kind: str
    multiple: bool = False
    label: str = ""
    options_key: str = ""
    distinct: bool = False


class FilterQuerySerializer(serializers.Serializer):
    filter_spec: "FilterSpec"

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        errors: dict[str, Any] = {}
        for key in data:
            if key not in self.fields and key not in {"page", "page_size"}:
                errors[key] = [serializers.ErrorDetail("Unknown query parameter.", code="invalid_query")]
            if hasattr(data, "getlist") and len(data.getlist(key)) > 1:
                errors[key] = [serializers.ErrorDetail("This parameter must not be repeated.", code="invalid_query")]
        try:
            # QueryDict is treated as HTML form data by DRF: blanks can be
            # omitted and absent booleans become False. Query filters must
            # preserve the distinction between absent, empty and false.
            values = super().to_internal_value({key: data[key] for key in data})
        except serializers.ValidationError as exc:
            if isinstance(exc.detail, dict):
                errors.update(exc.detail)
            else:
                errors["non_field_errors"] = exc.detail
            values = {}
        if errors:
            raise serializers.ValidationError(errors)
        return values

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        spec = self.filter_spec
        if "q" in attrs and "search" in attrs:
            raise serializers.ValidationError({"search": "Use either q or search, not both."})
        if "search" in attrs:
            attrs["q"] = attrs.pop("search")
        errors = {}
        ordering = attrs.get("ordering", ())
        if len({name.lstrip("-") for name in ordering}) != len(ordering):
            errors["ordering"] = "An ordering field cannot appear in both directions."
        for lower, upper in spec.ranges:
            if lower in attrs and upper in attrs and attrs[lower] > attrs[upper]:
                errors[upper] = "Upper bound must not be less than the lower bound."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class FilterSpec:
    """Model-independent validation, queryset filtering and UI metadata.

    Works with any Django queryset: fields and lookups are explicitly supplied
    by its owner. No resource fields, model registry or model discovery live here.
    """

    def __init__(
        self,
        filters: Sequence[Filter],
        *,
        search_fields: Sequence[str] = (),
        ordering: Mapping[str, str] | None = None,
        default_ordering: Sequence[str] = (),
        ranges: Sequence[tuple[str, str]] = (),
        search_alias: bool = False,
        search_distinct: bool = False,
    ) -> None:
        self.filters = tuple(filters)
        self.search_fields = tuple(search_fields)
        self.ordering = dict(ordering or {})
        self.default_ordering = tuple(default_ordering)
        self.ranges = tuple(ranges)
        self.search_alias = search_alias
        self.search_distinct = search_distinct
        names = [item.name for item in self.filters]
        if len(set(names)) != len(names) or set(names) & {"q", "search", "ordering", "page", "page_size"}:
            raise ValueError("Filter names must be unique and cannot use reserved query parameters.")
        if any(name.lstrip("-") not in self.ordering for name in self.default_ordering):
            raise ValueError("Default ordering must use declared public fields.")
        if any(lower not in names or upper not in names for lower, upper in self.ranges):
            raise ValueError("Range bounds must be declared filters.")

    def serializer(self, name: str) -> type[FilterQuerySerializer]:
        fields: dict[str, Any] = {"filter_spec": self, "__module__": __name__}
        for item in self.filters:
            child = deepcopy(item.field)
            fields[item.name] = (
                CSVField(child, required=False, help_text="Comma-separated values; OR within this filter.")
                if item.multiple
                else child.__class__(**{**child._kwargs, "required": False, "default": serializers.empty})
            )
        if self.search_fields:
            fields["q"] = serializers.CharField(required=False, min_length=1, max_length=200)
            if self.search_alias:
                # Existing clients may send an empty search; retain it as a legacy alias.
                fields["search"] = serializers.CharField(required=False, allow_blank=True, max_length=255)
        if self.ordering:
            choices = [value for key in self.ordering for value in (key, f"-{key}")]
            fields["ordering"] = CSVField(
                serializers.ChoiceField(choices=choices),
                required=False,
                max_items=len(self.ordering),
            )
        return type(name, (FilterQuerySerializer,), fields)

    def apply(self, queryset: QuerySet, values: Mapping[str, Any]) -> QuerySet:
        allowed = {item.name for item in self.filters} | {"q", "ordering"}
        if self.search_alias:
            allowed |= {"search"}
        if set(values) - allowed:
            raise ValueError("FilterSpec.apply requires validated query values.")
        needs_distinct = False
        for item in self.filters:
            if item.name in values:
                lookup = f"{item.lookup}__in" if item.multiple else item.lookup
                queryset = queryset.filter(**{lookup: values[item.name]})
                needs_distinct = needs_distinct or item.distinct
        search_query = values.get("q") or (values.get("search") if self.search_alias else None)
        if search_query:
            search = Q()
            for path in self.search_fields:
                search |= Q(**{f"{path}__icontains": search_query})
            queryset = queryset.filter(search)
            needs_distinct = needs_distinct or self.search_distinct
        requested = values.get("ordering", self.default_ordering)
        if requested:
            if len({name.lstrip("-") for name in requested}) != len(requested):
                raise ValueError("An ordering field cannot appear in both directions.")
            ordering = [
                f"{'-' if name.startswith('-') else ''}{self.ordering[name.lstrip('-')]}" for name in requested
            ]
            if not any(path.lstrip("-") in {"pk", "id"} for path in ordering):
                ordering.append("pk")
            queryset = queryset.order_by(*ordering)
        if needs_distinct:
            queryset = queryset.distinct()
        return queryset

    def metadata(self) -> dict[str, Any]:
        fields = []
        for item in self.filters:
            entry = {
                "name": item.name,
                "label": item.label or item.name,
                "type": item.kind,
                "multiple": item.multiple,
                "max_items": 50 if item.multiple else None,
            }
            if isinstance(item.field, serializers.ChoiceField):
                entry["choices"] = [{"value": key, "label": str(label)} for key, label in item.field.choices.items()]
            if item.options_key:
                entry["options_key"] = item.options_key
            fields.append(entry)
        return {
            "filters": fields,
            "combination": "and",
            "multi_value_combination": "or",
            "separator": ",",
            "search": {"parameter": "q", "min_length": 1, "max_length": 200} if self.search_fields else None,
            "ordering": list(self.ordering),
            "default_ordering": list(self.default_ordering),
        }


class FilterMetadataMixin:
    """General metadata handler; concrete API bases own auth and responses."""

    filter_spec: FilterSpec

    def handle_get(self: Any, request: Any, **kwargs: Any) -> Any:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.respond_data(self.filter_spec.metadata())


class FilterMetadataSerializer(serializers.Serializer):
    filters = serializers.ListField(child=serializers.DictField())
    combination = serializers.CharField()
    multi_value_combination = serializers.CharField()
    separator = serializers.CharField()
    search = serializers.DictField(allow_null=True)
    ordering = serializers.ListField(child=serializers.CharField())
    default_ordering = serializers.ListField(child=serializers.CharField())
