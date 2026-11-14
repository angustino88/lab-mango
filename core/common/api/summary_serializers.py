"""Reusable wire shapes, without domain choices or model imports."""

from typing import Any

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers


class SummaryStatusSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class SummaryStatusCountSerializer(serializers.Serializer):
    status = SummaryStatusSerializer()
    resource_count = serializers.IntegerField(min_value=0)


class StatusSummarySerializer(serializers.Serializer):
    total_count = serializers.IntegerField(min_value=0)
    unknown_status_count = serializers.IntegerField(
        min_value=0,
        help_text="Resources without a recorded status or with an unrecognized status.",
    )
    statuses = SummaryStatusCountSerializer(
        many=True,
        help_text="All code-defined states, including zero counts. Values are extensible.",
    )


embedded_resource = extend_schema_serializer(extensions={"x-embedded-resource": True})
"""Mark a serializer as an embedded resource (response standard REL-15): an owned child or a bundle item.

The contract gate then checks it as a resource instead of as a relation, so it must follow REL-1 and the
naming and enum rules itself.
"""


def protocol_payload(spec_path: str):
    """Mark a serializer as a payload of a separate approved wire protocol (response standard GEN-7).

    Its keys and values follow ``spec_path``; envelope, errors and security still follow the standard.
    """
    return extend_schema_serializer(extensions={"x-protocol-spec": spec_path})


DELETED_USER_NAME = "Deleted user"
"""REL-12 placeholder for a historical user reference whose user was erased."""


def user_display_name(user: Any) -> str:
    """REL-3 display name of a user: display name, then full name, then username."""
    for attribute in ("display_name", "name"):
        value = (getattr(user, attribute, "") or "").strip()
        if value:
            return value
    get_full_name = getattr(user, "get_full_name", None)
    full_name = (get_full_name() if callable(get_full_name) else "").strip()
    if full_name:
        return full_name
    return (getattr(user, "username", "") or "").strip() or DELETED_USER_NAME


class UserReferenceSerializer(serializers.Serializer):
    """REL-3 user relation ``{id, name}``; duck-typed so any feature may use it without importing users."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        ref_name = "UserReference"

    def get_name(self, obj: Any) -> str:
        return user_display_name(obj)


class RelationSerializer(serializers.Serializer):
    """REL-3 relation ``{id, name}`` to any model row; ``name`` follows ``relation_name``."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        ref_name = "Relation"

    def get_name(self, obj: Any) -> str:
        from .wire_names import relation_name

        return relation_name(obj)


class ChoiceSerializer(serializers.Serializer):
    """ENU-1 ``{value, label}``."""

    value = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)

    class Meta:
        ref_name = "Choice"


def to_choice(value: Any, choices: Any = None) -> dict[str, str] | None:
    """Render a stored enum value as ENU-1 ``{value, label}``; ``None`` stays ``None``."""
    if value is None or value == "":
        return None
    labels = dict(choices) if choices else {}
    label = labels.get(value, str(value).replace("_", " ").capitalize())
    return {"value": str(value), "label": str(label)}


def choice_field(choices: Any, *, source: str | None = None, allow_null: bool = False) -> serializers.Field:
    """Read-only ENU-1 field for a model choice attribute."""

    @extend_schema_field(ChoiceSerializer(allow_null=allow_null))
    class _ChoiceField(serializers.Field):
        def __init__(self, **kwargs):
            kwargs.setdefault("read_only", True)
            super().__init__(**kwargs)

        def to_representation(self, value):
            return to_choice(value, choices)

    kwargs: dict[str, Any] = {"allow_null": allow_null}
    if source is not None:
        kwargs["source"] = source
    return _ChoiceField(**kwargs)
