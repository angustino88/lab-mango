"""The single equipment collection: ``/api/labs/equipment`` (redesign step 6, decision B).

One table and one route set for every category. The category comes from ``kind.category``;
typed fields a category does not use are ``null`` (or empty) in responses and refused on write.
Computing units also carry a ``computing`` object (``ComputingProfile``) and their live
``activity`` on the detail.
"""

from typing import Any, ClassVar

from asgiref.sync import markcoroutinefunction
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema_view
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.filtering import Filter, FilterMetadataMixin, FilterMetadataSerializer, PositiveIDField
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.features.base.serializers import NamedReferenceSerializer
from core.labs.features.equipment.categories.computing.api import ComputingActivitySerializer
from core.labs.features.equipment.queries import equipment_form_reference_data, equipment_queryset
from core.labs.models import ComputingProfile, Equipment, TechnicalUser
from core.users.public import with_entra_access_token

from .category_serializers import (
    EQUIPMENT_CREATE_ONLY_FIELDS,
    EQUIPMENT_WRITE_FIELDS,
    EquipmentFormReferenceSerializer,
    EquipmentWriteSerializer,
)
from .common import EquipmentAPIView
from .facets import EquipmentFacetsAPIView, EquipmentFacetSerializer, facet_filter_spec, facet_query_serializer
from .list_create import EquipmentListCreateAPIView
from .retrieve_update_by_key import EquipmentByKeyRetrieveUpdateAPIView
from .retrieve_update_delete import EquipmentRetrieveUpdateDeleteAPIView
from .serializers import EquipmentCategorySerializer, EquipmentSerializer
from .views import EquipmentStateActionAPIView, state_action_contract

# Typed columns on Equipment (decision A); which category uses which is in application/_category.py.
TYPED_SCALAR_FIELDS = ("mac_address", "channels", "power_rating", "dimensions")
TYPED_REFERENCE_FIELDS = ("material", "size", "resolution", "protocol", "customer")
TYPED_MANY_FIELDS = ("interfaces", "characteristics")
TYPED_FIELDS = TYPED_SCALAR_FIELDS + TYPED_REFERENCE_FIELDS + TYPED_MANY_FIELDS

SEARCH_FIELDS = (
    "sku",
    "name",
    "serial_number",
    "log_label",
    "kind__name",
    "manufacturer__name",
    "product_model__name",
    "mac_address",
    "computing_profile__hostname",
    "computing_profile__ip_address",
    "computing_profile__os_name",
)
TYPED_FILTERS = (
    Filter("material_id", PositiveIDField(), "material", "reference", options_key="materials"),
    Filter("size_id", PositiveIDField(), "size", "reference", options_key="sizes"),
    Filter("resolution_id", PositiveIDField(), "resolution", "reference", options_key="resolutions"),
    Filter("protocol_id", PositiveIDField(), "protocol", "reference", options_key="protocols"),
    Filter("customer_id", PositiveIDField(), "customer", "reference", options_key="customers"),
    Filter(
        "technical_user_id",
        PositiveIDField(),
        "computing_profile__technical_user",
        "reference",
        options_key="technical_users",
    ),
)


class _LabelReferenceSerializer(NamedReferenceSerializer):
    """``{id, name}`` for lookups whose label column is not ``name``."""

    label_field: ClassVar[str] = "name"

    def to_representation(self, instance):
        return {"id": instance.pk, "name": getattr(instance, self.label_field)}


class DisplaySizeReferenceSerializer(_LabelReferenceSerializer):
    label_field = "size"

    class Meta:
        ref_name = "EquipmentDisplaySizeReference"


class DisplayResolutionReferenceSerializer(_LabelReferenceSerializer):
    label_field = "resolution"

    class Meta:
        ref_name = "EquipmentDisplayResolutionReference"


class TechnicalUserReferenceSerializer(_LabelReferenceSerializer):
    label_field = "username"

    class Meta:
        ref_name = "TechnicalUserReference"


class ComputingProfileSerializer(serializers.ModelSerializer):
    """Computing columns of a monitored unit; ``null`` for every other unit."""

    technical_user = TechnicalUserReferenceSerializer(read_only=True, allow_null=True)

    class Meta:
        model = ComputingProfile
        fields = (
            "hostname",
            "ip_address",
            "os_name",
            "disk_usage",
            "system_info",
            "monitored_devices",
            "rdp_file",
            "technical_user",
        )
        read_only_fields = fields
        ref_name = "EquipmentComputingProfile"


class EquipmentItemSerializer(EquipmentSerializer):
    """One unit in the equipment list: shared fields, typed fields, and its computing profile."""

    material = NamedReferenceSerializer(read_only=True, allow_null=True)
    size = DisplaySizeReferenceSerializer(read_only=True, allow_null=True)
    resolution = DisplayResolutionReferenceSerializer(read_only=True, allow_null=True)
    protocol = NamedReferenceSerializer(read_only=True, allow_null=True)
    customer = NamedReferenceSerializer(read_only=True, allow_null=True)
    interfaces = NamedReferenceSerializer(many=True, read_only=True)
    characteristics = NamedReferenceSerializer(many=True, read_only=True)
    computing = ComputingProfileSerializer(source="computing_profile", read_only=True, allow_null=True)

    class Meta(EquipmentSerializer.Meta):
        fields = EquipmentSerializer.Meta.fields + TYPED_FIELDS + ("computing",)  # type: ignore[assignment]
        read_only_fields = fields  # type: ignore[assignment]


class EquipmentDetailSerializer(EquipmentItemSerializer):
    """One unit with its notes and, for computing units, the live activity."""

    activity = ComputingActivitySerializer(read_only=True, allow_null=True)

    class Meta(EquipmentItemSerializer.Meta):
        fields = EquipmentItemSerializer.Meta.fields + ("activity", "details")  # type: ignore[assignment]
        read_only_fields = fields  # type: ignore[assignment]


class ComputingProfileCreateSerializer(serializers.Serializer):
    hostname = serializers.CharField(max_length=255, required=False, allow_blank=True)

    class Meta:
        ref_name = "EquipmentComputingProfileCreate"


class ComputingProfileUpdateSerializer(serializers.Serializer):
    monitored_devices = serializers.JSONField(required=False)
    technical_user_id = serializers.PrimaryKeyRelatedField(
        source="technical_user", queryset=TechnicalUser.objects.all(), allow_null=True, required=False
    )

    class Meta:
        ref_name = "EquipmentComputingProfileUpdate"


class EquipmentCreateSerializer(EquipmentWriteSerializer):
    computing = ComputingProfileCreateSerializer(required=False)

    class Meta:
        model = Equipment
        fields = EQUIPMENT_WRITE_FIELDS + EQUIPMENT_CREATE_ONLY_FIELDS + TYPED_FIELDS + ("computing",)


class EquipmentUpdateSerializer(EquipmentWriteSerializer):
    computing = ComputingProfileUpdateSerializer(required=False)

    class Meta:
        model = Equipment
        fields = EQUIPMENT_WRITE_FIELDS + TYPED_FIELDS + ("computing",)


def _lookup_serializer(name: str, model: type, label: str) -> type[serializers.ModelSerializer]:
    meta = type("Meta", (), {"model": model, "fields": ("id", label), "read_only_fields": ("id", label)})
    return type(name, (serializers.ModelSerializer,), {"__module__": __name__, "Meta": meta})


def _lookups() -> dict[str, Any]:
    from core.labs.models.resource.equipment import (
        DisplayResolution,
        DisplaySize,
        EquipmentInterface,
        Material,
        NetworkingProtocol,
        SampleCharacteristic,
        SampleCustomer,
    )

    return {
        "materials": _lookup_serializer("EquipmentMaterialOptionSerializer", Material, "name")(
            many=True, read_only=True
        ),
        "sizes": _lookup_serializer("EquipmentDisplaySizeOptionSerializer", DisplaySize, "size")(
            many=True, read_only=True
        ),
        "resolutions": _lookup_serializer(
            "EquipmentDisplayResolutionOptionSerializer", DisplayResolution, "resolution"
        )(many=True, read_only=True),
        "protocols": _lookup_serializer("EquipmentNetworkingProtocolOptionSerializer", NetworkingProtocol, "name")(
            many=True, read_only=True
        ),
        "customers": _lookup_serializer("EquipmentSampleCustomerOptionSerializer", SampleCustomer, "name")(
            many=True, read_only=True
        ),
        "interfaces": _lookup_serializer("EquipmentInterfaceOptionSerializer", EquipmentInterface, "name")(
            many=True, read_only=True
        ),
        "characteristics": _lookup_serializer(
            "EquipmentSampleCharacteristicOptionSerializer", SampleCharacteristic, "name"
        )(many=True, read_only=True),
        "technical_users": _lookup_serializer("EquipmentTechnicalUserOptionSerializer", TechnicalUser, "username")(
            many=True, read_only=True
        ),
    }


EquipmentReferenceDataSerializer = type(
    "EquipmentReferenceDataSerializer",
    (EquipmentFormReferenceSerializer,),
    {
        "__module__": __name__,
        "categories": EquipmentCategorySerializer(many=True, read_only=True),
        **_lookups(),
    },
)


class EquipmentReferenceDataQuerySerializer(serializers.Serializer):
    category = serializers.IntegerField(required=False, min_value=1, help_text="Narrow kinds, types and makers.")


class EquipmentReferenceDataAPIView(EquipmentAPIView):
    """Everything the equipment form needs, optionally for one category."""

    get_contract = OperationContract(
        query=EquipmentReferenceDataQuerySerializer,
        success=ResponseContract.success("EquipmentReferenceData", EquipmentReferenceDataSerializer),
        bad_request=ResponseContract.bad_request(),
        unauthorized=ResponseContract.unauthorized(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        return self.respond(equipment_form_reference_data(category_id=(filters or {}).get("category")))


_COMMON: dict[str, Any] = {
    "__module__": __name__,
    "model": Equipment,
    "queryset_provider": staticmethod(equipment_queryset),
    "entity_name": "equipment",
}


class EquipmentCollectionAPIView(EquipmentListCreateAPIView):
    """List every equipment unit (filter by ``category``), or create one."""

    model = Equipment  # type: ignore[assignment]
    queryset_provider = staticmethod(equipment_queryset)  # type: ignore[assignment]
    entity_name = "equipment"  # type: ignore[assignment]
    list_serializer_class = EquipmentItemSerializer  # type: ignore[assignment]
    create_response_serializer_class = EquipmentDetailSerializer  # type: ignore[assignment]
    create_serializer_class = EquipmentCreateSerializer  # type: ignore[assignment]
    text_search_fields: ClassVar[list[str]] = list(SEARCH_FIELDS)
    list_filters: ClassVar[tuple] = TYPED_FILTERS


class EquipmentFiltersAPIView(FilterMetadataMixin, EquipmentAPIView):
    filter_spec = EquipmentCollectionAPIView.filter_spec
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.success("EquipmentFilters", FilterMetadataSerializer),
        bad_request=ResponseContract.bad_request(),
    )


_FACET_SPEC = facet_filter_spec(EquipmentCollectionAPIView.filter_spec)


class EquipmentCollectionFacetsAPIView(EquipmentFacetsAPIView):
    queryset_provider = staticmethod(equipment_queryset)
    filter_spec = _FACET_SPEC
    get_contract = OperationContract(
        query=facet_query_serializer("EquipmentFacetsQuerySerializer", _FACET_SPEC),
        success=ResponseContract.paginated("EquipmentFacets", EquipmentFacetSerializer),
        bad_request=ResponseContract.bad_request(),
    )


class EquipmentDetailAPIView(EquipmentRetrieveUpdateDeleteAPIView):
    """Read, change or delete one unit."""

    model = Equipment  # type: ignore[assignment]
    queryset_provider = staticmethod(equipment_queryset)  # type: ignore[assignment]
    entity_name = "equipment"  # type: ignore[assignment]
    response_serializer_class = EquipmentDetailSerializer  # type: ignore[assignment]
    update_serializer_class = EquipmentUpdateSerializer  # type: ignore[assignment]
    schema_tags = ("Equipment",)


def _by_key_view(label: str, lookup_field: str, **extra: Any):
    response = ResponseContract.success(f"EquipmentBy{label}", EquipmentDetailSerializer)
    return type(
        f"EquipmentBy{label}APIView",
        (EquipmentByKeyRetrieveUpdateAPIView,),
        {
            **_COMMON,
            "lookup_field": lookup_field,
            "lookup_kwarg": lookup_field,
            "get_contract": OperationContract(success=response, not_found=ResponseContract.not_found()),
            "patch_contract": OperationContract(
                request=EquipmentUpdateSerializer,
                success=response,
                bad_request=ResponseContract.bad_request(),
                validation_error=ResponseContract.problem(422),
                not_found=ResponseContract.not_found(),
                conflict=ResponseContract.conflict(),
            ),
            **extra,
        },
    )


EquipmentBySKUAPIView = _by_key_view("SKU", "sku")
# The desktop audit tool reads detail by uid with an Entra access token; PATCH still needs a Lab Mango JWT.
EquipmentByUIDAPIView = _by_key_view("UID", "uid", authentication_classes=with_entra_access_token(read_only=True))


def _state_view(action: str, label: str):
    contract = state_action_contract(action, f"EquipmentDetailAfter{label}Change", EquipmentDetailSerializer)
    view = type(
        f"EquipmentChange{label}APIView",
        (EquipmentStateActionAPIView,),
        {**_COMMON, "action": action, "post_contract": contract},
    )
    extend_schema_view(post=contract.schema())(view)
    markcoroutinefunction(view.post)  # type: ignore[attr-defined]
    return view


EquipmentChangeConditionAPIView = _state_view("condition", "Condition")
EquipmentChangeLifecycleAPIView = _state_view("lifecycle", "Lifecycle")


__all__ = (
    "ComputingProfileSerializer",
    "EquipmentByKeyRetrieveUpdateAPIView",
    "EquipmentBySKUAPIView",
    "EquipmentByUIDAPIView",
    "EquipmentChangeConditionAPIView",
    "EquipmentChangeLifecycleAPIView",
    "EquipmentCollectionAPIView",
    "EquipmentCollectionFacetsAPIView",
    "EquipmentCreateSerializer",
    "EquipmentDetailAPIView",
    "EquipmentDetailSerializer",
    "EquipmentFiltersAPIView",
    "EquipmentItemSerializer",
    "EquipmentReferenceDataAPIView",
    "EquipmentUpdateSerializer",
)
