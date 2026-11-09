"""HTTP adapter and serializers for the live activity of computing equipment."""

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_api_key.permissions import HasAPIKey

from core.labs.features.base import CommandAPIView
from core.labs.features.equipment.categories.computing.application import (
    SyncComputingActivityInput,
    sync_computing_activity,
)
from core.labs.features.equipment.categories.computing.queries import (
    get_computing_activity_by_sku,
    get_computing_id_by_sku,
)
from core.labs.models import ComputingActivity, ComputingActivityStatus
from core.users.public import IsLabCoordinator


class ComputingActivitySerializer(serializers.ModelSerializer):
    """Read projection of the live activity state."""

    class Meta:
        model = ComputingActivity
        fields = (
            "status",
            "remote_user",
            "remote_user_display_name",
            "remote_computer",
            "remote_ip",
            "booking_code",
            "offline_at",
            "inactive_at",
            "inactive_reminder_count",
            "modified",
        )
        read_only_fields = fields
        ref_name = "ComputingActivity"


class ComputingActivityUpdateSerializer(serializers.Serializer):
    """Agent- or coordinator-reported state. Timestamps and counters are server-managed."""

    status = serializers.ChoiceField(choices=ComputingActivityStatus.choices, required=False)
    remote_user = serializers.CharField(max_length=255, required=False, allow_blank=True)
    remote_user_display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    remote_computer = serializers.CharField(max_length=255, required=False, allow_blank=True)
    remote_ip = serializers.IPAddressField(required=False, allow_null=True)
    booking_code = serializers.CharField(max_length=255, required=False, allow_blank=True)
    offline_at = serializers.DateTimeField(read_only=True)
    inactive_at = serializers.DateTimeField(read_only=True)


class ComputingActivityAPIView(CommandAPIView):
    """Read or report the live activity state of one computing equipment record."""

    schema_tags = ("Computing Equipment",)
    permission_classes = [HasAPIKey | IsLabCoordinator]
    get_contract = OperationContract(
        success=ResponseContract.success("ComputingActivityDetail", ComputingActivitySerializer),
        not_found=ResponseContract.not_found(),
    )
    patch_contract = OperationContract(
        request=ComputingActivityUpdateSerializer,
        success=ResponseContract.success("ComputingActivityUpdated", ComputingActivitySerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(422),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, sku: str, *args, **kwargs) -> Response:
        return self._execute(lambda: get_computing_activity_by_sku(sku))

    def handle_patch(self, request: Request, sku: str, *args, **kwargs) -> Response:
        serializer, error = self.validate_request(partial=True)
        if error is not None:
            return error
        fields = tuple(serializer.validated_data.items())
        user = getattr(request, "user", None)
        actor = user if getattr(user, "is_authenticated", False) else None

        def run() -> ComputingActivity:
            command = SyncComputingActivityInput(computing_id=get_computing_id_by_sku(sku), fields=fields)
            return sync_computing_activity(command, actor=actor)

        return self._execute(run)


__all__ = (
    "ComputingActivityAPIView",
    "ComputingActivitySerializer",
    "ComputingActivityUpdateSerializer",
)
