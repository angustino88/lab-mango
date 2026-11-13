from django.urls import path

from core.labs.features.equipment.categories.computing.api import ComputingActivityAPIView

from . import collection, views
from .reference_data import urlpatterns as reference_urlpatterns

urlpatterns = [
    path("equipment/status-summary", views.EquipmentStatusSummaryAPIView.as_view(), name="equipment-status-summary"),
    path(
        "equipment/computing/activity-summary",
        views.ComputingActivitySummaryAPIView.as_view(),
        name="computing-activity-summary",
    ),
    # One collection for every category (redesign step 6, decision B).
    path("equipment", collection.EquipmentCollectionAPIView.as_view(), name="equipment-list-create"),
    path("equipment/filters", collection.EquipmentFiltersAPIView.as_view(), name="equipment-filters"),
    path("equipment/facets", collection.EquipmentCollectionFacetsAPIView.as_view(), name="equipment-facets"),
    path("equipment/options", views.EquipmentOptionsAPIView.as_view(), name="equipment-options"),
    path(
        "equipment/reference-data",
        collection.EquipmentReferenceDataAPIView.as_view(),
        name="equipment-reference-data",
    ),
    path("equipment/sku/<str:sku>", collection.EquipmentBySKUAPIView.as_view(), name="equipment-by-sku"),
    path("equipment/uid/<uuid:uid>", collection.EquipmentByUIDAPIView.as_view(), name="equipment-by-uid"),
    path("equipment/<int:pk>", collection.EquipmentDetailAPIView.as_view(), name="equipment-retrieve"),
    path("equipment/<int:equipment_id>/image", views.EquipmentImageAPIView.as_view(), name="equipment-image"),
    path(
        "equipment/<int:equipment_id>/activity",
        ComputingActivityAPIView.as_view(),
        name="equipment-activity",
    ),
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
    path("equipment-loans", views.EquipmentLoanListCreateAPIView.as_view(), name="equipment-loan-list-create"),
    path(
        "equipment-loans/actions/return",
        views.EquipmentLoanReturnBatchAPIView.as_view(),
        name="equipment-loan-action-return",
    ),
    path(
        "equipment-loans/actions/extend",
        views.EquipmentLoanExtendBatchAPIView.as_view(),
        name="equipment-loan-action-extend",
    ),
    path(
        "equipment-loan-batches/<int:batch_id>",
        views.EquipmentLoanBatchAPIView.as_view(),
        name="equipment-loan-batch-detail",
    ),
    path(
        "equipment-reservations",
        views.EquipmentReservationListCreateAPIView.as_view(),
        name="equipment-reservation-list-create",
    ),
    path(
        "equipment-reservations/<int:batch_id>",
        views.EquipmentReservationDetailAPIView.as_view(),
        name="equipment-reservation-detail",
    ),
    path(
        "equipment-reservations/<int:batch_id>/actions/cancel",
        views.EquipmentReservationCancelAPIView.as_view(),
        name="equipment-reservation-action-cancel",
    ),
    path(
        "equipment-reservations/<int:batch_id>/actions/hand-over",
        views.EquipmentReservationHandOverAPIView.as_view(),
        name="equipment-reservation-action-hand-over",
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
        "equipment/<int:equipment_id>/status-changes",
        views.EquipmentStatusChangeListAPIView.as_view(),
        name="equipment-status-change-list",
    ),
    path(
        "equipment/<int:equipment_id>/actions/change-condition",
        collection.EquipmentChangeConditionAPIView.as_view(),
        name="equipment-action-change-condition",
    ),
    path(
        "equipment/<int:equipment_id>/actions/change-lifecycle",
        collection.EquipmentChangeLifecycleAPIView.as_view(),
        name="equipment-action-change-lifecycle",
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

    path("groups", views.GroupListAPIView.as_view(), name="group-list"),
    path("groups/options", views.GroupOptionsAPIView.as_view(), name="group-options"),
    path("groups/<int:group_id>", views.GroupDetailAPIView.as_view(), name="group-detail"),
]

urlpatterns += reference_urlpatterns
