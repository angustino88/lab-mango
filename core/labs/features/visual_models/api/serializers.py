from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.infrastructure.storage.urls import get_media_url
from core.labs.models.visual_models import VisualModelAsset, VisualModelAssignment

from ..validation import MAX_BYTES


class AssetSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    source_url = serializers.CharField(read_only=True, allow_blank=True)
    usage_count = serializers.IntegerField(read_only=True, help_text="Resources and types assigned to this model.")

    class Meta:
        model = VisualModelAsset
        fields = (
            "id",
            "name",
            "url",
            "sha256",
            "size",
            "source_url",
            "license",
            "rotation",
            "surface",
            "usage_count",
            "version",
            "updated_at",
        )

    def get_url(self, obj) -> str:
        return get_media_url(obj.file, request=self.context.get("request")) or ""


class AssignmentSerializer(serializers.ModelSerializer):
    asset_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = VisualModelAssignment
        fields = (
            "scope",
            "target_key",
            "asset_id",
            "rotation",
            "scale",
            "offset_x",
            "offset_y",
            "offset_z",
            "version",
            "updated_at",
        )


@extend_schema_field(OpenApiTypes.BINARY)
class ModelUploadField(serializers.FileField):
    pass


class AssetDetailsSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    source_url = serializers.URLField(required=False, allow_blank=True, default="")
    license = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    rotation = serializers.FloatField(min_value=-360, max_value=360, default=0)
    surface = serializers.FloatField(min_value=0, max_value=1, default=1)


class AssetUploadSerializer(AssetDetailsSerializer):
    file = ModelUploadField(max_length=255)

    def validate_file(self, value):
        if value.size > MAX_BYTES:
            raise serializers.ValidationError("Use a GLB file up to 15 MB.")
        return value


class AssignmentWriteSerializer(serializers.Serializer):
    asset_id = serializers.IntegerField(min_value=1)
    rotation = serializers.FloatField(min_value=-360, max_value=360, default=0)
    scale = serializers.FloatField(min_value=0.01, max_value=2, default=1)
    offset_x = serializers.FloatField(min_value=-1, max_value=1, default=0)
    offset_y = serializers.FloatField(min_value=-1, max_value=1, default=0)
    offset_z = serializers.FloatField(min_value=-1, max_value=1, default=0)


def multipart_model_data(data, serializer_class=AssetUploadSerializer):
    """Multipart fields are text. Coerce documented numbers before JSON-strict validation."""
    values = data.dict()
    serializer = serializer_class()
    errors: dict[str, Any] = {}
    for key in data:
        if len(data.getlist(key)) != 1:
            errors[key] = ["Send each field exactly once."]
    if errors:
        raise serializers.ValidationError(errors)
    for key, field in serializer.fields.items():
        if key in values and isinstance(field, (serializers.FloatField, serializers.IntegerField)):
            try:
                values[key] = field.run_validation(values[key])
            except serializers.ValidationError as exc:
                errors[key] = exc.detail
    if errors:
        raise serializers.ValidationError(errors)
    return values
