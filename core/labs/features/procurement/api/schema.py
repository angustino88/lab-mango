"""OpenAPI schema extensions for procurement request contracts."""

from drf_spectacular.extensions import OpenApiSerializerExtension

from .serializers import PurchaseItemResourceCreateSerializer


class PurchaseItemResourceCreateSchemaExtension(OpenApiSerializerExtension):
    target_class = PurchaseItemResourceCreateSerializer
    match_subclasses = True

    def map_serializer(self, auto_schema, direction):
        schema = auto_schema._map_serializer(self.target, direction, bypass_extensions=True)
        schema["anyOf"] = [
            {"required": ["resource_kind"]},
            {"required": ["resource_type_id"]},
        ]
        return schema


__all__ = ["PurchaseItemResourceCreateSchemaExtension"]
