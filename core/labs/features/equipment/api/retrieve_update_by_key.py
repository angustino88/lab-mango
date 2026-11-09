"""HTTP adapter for retrieving and partially updating equipment by a stable business key."""

from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.request import Request
from rest_framework.response import Response

from core.labs.features.base.resource_change_log import ResourceChangeLogMixin
from core.labs.features.equipment.application import UpdateEquipmentInput, update_equipment

from .common import EquipmentAPIView


class EquipmentByKeyRetrieveUpdateAPIView(ResourceChangeLogMixin, EquipmentAPIView):
    """Retrieve or partially update one category equipment record by SKU or UID.

    The key is resolved against the category queryset, so only active records of
    that category are visible. SKU and UID are immutable, so the resolved primary
    key stays valid for the write.
    """

    model = None
    queryset_provider = None
    entity_name = None
    lookup_field: ClassVar[str] = ""
    lookup_kwarg: ClassVar[str] = ""

    def get_queryset(self):
        return self.queryset_provider()

    def get_instance(self, key):
        return self.get_queryset().filter(**{self.lookup_field: key}).first()

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_instance(kwargs[self.lookup_kwarg])
        if instance is None:
            return self.respond_problem("not_found")
        return self.respond(instance)

    def handle_patch(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_instance(kwargs[self.lookup_kwarg])
        if instance is None:
            return self.respond_problem("not_found")
        serializer, error = self.validate_request(instance=instance, partial=True)
        if error is not None:
            return error
        old_values = self.get_old_values(instance, serializer)
        actor = request.user if request.user.is_authenticated else None
        try:
            with transaction.atomic():
                updated = update_equipment(
                    UpdateEquipmentInput(
                        equipment_id=instance.pk,
                        model=self.model,
                        fields=tuple(serializer.validated_data.items()),
                    ),
                    actor=actor,
                )
                updated = self.get_queryset().get(pk=updated.pk)
                self.after_update(updated, serializer, request, old_values)
        except ValidationError as error:
            errors = error.message_dict if hasattr(error, "error_dict") else error.messages
            return self.respond_problem("validation_error", errors=errors, code="validation_failed")
        return self.respond(updated)
