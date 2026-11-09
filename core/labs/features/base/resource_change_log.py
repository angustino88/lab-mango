"""Optional change-log behavior for resource-backed feature endpoints."""
from copy import deepcopy
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Manager, QuerySet
from django.db.models.fields.files import FieldFile
from rest_framework.request import Request

from core.labs.models import ResourceChangeLog


class ResourceChangeLogMixin:
    """Records authenticated mutations for resource-backed feature objects."""

    change_log_excluded_fields: ClassVar[frozenset[str]] = frozenset()

    def get_old_values(self, instance: Any, serializer: Any) -> dict[str, Any]:
        """Opt-in snapshots for logging; generic CRUD does not inspect resource fields."""
        return self.get_change_log_values(instance, serializer)

    @staticmethod
    def serialize_change_log_value(value: Any) -> Any:
        if isinstance(value, (UUID, Decimal)):
            return str(value)
        if isinstance(value, (FieldFile, UploadedFile)):
            return value.name
        if isinstance(value, (Manager, QuerySet)):
            value = list(value.order_by("pk").values_list("pk", flat=True))
        if hasattr(value, "pk"):
            return ResourceChangeLogMixin.serialize_change_log_value(value.pk)
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, (list, tuple)):
            return [ResourceChangeLogMixin.serialize_change_log_value(item) for item in value]
        if isinstance(value, dict):
            return {
                key: ResourceChangeLogMixin.serialize_change_log_value(item)
                for key, item in value.items()
            }
        return deepcopy(value)

    def get_change_log_values(self, instance: Any, serializer: Any) -> dict[str, Any]:
        """Read saved values, including normalized fields and materialized M2M IDs."""
        values = {}
        for field_name in serializer.validated_data:
            if field_name in self.change_log_excluded_fields:
                continue
            try:
                field = instance._meta.get_field(field_name)
            except FieldDoesNotExist:
                field = None
            if field is not None and field.many_to_many:
                value = list(getattr(instance, field_name).order_by("pk").values_list("pk", flat=True))
            elif field is not None and (field.many_to_one or field.one_to_one):
                value = getattr(instance, field.attname)
            else:
                value = getattr(instance, field_name, None)
            values[field_name] = ResourceChangeLogMixin.serialize_change_log_value(value)
        return values

    def record_change_log(
        self,
        instance,
        request: Request,
        action: str,
        *,
        field_name: str = "",
        old_value: Any = None,
        new_value: Any = None,
    ) -> None:
        if not request.user.is_authenticated or field_name in self.change_log_excluded_fields:
            return

        content_type = ContentType.objects.get_for_model(instance, for_concrete_model=False)
        change_log = ResourceChangeLog(
            resource_content_type=content_type,
            resource_object_id=str(instance.pk),
            action=action,
            field_name=field_name,
            old_value=self.serialize_change_log_value(old_value),
            new_value=self.serialize_change_log_value(new_value),
        )
        change_log.save(actor=request.user)

    def after_create(self, instance: Any, serializer: Any, request: Request) -> None:
        self.record_change_log(
            instance,
            request,
            ResourceChangeLog.Action.CREATE,
            new_value={
                field_name: self.serialize_change_log_value(value)
                for field_name, value in self.get_change_log_values(instance, serializer).items()
                if field_name not in self.change_log_excluded_fields
            },
        )

    def after_update(
        self,
        instance: Any,
        serializer: Any,
        request: Request,
        old_values: dict[str, Any],
    ) -> None:
        if not request.user.is_authenticated:
            return

        for field_name, new_value in self.get_change_log_values(instance, serializer).items():
            if field_name in self.change_log_excluded_fields:
                continue
            serialized_value = self.serialize_change_log_value(new_value)
            old_value = self.serialize_change_log_value(old_values[field_name])
            if old_value == serialized_value:
                continue
            self.record_change_log(
                instance,
                request,
                ResourceChangeLog.Action.UPDATE,
                field_name=field_name,
                old_value=old_value,
                new_value=serialized_value,
            )

    def before_delete(self, instance: Any, request: Request) -> None:
        self.record_change_log(
            instance,
            request,
            ResourceChangeLog.Action.DELETE,
            new_value=None,
        )
