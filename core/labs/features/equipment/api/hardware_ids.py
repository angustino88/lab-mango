"""``/api/labs/equipment/{id}/hardware-ids``: machine-read IDs a coordinator registers on a unit."""

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.summary_serializers import choice_field, embedded_resource
from core.labs.features.base.serializers import UIDNamedReferenceSerializer
from core.labs.features.equipment.application.hardware_ids import (
    RegisterHardwareIdInput,
    delete_hardware_id,
    is_port_bound,
    register_hardware_id,
)
from core.labs.features.equipment.queries.hardware_ids import list_hardware_ids
from core.labs.models.resource.equipment.hardware_id import EquipmentHardwareIdKind

from .common import EquipmentAPIView


@embedded_resource
class EquipmentHardwareIdSerializer(serializers.Serializer):
    """One ID registered on the unit; owned by it."""

    id = serializers.IntegerField()
    kind = choice_field(EquipmentHardwareIdKind.choices)
    value = serializers.CharField()
    computing = UIDNamedReferenceSerializer(allow_null=True, help_text="Set only for IDs valid on one computer.")
    is_port_bound = serializers.SerializerMethodField(help_text="Read from a USB port, not from the device.")
    created_at = serializers.DateTimeField(source="created")

    def get_is_port_bound(self, obj) -> bool:
        return is_port_bound(obj.kind, obj.value)


class EquipmentHardwareIdListSerializer(serializers.Serializer):
    items = EquipmentHardwareIdSerializer(many=True)


class RegisterHardwareIdRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=EquipmentHardwareIdKind.choices)
    value = serializers.CharField(max_length=512, trim_whitespace=True)
    computing_id = serializers.IntegerField(
        min_value=1, required=False, allow_null=True, help_text="Required for a port-bound PnP ID."
    )


class EquipmentHardwareIdListCreateAPIView(EquipmentAPIView):
    """List a unit's hardware IDs, or register one (idempotent for the same unit)."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentHardwareIdList", EquipmentHardwareIdListSerializer),
        not_found=ResponseContract.not_found(),
    )
    post_contract = OperationContract(
        request=RegisterHardwareIdRequestSerializer,
        success=ResponseContract.created("EquipmentHardwareIdCreated", EquipmentHardwareIdSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )

    def handle_get(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        return self.respond({"items": list(list_hardware_ids(equipment_id=equipment_id))})

    def handle_post(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned no serializer.")
        data = serializer.validated_data
        record = register_hardware_id(
            RegisterHardwareIdInput(
                equipment_id=equipment_id,
                kind=data["kind"],
                value=data["value"],
                computing_id=data.get("computing_id"),
            ),
            actor=self.acting_user,
        )
        return self.respond(list_hardware_ids(equipment_id=equipment_id).get(pk=record.pk))


class EquipmentHardwareIdDetailAPIView(EquipmentAPIView):
    """Remove a hardware ID from a unit."""

    delete_contract = OperationContract(
        success=ResponseContract.no_content(),
        not_found=ResponseContract.not_found(),
    )

    def handle_delete(self, request: Request, equipment_id: int, hardware_id_id: int, *args, **kwargs) -> Response:
        delete_hardware_id(equipment_id=equipment_id, hardware_id_id=hardware_id_id, actor=self.acting_user)
        return Response(status=status.HTTP_204_NO_CONTENT)
