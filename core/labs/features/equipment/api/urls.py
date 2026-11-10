from django.urls import include, path

from core.labs.features.equipment.api.category_definitions import CATEGORY_DEFINITIONS
from core.labs.features.equipment.categories.computing.api import ComputingActivityAPIView

from . import views
from .categories import build_category_urlpatterns
from .facets import EquipmentFacetsAPIView
from .reference_data import urlpatterns as reference_urlpatterns

urlpatterns = [
    path("equipment/status-summary", views.EquipmentStatusSummaryAPIView.as_view(), name="equipment-status-summary"),
    path(
        "equipment/computing/activity-summary",
        views.ComputingActivitySummaryAPIView.as_view(),
        name="computing-activity-summary",
    ),
    path("equipment", views.EquipmentListCreateAPIView.as_view(), name="equipment-list-create"),
    path("equipment/filters", views.EquipmentFiltersAPIView.as_view(), name="equipment-filters"),
    path("equipment/facets", EquipmentFacetsAPIView.as_view(), name="equipment-facets"),
    path("equipment/options", views.EquipmentOptionsAPIView.as_view(), name="equipment-options"),
    path("equipment/reference-data", views.EquipmentReferenceDataAPIView.as_view(), name="equipment-reference-data"),
    path("equipment/<int:equipment_id>", views.EquipmentRetrieveAPIView.as_view(), name="equipment-retrieve"),
    path(
        "equipment/<int:equipment_id>/actions/assign",
        views.DeprecatedEquipmentAssignmentActionAPIView.as_view(),
        name="equipment-action-assign",
    ),
    path(
        "equipment/<int:equipment_id>/assignment",
        views.EquipmentAssignmentAPIView.as_view(),
        name="equipment-assignment-detail",
    ),
    path(
        "equipment/<int:equipment_id>/placement",
        views.EquipmentPlacementAPIView.as_view(),
        name="equipment-placement-detail",
    ),
    path("equipment/<int:equipment_id>/loan", views.EquipmentLoanAPIView.as_view(), name="equipment-loan-detail"),
    path(
        "equipment/<int:equipment_id>/actions/hand-over",
        views.EquipmentHandOverAPIView.as_view(),
        name="equipment-action-hand-over",
    ),
    path(
        "equipment/<int:equipment_id>/actions/return",
        views.EquipmentReturnAPIView.as_view(),
        name="equipment-action-return",
    ),
    path(
        "equipment/<int:equipment_id>/actions/extend-loan",
        views.EquipmentExtendLoanAPIView.as_view(),
        name="equipment-action-extend-loan",
    ),
    path(
        "equipment/<int:equipment_id>/actions/change-condition",
        views.EquipmentChangeConditionAPIView.as_view(),
        name="equipment-action-change-condition",
    ),
    path(
        "equipment/<int:equipment_id>/actions/change-lifecycle",
        views.EquipmentChangeLifecycleAPIView.as_view(),
        name="equipment-action-change-lifecycle",
    ),
    path(
        "equipment/computing/sku/<str:sku>/activity",
        ComputingActivityAPIView.as_view(),
        name="computing-activity",
    ),

    # Lookup catalogs and options (ADR 002)
    path("equipment-categories", views.EquipmentCategoriesListAPIView.as_view(), name="equipment-category-list"),
    path("equipment-categories/options", views.EquipmentCategoriesOptionsAPIView.as_view(), name="equipment-category-options"),
    path("equipment-categories/<int:category_id>", views.EquipmentCategoriesDetailAPIView.as_view(), name="equipment-category-detail"),

    path("equipment-kinds", views.EquipmentKindListAPIView.as_view(), name="equipment-kind-list"),
    path("equipment-kinds/options", views.EquipmentKindOptionsAPIView.as_view(), name="equipment-kind-options"),
    path("equipment-kinds/<int:kind_id>", views.EquipmentKindDetailAPIView.as_view(), name="equipment-kind-detail"),

    path("equipment-types", views.EquipmentTypeListAPIView.as_view(), name="equipment-type-list"),
    path("equipment-types/options", views.EquipmentTypeOptionsAPIView.as_view(), name="equipment-type-options"),
    path("equipment-types/<int:type_id>", views.EquipmentTypeDetailAPIView.as_view(), name="equipment-type-detail"),

    path("equipment-manufacturers", views.EquipmentManufacturerListAPIView.as_view(), name="equipment-manufacturer-list"),
    path("equipment-manufacturers/options", views.EquipmentManufacturerOptionsAPIView.as_view(), name="equipment-manufacturer-options"),
    path("equipment-manufacturers/<int:manufacturer_id>", views.EquipmentManufacturerDetailAPIView.as_view(), name="equipment-manufacturer-detail"),

    path("equipment-product-models", views.EquipmentProductModelListAPIView.as_view(), name="equipment-product-model-list"),
    path("equipment-product-models/options", views.EquipmentProductModelOptionsAPIView.as_view(), name="equipment-product-model-options"),
    path("equipment-product-models/<int:model_id>", views.EquipmentProductModelDetailAPIView.as_view(), name="equipment-product-model-detail"),

    path("departments", views.DepartmentListAPIView.as_view(), name="department-list"),
    path("departments/options", views.DepartmentOptionsAPIView.as_view(), name="department-options"),
    path("departments/<int:department_id>", views.DepartmentDetailAPIView.as_view(), name="department-detail"),

    path("resource-groups", views.ResourceGroupListAPIView.as_view(), name="resource-group-list"),
    path("resource-groups/options", views.ResourceGroupOptionsAPIView.as_view(), name="resource-group-options"),
    path("resource-groups/<int:group_id>", views.ResourceGroupDetailAPIView.as_view(), name="resource-group-detail"),
]

urlpatterns += [
    path(
        "equipment/",
        include(build_category_urlpatterns(definition, module=__name__)),
    )
    for definition in CATEGORY_DEFINITIONS.values()
]
urlpatterns += reference_urlpatterns
