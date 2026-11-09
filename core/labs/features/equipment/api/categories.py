"""Build HTTP adapters and schemas for declared equipment categories."""

import sys
from functools import partial
from typing import cast

from asgiref.sync import markcoroutinefunction
from django.core.exceptions import FieldDoesNotExist
from django.urls import path
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import extend_schema_view
from rest_framework import serializers, status

from core.common.api.filtering import FilterMetadataMixin, FilterMetadataSerializer
from core.common.api.options import CatalogOptionListSerializer, CatalogOptionSerializer
from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.features.base.serializers import NamedReferenceSerializer
from core.labs.features.equipment.api.category_definitions import EquipmentCategoryAPIConfig
from core.labs.features.equipment.api.category_serializers import (
    EQUIPMENT_WRITE_FIELDS,
    EquipmentFormReferenceSerializer,
    EquipmentWriteSerializer,
)
from core.labs.features.equipment.api.common import EquipmentAPIView
from core.labs.features.equipment.api.facets import (
    EquipmentFacetsAPIView,
    EquipmentFacetSerializer,
    facet_filter_spec,
    facet_query_serializer,
)
from core.labs.features.equipment.api.list_create import EquipmentListCreateAPIView
from core.labs.features.equipment.api.registry import EQUIPMENT_REGISTRY
from core.labs.features.equipment.api.retrieve_update_by_key import EquipmentByKeyRetrieveUpdateAPIView
from core.labs.features.equipment.api.retrieve_update_delete import EquipmentRetrieveUpdateDeleteAPIView
from core.labs.features.equipment.api.serializers import (
    CategoryOptionsQuerySerializer,
    EquipmentSerializer,
    EquipmentStatusSerializer,
    EquipmentStatusSummarySerializer,
)
from core.labs.features.equipment.api.views import (
    EquipmentCategoryOptionsAPIView,
    EquipmentCategoryStatusAPIView,
    EquipmentCategorySummaryAPIView,
)
from core.labs.features.equipment.queries import category_queryset, category_reference_data


class EquipmentCategoryReferenceAPIView(EquipmentAPIView):
    definition = None

    def handle_get(self, request, *args, **kwargs):
        payload = category_reference_data(self.definition.key, self.definition.lookups)
        return self.respond(payload)


def build_category_urlpatterns(definition: EquipmentCategoryAPIConfig, *, module: str):
    """Build named, schema-discoverable classes from an explicit field allowlist."""
    registry_definition = EQUIPMENT_REGISTRY[definition.key]
    prefix = registry_definition.model.__name__.removesuffix("Equipment")
    if not definition.searchable_fields:
        raise ValueError(f"{definition.key} must explicitly declare searchable_fields")

    def resolve_path(configured_path: str) -> bool:
        model = registry_definition.model
        path_parts = configured_path.split("__")
        may_duplicate = False
        for index, path_part in enumerate(path_parts):
            try:
                field = model._meta.get_field(path_part)
            except FieldDoesNotExist as exc:
                if index == len(path_parts) - 1 and path_part in {
                    "exact",
                    "iexact",
                    "contains",
                    "icontains",
                    "gte",
                    "gt",
                    "lte",
                    "lt",
                    "isnull",
                }:
                    break
                raise ValueError(f"Invalid configured model path: {configured_path}") from exc
            may_duplicate = may_duplicate or field.many_to_many or field.one_to_many
            if index < len(path_parts) - 1:
                if not field.is_relation or field.related_model is None:
                    raise ValueError(f"Invalid searchable field path: {configured_path}")
                model = field.related_model

        return may_duplicate

    distinct_search = any(resolve_path(field_path) for field_path in definition.searchable_fields)
    for configured_filter in definition.list_filters:
        if "__" in configured_filter.lookup:
            raise ValueError(f"Category filter {configured_filter.name} must target a direct foreign-key field")
        try:
            filter_field = registry_definition.model._meta.get_field(configured_filter.lookup)
        except FieldDoesNotExist as exc:
            raise ValueError(f"Unknown category filter field: {configured_filter.lookup}") from exc
        if not filter_field.many_to_one or filter_field.many_to_many or filter_field.related_model is None:
            raise ValueError(f"Category filter {configured_filter.name} must target a direct foreign-key field")
    category_filters = definition.list_filters

    def serializer_class(name, base, fields, *, readonly=False, attributes=None):
        meta = type(
            "Meta",
            (),
            {
                "model": registry_definition.model,
                "fields": fields,
                "read_only_fields": fields if readonly else (),
            },
        )
        return type(name, (base,), {"__module__": module, "Meta": meta, **(attributes or {})})

    list_fields = definition.fields_for("list")
    create_fields = definition.fields_for("create")
    update_fields = definition.fields_for("update")
    detail_fields = definition.fields_for("detail")

    relation_serializer_cache = {}

    def get_label_fields(fields):
        result = {}
        for name in fields:
            field = registry_definition.model._meta.get_field(name)
            if field.many_to_one:
                display = next(
                    (label for _, model, label in definition.lookups if model is field.related_model),
                    "name",
                )
                attributes = {
                    "name": serializers.CharField(read_only=True)
                    if display == "name"
                    else serializers.CharField(source=display, read_only=True)
                }
                cache_key = (
                    name,
                    field.related_model.__module__,
                    field.related_model.__name__,
                    display,
                    field.null,
                    any(candidate.name == "uid" for candidate in field.related_model._meta.concrete_fields),
                )
                relation_serializer = relation_serializer_cache.get(cache_key)
                if relation_serializer is None:
                    if any(candidate.name == "uid" for candidate in field.related_model._meta.concrete_fields):
                        from core.labs.features.base.serializers import UIDNamedReferenceSerializer

                        relation_meta = type("Meta", (), {"ref_name": f"{prefix}{name.title()}UIDReference"})
                        relation_serializer = type(
                            f"{prefix}{name.title().replace('_', '')}UIDReferenceSerializer",
                            (UIDNamedReferenceSerializer,),
                            {**attributes, "Meta": relation_meta},
                        )
                    else:
                        relation_meta = type("Meta", (), {"ref_name": f"{prefix}{name.title()}Reference"})
                        relation_serializer = type(
                            f"{prefix}{name.title().replace('_', '')}ReferenceSerializer",
                            (NamedReferenceSerializer,),
                            {**attributes, "Meta": relation_meta},
                        )
                    relation_serializer_cache[cache_key] = relation_serializer
                result[name] = relation_serializer(read_only=True, allow_null=field.null)
        return result

    list_label_fields = get_label_fields(list_fields)
    detail_label_fields = get_label_fields(detail_fields)
    list_read_fields = tuple(dict.fromkeys(EquipmentSerializer.Meta.fields + list_fields + tuple(list_label_fields)))
    detail_relation_fields = {
        name: relation_serializer(read_only=True, allow_null=True)
        for name, relation_serializer in definition.detail_relations
    }
    detail_read_fields = tuple(
        dict.fromkeys(
            EquipmentSerializer.Meta.fields
            + detail_fields
            + tuple(detail_label_fields)
            + tuple(detail_relation_fields)
            + ("details",)
        )
    )
    list_serializer = serializer_class(
        f"{prefix}EquipmentListSerializer",
        EquipmentSerializer,
        list_read_fields,
        readonly=True,
        attributes=list_label_fields,
    )
    detail_serializer = serializer_class(
        f"{prefix}EquipmentDetailSerializer",
        list_serializer,
        detail_read_fields,
        readonly=True,
        attributes={**detail_label_fields, **detail_relation_fields},
    )
    create_serializer = serializer_class(
        f"{prefix}EquipmentCreateSerializer",
        EquipmentWriteSerializer,
        EQUIPMENT_WRITE_FIELDS + create_fields,
    )
    update_serializer = serializer_class(
        f"{prefix}EquipmentUpdateSerializer",
        EquipmentWriteSerializer,
        EQUIPMENT_WRITE_FIELDS + update_fields,
    )

    lookup_fields = {}
    for key, model, label in definition.lookups:
        meta = type("Meta", (), {"model": model, "fields": ("id", label), "read_only_fields": ("id", label)})
        lookup = type(
            f"{prefix}{key.title().replace('_', '')}Serializer",
            (serializers.ModelSerializer,),
            {"__module__": module, "Meta": meta},
        )
        lookup_fields[key] = lookup(many=True, read_only=True)
    reference_serializer = type(
        f"{prefix}ReferenceDataSerializer",
        (EquipmentFormReferenceSerializer,),
        {"__module__": module, **lookup_fields},
    )
    common = {
        "__module__": module,
        "schema_tags": (f"{prefix} Equipment",),
        "model": registry_definition.model,
        "queryset_provider": staticmethod(
            partial(
                category_queryset,
                registry_definition.model,
                definition.fields,
                related=tuple(name for name, _ in definition.detail_relations),
            )
        ),
        "entity_name": f"{definition.key} equipment",
        "list_filters": category_filters,
    }
    list_view = type(
        f"ListCreate{prefix}EquipmentAPIView",
        (EquipmentListCreateAPIView,),
        {
            **common,
            "list_serializer_class": list_serializer,
            "create_response_serializer_class": detail_serializer,
            "create_serializer_class": create_serializer,
            "text_search_fields": list(definition.searchable_fields),
            "distinct_search": distinct_search,
        },
    )
    filters_view = type(
        f"{prefix}EquipmentFiltersAPIView",
        (FilterMetadataMixin, EquipmentAPIView),
        {
            "__module__": module,
            "filter_spec": list_view.filter_spec,
            "schema_tags": common["schema_tags"],
            "get_contract": OperationContract(
                query=PageNumberQuerySerializer,
                success=ResponseContract.success(f"{prefix}EquipmentFilters", FilterMetadataSerializer),
                bad_request=ResponseContract.bad_request(),
                tags=common["schema_tags"],
            ),
        },
    )
    extend_schema_view(get=filters_view.get_contract.schema())(filters_view)
    markcoroutinefunction(filters_view.get)
    facet_spec = facet_filter_spec(getattr(list_view, "filter_spec"))
    facets_contract = OperationContract(
        query=facet_query_serializer(f"{prefix}EquipmentFacetsQuerySerializer", facet_spec),
        success=ResponseContract.paginated(f"{prefix}EquipmentFacets", EquipmentFacetSerializer),
        bad_request=ResponseContract.bad_request(),
        tags=common["schema_tags"],
    )
    facets_view = cast(
        type[EquipmentFacetsAPIView],
        type(
            f"{prefix}EquipmentFacetsAPIView",
            (EquipmentFacetsAPIView,),
            {
                "__module__": module,
                "schema_tags": common["schema_tags"],
                "queryset_provider": common["queryset_provider"],
                "filter_spec": facet_spec,
                "get_contract": facets_contract,
            },
        ),
    )
    extend_schema_view(get=facets_contract.schema())(facets_view)
    markcoroutinefunction(facets_view.get)
    detail_view = type(
        f"RetrieveUpdate{prefix}EquipmentAPIView",
        (EquipmentRetrieveUpdateDeleteAPIView,),
        {
            **common,
            "response_serializer_class": detail_serializer,
            "update_serializer_class": update_serializer,
        },
    )

    def build_key_view(view_name: str, lookup_field: str, lookup_kwarg: str):
        return type(
            f"{view_name}{prefix}EquipmentAPIView",
            (EquipmentByKeyRetrieveUpdateAPIView,),
            {
                **common,
                "lookup_field": lookup_field,
                "lookup_kwarg": lookup_kwarg,
                "get_contract": OperationContract(
                    success=ResponseContract.success(f"{view_name}{prefix}EquipmentResponse", detail_serializer),
                    not_found=ResponseContract.not_found(),
                ),
                "patch_contract": OperationContract(
                    request=update_serializer,
                    success=ResponseContract.success(f"{view_name}{prefix}EquipmentResponse", detail_serializer),
                    bad_request=ResponseContract.bad_request(),
                    validation_error=ResponseContract.problem(422),
                    not_found=ResponseContract.not_found(),
                    conflict=ResponseContract.conflict(),
                ),
            },
        )

    sku_view = build_key_view("BySKU", "sku", "sku")
    uid_view = build_key_view("ByUID", "uid", "uid")
    reference_view = type(
        f"{prefix}ReferenceDataAPIView",
        (EquipmentCategoryReferenceAPIView,),
        {
            "__module__": module,
            "schema_tags": common["schema_tags"],
            "definition": definition,
            "get_contract": OperationContract(
                success=ResponseContract.success(
                    f"{prefix}ReferenceData",
                    reference_serializer,
                ),
                unauthorized=ResponseContract.unauthorized(),
            ),
        },
    )
    extend_schema_view(get=reference_view.get_contract.schema())(reference_view)
    markcoroutinefunction(reference_view.get)
    status_contract = OperationContract(
        request=EquipmentStatusSerializer,
        success=ResponseContract.success(
            f"{prefix}EquipmentDetailAfterStatusChange",
            detail_serializer,
        ),
        bad_request=ResponseContract.bad_request(),
        validation_error=ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY),
        not_found=ResponseContract.not_found(),
        conflict=ResponseContract.conflict(),
        tags=common["schema_tags"],
    )
    status_view = type(
        f"{prefix}EquipmentStatusAPIView",
        (EquipmentCategoryStatusAPIView,),
        {
            **common,
            "post_contract": status_contract,
        },
    )
    extend_schema_view(post=status_contract.schema())(status_view)
    markcoroutinefunction(status_view.post)
    options_contract = OperationContract(
        query=CategoryOptionsQuerySerializer,
        success=ResponseContract(
            status_code=200,
            schema=CatalogOptionListSerializer,
            payload_serializer=CatalogOptionSerializer,
            many=True,
        ),
        not_modified=ResponseContract.empty("NotModified", status_code=304),
        bad_request=ResponseContract.bad_request(),
        tags=common["schema_tags"],
    )
    options_view = type(
        f"{prefix}EquipmentOptionsAPIView",
        (EquipmentCategoryOptionsAPIView,),
        {
            **common,
            "category_fields": definition.fields,
            "get_contract": options_contract,
        },
    )
    extend_schema_view(get=options_contract.schema())(options_view)
    markcoroutinefunction(options_view.get)
    summary_contract = OperationContract(
        success=ResponseContract.success(
            f"{prefix}EquipmentStatusSummaryData",
            EquipmentStatusSummarySerializer,
        ),
        bad_request=ResponseContract.bad_request(),
        tags=common["schema_tags"],
    )
    summary_view = type(
        f"{prefix}EquipmentSummaryAPIView",
        (EquipmentCategorySummaryAPIView,),
        {
            **common,
            "category_key": definition.key,
            "category_model": registry_definition.model,
            "get_contract": summary_contract,
        },
    )
    extend_schema_view(get=summary_contract.schema())(summary_view)
    markcoroutinefunction(summary_view.get)
    import importlib

    target_mod = sys.modules.get(module) or importlib.import_module(module)
    for cls in (
        list_serializer,
        detail_serializer,
        create_serializer,
        update_serializer,
        reference_serializer,
        list_view,
        filters_view,
        facets_view,
        detail_view,
        sku_view,
        uid_view,
        reference_view,
        status_view,
        options_view,
        summary_view,
    ):
        setattr(target_mod, cls.__name__, cls)
    return [
        path(definition.key, list_view.as_view(), name=f"{definition.key}-list-create"),
        path(f"{definition.key}/reference-data", reference_view.as_view(), name=f"{definition.key}-reference-data"),
        path(f"{definition.key}/<int:pk>", detail_view.as_view(), name=f"{definition.key}-retrieve-update"),
        path(f"{definition.key}/filters", filters_view.as_view(), name=f"{definition.key}-filters"),
        path(f"{definition.key}/facets", facets_view.as_view(), name=f"{definition.key}-facets"),
        path(
            f"{definition.key}/<int:pk>/actions/change-status",
            status_view.as_view(),
            name=f"{definition.key}-action-change-status",
        ),
        path(f"{definition.key}/options", options_view.as_view(), name=f"{definition.key}-options"),
        path(f"{definition.key}/summary", summary_view.as_view(), name=f"{definition.key}-summary"),
        path(f"{definition.key}/sku/<str:sku>", sku_view.as_view(), name=f"{definition.key}-by-sku"),
        path(f"{definition.key}/uid/<uuid:uid>", uid_view.as_view(), name=f"{definition.key}-by-uid"),
    ]


__all__ = (
    "EquipmentCategoryOptionsAPIView",
    "EquipmentCategoryReferenceAPIView",
    "EquipmentCategoryStatusAPIView",
    "build_category_urlpatterns",
)
