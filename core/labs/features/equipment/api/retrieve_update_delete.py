"""Equipment-specific HTTP retrieve, update, and delete adapter."""

from django.shortcuts import get_object_or_404

from core.labs.features.base.resource_change_log import ResourceChangeLogMixin
from core.labs.features.base.retrieve_update_delete import RetrieveUpdateDeleteAPIView
from core.labs.features.equipment.application import (
    DeleteEquipmentInput,
    UpdateEquipmentInput,
    delete_equipment,
    update_equipment,
)
from core.labs.features.equipment.exceptions import SkuAlreadyExists

from .common import is_active_sku_unique_error


class EquipmentRetrieveUpdateDeleteAPIView(ResourceChangeLogMixin, RetrieveUpdateDeleteAPIView):
    """Adds equipment validation and change logging to single-object endpoints."""

    lock_on_write = True

    def get_save_kwargs(self, request):
        return {"last_modified_by": request.user} if request.user.is_authenticated else {}

    def get_response_instance(self, instance):
        return get_object_or_404(self.get_queryset(), pk=instance.pk)

    def get_object_queryset(self):
        """Keep provider visibility, without locking its DISTINCT/nullable joins."""
        return self.model.objects.filter(pk__in=self.get_queryset().values("pk"))

    def get_integrity_error_response(self, error):
        if is_active_sku_unique_error(error):
            raise SkuAlreadyExists from error
        return super().get_integrity_error_response(error)

    def perform_delete(self, instance, request) -> None:
        actor = request.user if request.user.is_authenticated else None
        delete_equipment(
            DeleteEquipmentInput(equipment_id=instance.pk, model=self.model),
            actor=actor,
        )

    def perform_update(self, instance, serializer, request):
        actor = request.user if request.user.is_authenticated else None
        return update_equipment(
            UpdateEquipmentInput(
                equipment_id=instance.pk,
                model=self.model,
                fields=tuple(serializer.validated_data.items()),
            ),
            actor=actor,
        )
