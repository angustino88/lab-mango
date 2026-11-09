from drf_spectacular.utils import extend_schema as api_schema

from .operations import OperationContract, ResponseSet
from .responses import ResponseContract
from .schema import ResponseSchemaFactory
from .serializers import (
    EmptyPayloadSerializer,
    PaginatedResponseEnvelopeSerializer,
    PaginationMetadataSerializer,
    ProblemDetailSerializer,
    ResponseEnvelopeSerializer,
)
from .settings import (
    DEFAULT_PROBLEM_TYPE,
    DEFAULT_SETTINGS,
    PROBLEM_JSON,
    ContractSettings,
    default_code_value,
    default_problem_detail,
)
from .types import ResponseDefinition, SerializerClass, SerializerDefinition


__all__ = [
    "ContractSettings",
    "DEFAULT_PROBLEM_TYPE",
    "DEFAULT_SETTINGS",
    "EmptyPayloadSerializer",
    "OperationContract",
    "PROBLEM_JSON",
    "PaginatedResponseEnvelopeSerializer",
    "PaginationMetadataSerializer",
    "ProblemDetailSerializer",
    "ResponseContract",
    "ResponseDefinition",
    "ResponseEnvelopeSerializer",
    "ResponseSchemaFactory",
    "ResponseSet",
    "SerializerClass",
    "SerializerDefinition",
    "api_schema",
    "default_code_value",
    "default_problem_detail",
]

__version__ = "0.1.0"
