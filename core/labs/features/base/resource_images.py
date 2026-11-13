"""Resource images over HTTP: one URL field and one upload endpoint shared by every Labs resource.

* ``ResourceImageURLField`` renders ``image_url`` through ``get_media_url``: a presigned URL when MinIO is
  enabled, otherwise an absolute media URL. Every resource read serializer uses it, so the URL rule lives here.
* ``ResourceImageAPIView`` serves ``/{resource}/{id}/image``: ``GET`` reads ``image_url``, ``PUT`` replaces the
  image from a ``multipart/form-data`` body with exactly one ``file`` part (UPL-1), ``DELETE`` removes it.
  The content type is sniffed by Pillow (UPL-3); the client filename is never used as the storage path.
"""

from __future__ import annotations

from typing import Any, ClassVar

from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, status
from rest_framework.exceptions import ErrorDetail
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from core.infrastructure.storage.urls import get_media_url

from .common import FeatureAPIView
from .resource_image_commands import (
    RemoveResourceImageInput,
    ReplaceResourceImageInput,
    ResourceImageCommands,
    ResourceImageTargetNotFound,
)

MAX_RESOURCE_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_RESOURCE_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})


@extend_schema_field(OpenApiTypes.URI)
class ResourceImageURLField(serializers.Field):
    """Read-only ``image_url`` for a resource; ``null`` when the resource has no image."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("source", "image")
        kwargs["read_only"] = True
        kwargs["allow_null"] = True
        super().__init__(**kwargs)

    def to_representation(self, value: Any) -> str | None:
        return get_media_url(value, request=self.context.get("request"))


class ResourceImageSerializer(serializers.Serializer):
    image_url = ResourceImageURLField()


@extend_schema_field(OpenApiTypes.BINARY)
class _ImageUploadField(serializers.ImageField):
    """Documents the multipart part as binary; without COMPONENT_SPLIT_REQUEST spectacular emits ``uri``."""


class ResourceImageUploadSerializer(serializers.Serializer):
    file = _ImageUploadField(
        help_text="JPEG, PNG, GIF or WebP, at most 5 MB. The type is detected from the content.",
    )


class ResourceImageAPIView(FeatureAPIView):
    """Read, replace or remove a resource's image. Upload as multipart/form-data with one ``file`` part.

    Subclasses set ``image_commands`` to the binding their feature's application layer exports, and
    ``lookup_url_kwarg`` to the route's id keyword.
    """

    image_commands: ClassVar[ResourceImageCommands | None] = None
    lookup_url_kwarg: ClassVar[str | None] = None
    required_attributes = ("image_commands", "lookup_url_kwarg")
    parser_classes = [MultiPartParser]

    _image_response = ResponseContract.success("ResourceImage", ResourceImageSerializer)
    get_contract = OperationContract(success=_image_response, not_found=ResponseContract.not_found())
    put_contract = OperationContract(
        request=ResourceImageUploadSerializer,
        success=_image_response,
        not_found=ResponseContract.not_found(),
        payload_too_large=ResponseContract.problem(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE),
        unsupported_media_type=ResponseContract.problem(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
    )
    delete_contract = OperationContract(success=ResponseContract.no_content(), not_found=ResponseContract.not_found())

    @property
    def _commands(self) -> ResourceImageCommands:
        self.validate_configuration()
        assert self.image_commands is not None
        return self.image_commands

    def _resource_id(self, kwargs: dict[str, Any]) -> int:
        return kwargs[str(self.lookup_url_kwarg)]

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            resource = self._commands.get(resource_id=self._resource_id(kwargs))
        except ResourceImageTargetNotFound:
            return self.respond_problem("not_found")
        return self.respond(resource)

    def handle_put(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        commands = self._commands
        if len(request.FILES.getlist("file")) > 1:
            return self.respond_problem(
                "validation_error",
                code="validation_failed",
                errors={"file": [ErrorDetail("Send exactly one file part.", code="duplicate_values")]},
            )
        serializer, error = self.validate_request(serializer_class=ResourceImageUploadSerializer)
        if error is not None:
            return error
        assert serializer is not None
        image = serializer.validated_data["file"]
        if image.size > MAX_RESOURCE_IMAGE_BYTES:
            return self.respond_problem(
                "payload_too_large",
                code="payload_too_large",
                errors={"file": [ErrorDetail("The image must not exceed 5 MB.", code="max_size")]},
            )
        # Django's ImageField replaces the client's content type with the one Pillow detected.
        if getattr(image, "content_type", None) not in ALLOWED_RESOURCE_IMAGE_TYPES:
            return self.respond_problem(
                "unsupported_media_type",
                code="unsupported_media_type",
                errors={"file": [ErrorDetail("Use a JPEG, PNG, GIF or WebP image.", code="invalid_file")]},
            )
        try:
            resource = commands.replace(
                data=ReplaceResourceImageInput(resource_id=self._resource_id(kwargs), image=image),
                actor=self.acting_user,
            )
        except ResourceImageTargetNotFound:
            return self.respond_problem("not_found")
        return self.respond(resource)

    def handle_delete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            self._commands.remove(
                data=RemoveResourceImageInput(resource_id=self._resource_id(kwargs)),
                actor=self.acting_user,
            )
        except ResourceImageTargetNotFound:
            return self.respond_problem("not_found")
        return Response(status=status.HTTP_204_NO_CONTENT)


__all__ = [
    "ALLOWED_RESOURCE_IMAGE_TYPES",
    "MAX_RESOURCE_IMAGE_BYTES",
    "ResourceImageAPIView",
    "ResourceImageSerializer",
    "ResourceImageURLField",
    "ResourceImageUploadSerializer",
]
