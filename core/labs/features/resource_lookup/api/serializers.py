"""Resource lookup transport fields."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.filtering import CSVField
from core.labs.features.base.serializers import (
    ChoiceReferenceSerializer,
    UIDNamedReferenceSerializer,
    to_choice_reference,
)
from core.labs.features.resource_lookup.queries import MAX_PER_TYPE, RESOURCE_TYPES


class ResourceLookupQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=1, max_length=100, help_text="Name, UID or SKU.")
    types = CSVField(
        serializers.ChoiceField(choices=RESOURCE_TYPES),
        max_items=len(RESOURCE_TYPES),
        required=False,
        help_text="Comma-separated: room, station, bench, equipment, license. Default: every type you may read.",
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=MAX_PER_TYPE, default=5)


_TYPE_LABELS = {"room": "Room", "station": "Station", "bench": "Bench", "equipment": "Equipment", "license": "License"}
_MATCH_LABELS = {
    "uid_exact": "Exact UID",
    "sku_exact": "Exact SKU",
    "name_exact": "Exact name",
    "prefix": "Starts with",
    "contains": "Contains",
}


class ResourceLookupMatchSerializer(serializers.Serializer):
    type = serializers.SerializerMethodField(help_text="room, station, bench, equipment or license.")
    match = serializers.SerializerMethodField(
        help_text="How q matched, best first: uid_exact, sku_exact, name_exact, prefix, contains."
    )
    resource = UIDNamedReferenceSerializer(read_only=True)
    sku = serializers.CharField(read_only=True)
    context = serializers.CharField(read_only=True, help_text="Where it is, or its product; empty when unknown.")

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_type(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.type, _TYPE_LABELS.items())

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_match(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.match, _MATCH_LABELS.items())
