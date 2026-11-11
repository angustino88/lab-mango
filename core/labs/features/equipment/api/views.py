"""Contract-based API views for redesigned equipment resources."""

from typing import Any

from asgiref.sync import sync_to_async
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.common.api.filtering import FilterMetadataMixin, FilterMetadataSerializer
from core.common.api.options import OptionsQueryMixin, SizeClass
from core.common.api.pagination import PageNumberQuerySerializer, ResultsSetPagination
from core.labs.features.base.common import OptionsAPIView
from core.labs.features.equipment.api.serializers import (
    EquipmentCategorySerializer,
    EquipmentKindSerializer,
    EquipmentManufacturerSerializer,
    EquipmentProductModelSerializer,
    EquipmentTypeSerializer,
)
from core.labs.features.equipment.application import (
    AssignEquipmentInput,
    ChangeEquipmentStatusInput,
    CreateEquipmentInput,
    UnassignEquipmentInput,
    assign_equipment,
    change_equipment_status,
    create_equipment,
    unassign_equipment,
)
from core.labs.features.equipment.queries import (
    category_options_queryset,
    equipment_reference_data,
    get_active_equipment_assignment,
    get_equipment,
    list_equipment,
    list_equipment_options,
)
from core.labs.features.equipment.queries.reference_data import (
    get_department,
    get_equipment_category,
    get_equipment_kind,
    get_equipment_manufacturer,
    get_equipment_product_model,
    get_equipment_type,
    get_resource_group,
    list_department_options,
    list_departments,
    list_equipment_categories,
    list_equipment_category_options,
    list_equipment_kind_options,
    list_equipment_kinds,
    list_equipment_manufacturer_options,
    list_equipment_manufacturers,
    list_equipment_product_model_options,
    list_equipment_product_models,
    list_equipment_type_options,
    list_equipment_types,
    list_resource_group_options,
    list_resource_groups,
)
from core.labs.models import Equipment
from core.labs.models.resource.equipment.assignment import EquipmentAssignment

from ..queries.summaries import (
    get_computing_activity_summary,
    get_equipment_category_status_summary,
    get_equipment_status_summary,
)
from .common import EquipmentAPIView
from .resource_filters import EQUIPMENT_FILTERS
from .serializers import (
    CategoryOptionsQuerySerializer,
    ComputingActivitySummarySerializer,
    DepartmentSerializer,
    EquipmentAssignmentResultSerializer,
    EquipmentAssignmentSerializer,
    EquipmentCreateSerializer,
    EquipmentKindOptionsQuerySerializer,
    EquipmentManufacturerOptionsQuerySerializer,
    EquipmentOptionsQuerySerializer,
    EquipmentProductModelOptionsQuerySerializer,
    EquipmentReferenceDataSerializer,
    EquipmentSerializer,
    EquipmentStatusSerializer,
    EquipmentStatusSummarySerializer,
    EquipmentTypeOptionsQuerySerializer,
    ResourceGroupCatalogSerializer,
    ResourceGroupOptionsQuerySerializer,
)

EquipmentListQuerySerializer = EQUIPMENT_FILTERS.serializer("EquipmentListQuerySerializer")


class EquipmentStatusSummaryAPIView(EquipmentAPIView):
    """Non-deleted equipment by latest recorded lifecycle status; no filters."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentStatusSummaryData", EquipmentStatusSummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        if request.query_params:
            return self.respond_problem(
                "bad_request", code="invalid_query", detail="This endpoint accepts no query parameters."
            )
        return self.respond(get_equipment_status_summary())


class ComputingActivitySummaryAPIView(EquipmentAPIView):
    """All non-deleted computing assets by stored activity; missing telemetry is unknown."""

    get_contract = OperationContract(
        success=ResponseContract.success("ComputingActivitySummaryData", ComputingActivitySummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        if request.query_params:
            return self.respond_problem(
                "bad_request", code="invalid_query", detail="This endpoint accepts no query parameters."
            )
        return self.respond(get_computing_activity_summary())


class EquipmentCategorySummaryAPIView(EquipmentAPIView):
    """Summary of one equipment subtype, configured by category route generation."""

    category_key = None
    category_model = None

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentCategoryStatusSummaryData", EquipmentStatusSummarySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        if request.query_params:
            return self.respond_problem(
                "bad_request", code="invalid_query", detail="This endpoint accepts no query parameters."
            )
        if self.category_model is None:
            raise TypeError("Equipment category summary view must define category_model")
        return self.respond(get_equipment_category_status_summary(equipment_model=self.category_model))


class EquipmentListAPIView(AppListAPIView, EquipmentAPIView):
    """Paginated response adapter for the generic equipment collection."""

    pagination_class = ResultsSetPagination
    get_contract = OperationContract(
        query=EquipmentListQuerySerializer,
        success=ResponseContract.paginated("EquipmentList", EquipmentSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        queryset = EQUIPMENT_FILTERS.apply(list_equipment(), filters)
        return self.list_response_sync(queryset)


class EquipmentFiltersAPIView(FilterMetadataMixin, EquipmentAPIView):
    filter_spec = EQUIPMENT_FILTERS
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.success("EquipmentFilters", FilterMetadataSerializer),
    )


class EquipmentListCreateAPIView(EquipmentListAPIView):
    """List equipment with filters, or create a base equipment record."""

    post_contract = OperationContract(
        request=EquipmentCreateSerializer,
        success=ResponseContract.created("EquipmentCreate", EquipmentSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
    )

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        equipment = create_equipment(
            CreateEquipmentInput(fields=tuple(serializer.validated_data.items())),
            actor=request.user,
        )
        return self.respond(equipment)


class EquipmentRetrieveAPIView(EquipmentAPIView):
    """Retrieve one equipment record."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentDetail", EquipmentSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        return self.respond(get_equipment(equipment_id))


class EquipmentAssignmentAPIView(EquipmentAPIView):
    """Assign equipment to a bench, or release its current assignment."""

    post_contract = OperationContract(
        request=EquipmentAssignmentSerializer,
        success=ResponseContract.success("EquipmentAssignment", EquipmentAssignmentResultSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentAssignmentDetail", EquipmentAssignmentResultSerializer),
        not_found=ResponseContract.not_found(),
    )
    delete_contract = OperationContract(
        success=ResponseContract.no_content(),
        not_found=ResponseContract.not_found(),
    )

    def handle_post(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assignment = assign_equipment(
            AssignEquipmentInput(
                equipment_id=equipment_id,
                bench_id=serializer.validated_data["bench_id"],
                role=serializer.validated_data["role"],
                position=serializer.validated_data["position"],
            ),
            actor=request.user,
        )
        return self.respond(assignment)

    async def get(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        try:
            assignment = await sync_to_async(get_active_equipment_assignment)(equipment_id=equipment_id)
        except EquipmentAssignment.DoesNotExist:
            return self.respond_problem("not_found")
        data = EquipmentAssignmentResultSerializer(assignment, context={"request": request}).data
        return self.respond_data(data)

    async def delete(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        try:
            await sync_to_async(unassign_equipment)(UnassignEquipmentInput(equipment_id), actor=request.user)
        except Equipment.DoesNotExist:
            return self.respond_problem("not_found")
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    get=extend_schema(
        deprecated=True,
        description="Deprecated alias for equipment assignment. Use /api/labs/equipment/{equipment_id}/assignment instead.",
    ),
    post=extend_schema(
        deprecated=True,
        description="Deprecated alias for equipment assignment. Use /api/labs/equipment/{equipment_id}/assignment instead.",
    ),
    delete=extend_schema(
        deprecated=True,
        description="Deprecated alias for equipment assignment. Use /api/labs/equipment/{equipment_id}/assignment instead.",
    ),
)
class DeprecatedEquipmentAssignmentActionAPIView(EquipmentAssignmentAPIView):
    """Deprecated alias for equipment assignment.

    Use /api/labs/equipment/{equipment_id}/assignment instead.
    """

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Sunset"] = "Wed, 01 Jul 2027 00:00:00 GMT"
        equipment_id = kwargs.get("equipment_id")
        if equipment_id:
            response["Link"] = f'</api/labs/equipment/{equipment_id}/assignment>; rel="successor-version"'
        return response


class EquipmentStatusAPIView(EquipmentAPIView):
    """Record a new status for an equipment record."""

    post_contract = OperationContract(
        request=EquipmentStatusSerializer,
        success=ResponseContract.success("EquipmentDetailAfterStatusChange", EquipmentSerializer),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
    )

    def handle_post(self, request: Request, equipment_id: int, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        status_record = change_equipment_status(
            ChangeEquipmentStatusInput(
                equipment_id=equipment_id,
                status=serializer.validated_data["status"],
                details=tuple(serializer.validated_data["details"].items()),
            ),
            actor=request.user,
        )
        equipment = get_equipment(status_record.equipment_id)
        return self.respond(equipment)


class EquipmentCategoryStatusAPIView(EquipmentStatusAPIView):
    """Record a new status for a category equipment record."""

    model = None
    queryset_provider = None
    entity_name = None
    required_attributes = ("model", "queryset_provider")

    def handle_post(self, request: Request, pk: int = None, equipment_id: int = None, *args, **kwargs) -> Response:
        self.validate_configuration()
        target_id = pk if pk is not None else kwargs.get("id", kwargs.get("equipment_id", equipment_id))
        if target_id is None:
            return self.respond_problem("not_found")
        serializer, error = self.validate_request()
        if error is not None:
            return error
        if not self.queryset_provider().filter(pk=target_id).exists():
            return self.respond_problem("not_found")
        details_dict = serializer.validated_data.get("details") or {}
        user = getattr(request, "user", None)
        actor = user if getattr(user, "is_authenticated", False) else None
        status_record = change_equipment_status(
            ChangeEquipmentStatusInput(
                equipment_id=target_id,
                status=serializer.validated_data["status"],
                details=tuple(details_dict.items()),
            ),
            actor=actor,
        )
        instance = self.queryset_provider().get(pk=status_record.equipment_id)
        return self.respond(instance)


class EquipmentReferenceDataAPIView(EquipmentAPIView):
    """Generic equipment lookups. Computing-specific lookups live under computing/."""

    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentReferenceData", EquipmentReferenceDataSerializer),
        unauthorized=ResponseContract.unauthorized(),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        references = equipment_reference_data()
        data = {
            "categories": EquipmentCategorySerializer(references["categories"], many=True).data,
            "kinds": EquipmentKindSerializer(references["kinds"], many=True).data,
            "types": EquipmentTypeSerializer(references["types"], many=True).data,
            "manufacturers": EquipmentManufacturerSerializer(references["manufacturers"], many=True).data,
            "product_models": EquipmentProductModelSerializer(references["product_models"], many=True).data,
        }
        return self.respond_data(data)


class EquipmentOptionsAPIView(OptionsAPIView):
    """List equipment as compact options, optionally filtering for assignable items (ADR 002)."""

    schema_description = (
        "Large Equipment selectors require q or at least one declared parent filter: category_id, kind_id, "
        "type_id, or manufacturer_id. include_ids, lifecycle_status, assigned, and assignable do not satisfy "
        "this requirement."
    )
    query_serializer = EquipmentOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = (
        "q",
        "category_id",
        "kind_id",
        "type_id",
        "manufacturer_id",
    )
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_options(actor=actor, **filters)


class EquipmentCategoryOptionsAPIView(OptionsAPIView):
    """List category equipment as compact options, optionally filtering for assignable items (ADR 002)."""

    schema_description = (
        "Large category Equipment selectors require q or at least one declared parent filter: kind_id, type_id, "
        "or manufacturer_id. include_ids, lifecycle_status, assigned, and assignable do not satisfy this requirement."
    )
    model = None
    queryset_provider = None
    entity_name = None
    required_attributes = ("model", "queryset_provider")
    category_fields = ()

    query_serializer = CategoryOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = ("q", "kind_id", "type_id", "manufacturer_id")
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return category_options_queryset(self.model, self.category_fields, actor=actor, **filters)


# 1. Equipment Categories
class EquipmentCategoriesListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("EquipmentCategoriesCatalogList", EquipmentCategorySerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_equipment_categories())


class EquipmentCategoriesDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentCategoriesCatalogDetail", EquipmentCategorySerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, category_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_category(category_id=category_id))


class EquipmentCategoriesOptionsAPIView(OptionsAPIView):
    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_category_options(actor=actor, **filters)


# 2. Equipment Kinds
class EquipmentKindListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=EquipmentKindOptionsQuerySerializer,
        success=ResponseContract.paginated("EquipmentKindCatalogList", EquipmentKindSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_equipment_kinds(category_id=query.get("category_id") if query else None))


class EquipmentKindDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentKindCatalogDetail", EquipmentKindSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, kind_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_kind(kind_id=kind_id))


class EquipmentKindOptionsAPIView(OptionsAPIView):
    query_serializer = EquipmentKindOptionsQuerySerializer
    size_class = SizeClass.SMALL
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_kind_options(actor=actor, **filters)


# 3. Equipment Types
class EquipmentTypeListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=EquipmentTypeOptionsQuerySerializer,
        success=ResponseContract.paginated("EquipmentTypeCatalogList", EquipmentTypeSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        kind_id = query.get("kind_id") if query else None
        category_id = query.get("category_id") if query else None
        return self.list_response_sync(list_equipment_types(kind_id=kind_id, category_id=category_id))


class EquipmentTypeDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentTypeCatalogDetail", EquipmentTypeSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, type_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_type(type_id=type_id))


class EquipmentTypeOptionsAPIView(OptionsAPIView):
    query_serializer = EquipmentTypeOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = ("q", "kind_id", "category_id")
    schema_description = "Large Equipment type selectors require q, kind_id, or category_id."
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_type_options(actor=actor, **filters)


# 4. Equipment Manufacturers
class EquipmentManufacturerListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=EquipmentManufacturerOptionsQuerySerializer,
        success=ResponseContract.paginated("EquipmentManufacturerCatalogList", EquipmentManufacturerSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(
            list_equipment_manufacturers(category_id=query.get("category_id") if query else None)
        )


class EquipmentManufacturerDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentManufacturerCatalogDetail", EquipmentManufacturerSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, manufacturer_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_manufacturer(manufacturer_id=manufacturer_id))


class EquipmentManufacturerOptionsAPIView(OptionsAPIView):
    query_serializer = EquipmentManufacturerOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = ("q", "category_id")
    schema_description = "Large Equipment manufacturer selectors require q or category_id."
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_manufacturer_options(actor=actor, **filters)


# 5. Equipment Product Models
class EquipmentProductModelListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=EquipmentProductModelOptionsQuerySerializer,
        success=ResponseContract.paginated("EquipmentProductModelCatalogList", EquipmentProductModelSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        manufacturer_id = query.get("manufacturer_id") if query else None
        type_id = query.get("type_id") if query else None
        return self.list_response_sync(list_equipment_product_models(manufacturer_id=manufacturer_id, type_id=type_id))


class EquipmentProductModelDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("EquipmentProductModelCatalogDetail", EquipmentProductModelSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, model_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_equipment_product_model(model_id=model_id))


class EquipmentProductModelOptionsAPIView(OptionsAPIView):
    query_serializer = EquipmentProductModelOptionsQuerySerializer
    size_class = SizeClass.LARGE
    required_any = ("q", "manufacturer_id", "type_id")
    schema_description = "Large Equipment product-model selectors require q, manufacturer_id, or type_id."
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_equipment_product_model_options(actor=actor, **filters)


# 6. Departments
class DepartmentListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=PageNumberQuerySerializer,
        success=ResponseContract.paginated("DepartmentCatalogList", DepartmentSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error
        return self.list_response_sync(list_departments())


class DepartmentDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("DepartmentCatalogDetail", DepartmentSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, department_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_department(department_id=department_id))


class DepartmentOptionsAPIView(OptionsAPIView):
    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_department_options(actor=actor, **filters)


# 7. Resource Groups
class ResourceGroupListAPIView(AppListAPIView, EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        query=ResourceGroupOptionsQuerySerializer,
        success=ResponseContract.paginated("ResourceGroupCatalogList", ResourceGroupCatalogSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        department_id = query.get("department_id") if query else None
        return self.list_response_sync(list_resource_groups(department_id=department_id))


class ResourceGroupDetailAPIView(EquipmentAPIView):
    schema_tags = ("Equipment",)
    get_contract = OperationContract(
        success=ResponseContract.success("ResourceGroupCatalogDetail", ResourceGroupCatalogSerializer),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request, group_id: int, *args: Any, **kwargs: Any) -> Response:
        return self.respond(get_resource_group(group_id=group_id))


class ResourceGroupOptionsAPIView(OptionsAPIView):
    query_serializer = ResourceGroupOptionsQuerySerializer
    size_class = SizeClass.SMALL
    owner = "equipment"
    schema_tags = ("Equipment",)

    def select(self, *, actor: Any, filters: dict[str, Any]) -> Any:
        return list_resource_group_options(actor=actor, **filters)
