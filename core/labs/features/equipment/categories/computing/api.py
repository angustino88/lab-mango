"""Read adapter and serializer for the live activity of computing equipment."""

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.summary_serializers import choice_field
from core.labs.features.base import CommandAPIView
from core.labs.features.equipment.api.common import EQUIPMENT_PERMISSIONS
from core.labs.features.equipment.categories.computing.queries import get_computing_activity
from core.labs.models import ComputingActivity


class ComputingActivitySerializer(serializers.ModelSerializer):
    """Read projection of the live activity state."""

    status = choice_field(ComputingActivity._meta.get_field("status").choices)
    updated_at = serializers.DateTimeField(source="modified", read_only=True)

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
            "updated_at",
        )
        read_only_fields = fields
        ref_name = "ComputingActivity"


class ComputingActivityAPIView(CommandAPIView):
    """Read the live activity of one computing unit (coordinators and API keys, like every equipment read).

    Agents report activity through ``PATCH /agent/equipment/activity``, authenticated by the agent's
    signed request; there is no write here (owner decision 2026-11-11).
    """

    schema_tags = ("Equipment",)
    permission_classes = EQUIPMENT_PERMISSIONS
    get_contract = OperationContract(
        success=ResponseContract.success("ComputingActivityDetail", ComputingActivitySerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        return self._execute(lambda: get_computing_activity(equipment_id))


__all__ = (
    "ComputingActivityAPIView",
    "ComputingActivitySerializer",
)
