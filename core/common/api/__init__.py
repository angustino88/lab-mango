"""Shared transport primitives for the project's HTTP APIs."""

from rest_framework import serializers

from .api_views import AppAPIView, AppDetailAPIView, AppListAPIView
from .options import (
    OPTIONS_MAX_RESULTS,
    CatalogOptionListSerializer,
    CatalogOptionSerializer,
    IncludeIDsField,
    OptionsAPIView,
    OptionsQueryMixin,
    SizeClass,
)


class AppModelSerializer(serializers.ModelSerializer):
    """Base model serializer that automatically exposes created_at and updated_at from TimeStampedModel."""

    created_at = serializers.DateTimeField(source="created", read_only=True)
    updated_at = serializers.DateTimeField(source="modified", read_only=True)

    def get_fields(self):
        fields = super().get_fields()
        model = getattr(getattr(self, "Meta", None), "model", None)
        if model is not None:
            model_fields = {f.name for f in model._meta.get_fields()}
            if "created" not in model_fields and "created_at" not in model_fields:
                fields.pop("created_at", None)
            if "modified" not in model_fields and "updated_at" not in model_fields:
                fields.pop("updated_at", None)
        return fields


__all__ = [
    "AppAPIView",
    "AppDetailAPIView",
    "AppListAPIView",
    "AppModelSerializer",
    "CatalogOptionListSerializer",
    "CatalogOptionSerializer",
    "IncludeIDsField",
    "OPTIONS_MAX_RESULTS",
    "OptionsAPIView",
    "OptionsQueryMixin",
    "SizeClass",
]
