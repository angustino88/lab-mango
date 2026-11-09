from collections.abc import Mapping, Sequence
from functools import lru_cache

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema
from rest_framework import serializers, status

from .serializers import PaginatedResponseEnvelopeSerializer, ResponseEnvelopeSerializer
from .types import ResponseDefinition, SerializerClass, SerializerDefinition


class ResponseSchemaFactory:
    """Factory for consistent OpenAPI response schemas."""

    @staticmethod
    @lru_cache(maxsize=None)
    def success(name: str, payload_serializer: SerializerClass, *, many: bool = False) -> SerializerClass:
        ResponseSchemaFactory._validate(name, payload_serializer)
        payload_kind = "List" if many else "Detail"
        component_suffix = ResponseSchemaFactory._component_suffix(payload_serializer)
        return type(
            f"{name}{component_suffix}{payload_kind}ResponseSerializer",
            (ResponseEnvelopeSerializer,),
            {"data": payload_serializer(many=many), "__module__": payload_serializer.__module__},
        )

    @staticmethod
    @lru_cache(maxsize=None)
    def paginated(name: str, payload_serializer: SerializerClass) -> SerializerClass:
        ResponseSchemaFactory._validate(name, payload_serializer)
        component_suffix = ResponseSchemaFactory._component_suffix(payload_serializer)
        pagination_serializer = type(
            f"{name}{component_suffix}PaginationSerializer",
            (serializers.Serializer,),
            {
                "count": serializers.IntegerField(min_value=0),
                "page": serializers.IntegerField(min_value=1),
                "page_size": serializers.IntegerField(min_value=1),
                "next": serializers.CharField(allow_null=True),
                "previous": serializers.CharField(allow_null=True),
                "__module__": payload_serializer.__module__,
            },
        )
        meta_serializer = type(
            f"{name}{component_suffix}PaginationMetaSerializer",
            (serializers.Serializer,),
            {"pagination": pagination_serializer(), "__module__": payload_serializer.__module__},
        )
        return type(
            f"{name}{component_suffix}PaginatedResponseSerializer",
            (PaginatedResponseEnvelopeSerializer,),
            {"data": payload_serializer(many=True), "meta": meta_serializer(), "__module__": payload_serializer.__module__},
        )

    @staticmethod
    @lru_cache(maxsize=None)
    def empty(name: str) -> SerializerClass:
        ResponseSchemaFactory._validate_name(name)
        return type(
            f"{name}EmptyResponseSerializer",
            (ResponseEnvelopeSerializer,),
            {"data": serializers.DictField(read_only=True)},
        )

    @staticmethod
    def variants(component_name: str, schemas: Sequence[SerializerDefinition]) -> PolymorphicProxySerializer:
        ResponseSchemaFactory._validate_name(component_name)
        if not schemas:
            raise ValueError("schemas must contain at least one serializer")
        return PolymorphicProxySerializer(
            component_name=component_name,
            serializers=schemas,
            resource_type_field_name=None,
            many=False,
        )

    @staticmethod
    def list_variants(name: str, serializer: SerializerClass) -> PolymorphicProxySerializer:
        return ResponseSchemaFactory.variants(
            component_name=f"{name}ResponseVariant",
            schemas=[
                ResponseSchemaFactory.success(name, serializer, many=True),
                ResponseSchemaFactory.paginated(name, serializer),
            ],
        )

    @staticmethod
    def polymorphic(
        component_name: str,
        response_serializers: Sequence[SerializerDefinition],
    ) -> PolymorphicProxySerializer:
        return ResponseSchemaFactory.variants(component_name, response_serializers)

    @staticmethod
    def document(response: ResponseDefinition, *, status_code: int = status.HTTP_200_OK):
        responses = response if isinstance(response, Mapping) else {status_code: response}
        return extend_schema(responses=responses)

    @staticmethod
    def document_list(payload_serializer: SerializerClass, *, status_code: int = status.HTTP_200_OK):
        ResponseSchemaFactory._validate("List", payload_serializer)
        return ResponseSchemaFactory.document(payload_serializer(many=True), status_code=status_code)

    @staticmethod
    def _validate(name: str, payload_serializer: SerializerClass) -> None:
        ResponseSchemaFactory._validate_name(name)
        if not isinstance(payload_serializer, type) or not issubclass(payload_serializer, serializers.BaseSerializer):
            raise TypeError("payload_serializer must be a DRF serializer class")
        if issubclass(payload_serializer, ResponseEnvelopeSerializer):
            raise TypeError(
                f"{payload_serializer.__name__} is an API response envelope; "
                "pass its inner payload serializer instead"
            )

    @staticmethod
    def _validate_name(name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")

    @staticmethod
    def _component_suffix(payload_serializer: SerializerClass) -> str:
        module_name = payload_serializer.__module__.rsplit(".", 1)[-1]
        serializer_name = payload_serializer.__name__.removesuffix("Serializer")
        return f"{module_name.title().replace('_', '')}{serializer_name}"
