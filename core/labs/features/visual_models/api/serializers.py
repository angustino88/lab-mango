from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.infrastructure.storage.urls import get_media_url
from core.labs.models.visual_models import VisualModelAsset

from ..validation import MAX_BYTES


class AssetSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    source_url = serializers.CharField(read_only=True, allow_blank=True)
    usage_count = serializers.IntegerField(read_only=True, help_text="Resources and catalog types using this model.")

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


class SelectionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True)
    visual_model_id = serializers.IntegerField(allow_null=True, help_text="Model stored on this resource.")
    effective_visual_model_id = serializers.IntegerField(
        allow_null=True, help_text="Model shown on the 3D dashboard after inheriting catalog defaults."
    )
    origin = serializers.CharField(
        allow_null=True,
        help_text="'own', or the catalog the shown model is inherited from (station_type, product_model, "
        "equipment_category); null when no model applies.",
    )


@extend_schema_field(OpenApiTypes.BINARY)
class ModelUploadField(serializers.FileField):
    pass


_url_check = URLValidator()


def _valid_url(value: str) -> None:
    """Same check as URLField, behind a plain function so the schema stays a string (not format uri)."""
    try:
        _url_check(value)
    except DjangoValidationError as error:
        raise serializers.ValidationError(error.messages) from None


class AssetDetailsSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    # A text field validated as a URL when given. Not URLField: its OpenAPI schema is format "uri" with an
    # empty default, which is not a valid URI and fails Spectral. Validation is unchanged for non-empty values.
    source_url = serializers.CharField(required=False, allow_blank=True, default="", validators=[_valid_url])
    license = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    rotation = serializers.FloatField(min_value=-360, max_value=360, default=0)
    surface = serializers.FloatField(min_value=0, max_value=1, default=1)


class AssetUploadSerializer(AssetDetailsSerializer):
    file = ModelUploadField(max_length=255)

    def validate_file(self, value):
        if value.size > MAX_BYTES:
            raise serializers.ValidationError("Use a GLB file up to 15 MB.")
        return value


class SelectionWriteSerializer(serializers.Serializer):
    visual_model_id = serializers.IntegerField(
        min_value=1, allow_null=True, help_text="Library model to show, or null to inherit or show none."
    )


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
