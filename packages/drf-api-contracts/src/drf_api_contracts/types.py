from collections.abc import Callable, Mapping
from typing import Any, TypeAlias

from rest_framework import serializers


SerializerClass: TypeAlias = type[serializers.BaseSerializer]
SerializerDefinition: TypeAlias = SerializerClass | serializers.BaseSerializer
ResponseDefinition: TypeAlias = SerializerDefinition | Mapping[int | str, SerializerDefinition]
ProblemResolver: TypeAlias = Callable[[Any, Any, int], str]
CodeResolver: TypeAlias = Callable[[Any], str]
