"""POST /api/labs/equipment/actions/match: equipment by specification requirements and free time. Read-only."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from core.labs.features.base import LAB_OPERATIONS_ACCESS, CommandAPIView, operation
from core.labs.features.base.serializers import (
    ChoiceReferenceSerializer,
    NamedReferenceSerializer,
    UIDNamedReferenceSerializer,
    to_choice_reference,
)
from core.labs.features.equipment.queries.matching import (
    MAX_REQUIREMENTS,
    MAX_RESULTS,
    MAX_WINDOW,
    MatchEquipmentInput,
    SpecRequirement,
    match_equipment,
)
from core.labs.models import ResourceCondition

SPEC_REQUIREMENT_OPS = ("eq", "neq", "gte", "lte", "between", "in", "contains")
_STATUS_LABELS = (("matched", "Matched"), ("missed", "Missed"), ("unknown", "Unknown"))


class SpecRequirementSerializer(serializers.Serializer):
    spec_definition_id = serializers.IntegerField(min_value=1)
    op = serializers.ChoiceField(
        choices=SPEC_REQUIREMENT_OPS,
        help_text="Numbers: eq, neq, gte, lte, between ([min, max]), in. Text: eq, neq, in, contains. Yes/no: eq, neq.",
    )
    value = serializers.JSONField(help_text="A number, text or yes/no; a list for in and between.")
    unit = serializers.CharField(
        required=False, allow_blank=True, max_length=20, help_text="Converted with SI prefixes, e.g. GHz to MHz."
    )
    # DRF removes declared fields from the class, so this API field does not replace Field.required.
    required = serializers.BooleanField(  # type: ignore[assignment]
        required=False, default=True, help_text="False: only raises the rank."
    )


class EquipmentMatchRequestSerializer(serializers.Serializer):
    requirements = serializers.ListField(
        child=SpecRequirementSerializer(), required=False, max_length=MAX_REQUIREMENTS, default=list
    )
    category_id = serializers.IntegerField(min_value=1, required=False)
    kind_id = serializers.IntegerField(min_value=1, required=False)
    type_id = serializers.IntegerField(min_value=1, required=False)
    manufacturer_id = serializers.IntegerField(min_value=1, required=False)
    product_model_id = serializers.IntegerField(min_value=1, required=False)
    department_id = serializers.IntegerField(min_value=1, required=False)
    room_id = serializers.IntegerField(min_value=1, required=False, help_text="Placed in this room now.")
    available_from = serializers.DateTimeField(required=False)
    available_until = serializers.DateTimeField(required=False, help_text="At most 31 days after available_from.")
    include_near_matches = serializers.BooleanField(
        required=False, default=False, help_text="Also units missing exactly one required requirement."
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=MAX_RESULTS, default=20)

    def validate(self, attrs):
        starts_at, ends_at = attrs.get("available_from"), attrs.get("available_until")
        if (starts_at is None) != (ends_at is None):
            raise serializers.ValidationError({"available_until": "Send available_from and available_until together."})
        if starts_at is not None and ends_at <= starts_at:
            raise serializers.ValidationError({"available_until": "The window must end after it starts."})
        if starts_at is not None and ends_at - starts_at > MAX_WINDOW:
            raise serializers.ValidationError({"available_until": "The window is at most 31 days."})
        return attrs

    def to_input(self) -> MatchEquipmentInput:
        data = dict(self.validated_data)
        requirements = tuple(
            SpecRequirement(
                definition_id=item["spec_definition_id"],
                op=item["op"],
                value=item["value"],
                unit=item.get("unit", ""),
                required=item["required"],
            )
            for item in data.pop("requirements")
        )
        return MatchEquipmentInput(requirements=requirements, **data)


class RequirementResultSerializer(serializers.Serializer):
    spec_definition_id = serializers.IntegerField(source="definition_id", read_only=True)
    name = serializers.CharField(read_only=True)
    status = serializers.SerializerMethodField(help_text="matched, missed, or unknown (no value for this model).")
    actual = serializers.CharField(read_only=True, allow_null=True)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.status, _STATUS_LABELS)


class EquipmentMatchSerializer(serializers.Serializer):
    equipment = UIDNamedReferenceSerializer(read_only=True)
    product_model = NamedReferenceSerializer(read_only=True)
    score = serializers.DecimalField(
        max_digits=3, decimal_places=2, read_only=True, help_text="Share of requirements met, 0 to 1."
    )
    is_full_match = serializers.BooleanField(read_only=True, help_text="Every required requirement is met.")
    requirements = RequirementResultSerializer(many=True, read_only=True)
    location = serializers.CharField(read_only=True, help_text="Current bench, station, room or note; may be empty.")
    condition = serializers.SerializerMethodField()
    is_on_loan = serializers.BooleanField(read_only=True)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_condition(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.condition, ResourceCondition.choices)


class EquipmentMatchResultSerializer(serializers.Serializer):
    """Full matches first, then near matches; within each, more optional matches first, then name."""

    is_truncated = serializers.BooleanField(read_only=True, help_text="More units matched than were returned.")
    matches = EquipmentMatchSerializer(many=True, read_only=True)


class EquipmentMatchActionAPIView(CommandAPIView):
    """Find units by specification requirements. Changes nothing: POST only because the body is structured."""

    permission_classes = LAB_OPERATIONS_ACCESS
    schema_tags = ("Equipment",)
    post_contract = operation(
        "EquipmentMatchAction",
        EquipmentMatchResultSerializer,
        request=EquipmentMatchRequestSerializer,
        bad_request=True,
        validation_error=True,
        forbidden=True,
    )

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if serializer is None:
            raise TypeError("Request validation returned neither a serializer nor an error.")
        data = serializer.to_input()
        return self._execute(lambda: match_equipment(data=data))
