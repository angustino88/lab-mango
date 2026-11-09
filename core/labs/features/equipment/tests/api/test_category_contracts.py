"""Contract regressions that do not require the production database or root URLconf."""

from dataclasses import replace
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.urls import resolve
from rest_framework import serializers

from core.common.api.options import CatalogOptionSerializer
from core.labs.features.base.list_create import ListCreateAPIView
from core.labs.features.base.retrieve_update_delete import RetrieveUpdateDeleteAPIView
from core.labs.features.equipment.api.category_definitions import (
    CATEGORY_DEFINITIONS,
    COMMON_EQUIPMENT_SEARCH_FIELDS,
    EquipmentCategoryAPIConfig,
)
from core.labs.features.equipment.api.category_serializers import EquipmentWriteSerializer
from core.labs.features.equipment.api.registry import EQUIPMENT_REGISTRY
from core.labs.features.equipment.api.retrieve_update_delete import EquipmentRetrieveUpdateDeleteAPIView
from core.labs.features.equipment.api.serializers import (
    EquipmentSerializer,
    EquipmentStatusSerializer,
)
from core.labs.features.equipment.api.views import (
    EquipmentCategoryOptionsAPIView,
    EquipmentCategoryStatusAPIView,
    EquipmentOptionsAPIView,
    EquipmentStatusAPIView,
)

URLCONF = "core.labs.features.equipment.api.urls"


@pytest.mark.parametrize("key", CATEGORY_DEFINITIONS)
def test_category_routes_and_response_contracts(key):
    definition = CATEGORY_DEFINITIONS[key]
    for suffix, methods in (
        ("", {"GET", "POST"}),
        ("/42", {"GET", "PUT", "PATCH", "DELETE"}),
        ("/reference-data", {"GET"}),
        ("/42/actions/change-status", {"POST"}),
        ("/options", {"GET"}),
    ):
        match = resolve(f"/equipment/{key}{suffix}", urlconf=URLCONF)
        view = match.func.view_class
        assert methods <= set(view()._allowed_methods())
        assert len(view.permission_classes) > 0
        if suffix == "/options":
            view.validate_configuration()
            assert issubclass(view, EquipmentCategoryOptionsAPIView)
            assert view.model is definition.model
            assert view.get_contract.responses.success.payload_serializer is CatalogOptionSerializer
        elif suffix == "/42/actions/change-status":
            view.validate_configuration()
            assert issubclass(view, EquipmentCategoryStatusAPIView)
            assert issubclass(view, EquipmentStatusAPIView)
            assert view.model is definition.model
            assert view.post_contract.request is EquipmentStatusSerializer
            response = view.post_contract.responses.success.payload_serializer
            fields = response().get_fields()
            expected_read_fields = definition.fields_for("detail")
            assert set(expected_read_fields) <= fields.keys()
            assert "acquisition_price" in fields
            assert "status" in fields
        elif suffix != "/reference-data":
            view.validate_configuration()
            assert view.model is definition.model
            queryset = view.queryset_provider()
            sql, params = queryset.query.sql_with_params()
            assert "equipment" in params  # Pricing links to the canonical Equipment, not its subtype.
            assert {"acquisition_price", "acquisition_currency", "current_status"} <= queryset.query.annotations.keys()
            response = view.list_serializer_class if not suffix else view.response_serializer_class
            fields = response().get_fields()
            expected_read_fields = definition.fields_for("detail" if suffix else "list")
            assert set(expected_read_fields) <= fields.keys()
            assert "acquisition_price" in fields
            assert "status" in fields
            assert len(response.Meta.fields) == len(set(response.Meta.fields))
        else:
            fields = view.get_contract.responses.success.payload_serializer().get_fields()
            assert {name for name, _, _ in definition.lookups} <= fields.keys()
    assert EQUIPMENT_REGISTRY[key].model is definition.model


@pytest.mark.parametrize("key", CATEGORY_DEFINITIONS)
def test_category_writes_are_explicit_and_do_not_duplicate_pricing(key):
    view = resolve(f"/equipment/{key}", urlconf=URLCONF).func.view_class
    detail_view = resolve(f"/equipment/{key}/42", urlconf=URLCONF).func.view_class
    serializer = view.create_serializer_class()
    fields = serializer.get_fields()
    definition = CATEGORY_DEFINITIONS[key]
    model = definition.model

    def to_write_key(field_name: str) -> str:
        model_field = model._meta.get_field(field_name)
        if model_field.is_relation:
            return f"{field_name}_ids" if model_field.many_to_many else f"{field_name}_id"
        return field_name

    expected_create = {to_write_key(f) for f in definition.fields_for("create")}
    expected_update = {to_write_key(f) for f in definition.fields_for("update")}
    assert expected_create <= fields.keys()
    assert expected_update <= detail_view.update_serializer_class().get_fields().keys()
    assert not {"equipment_ptr", "currency", "purchase_price", "acquisition_price", "current_status"} & fields.keys()
    assert isinstance(serializer, EquipmentWriteSerializer)
    assert "group_id" in fields
    assert "department_id" in fields

    relation_field = serializer.fields["group_id"]
    assert relation_field.source == "group"


def test_generic_create_serializer_maps_group_and_department_to_application_fields():
    from core.labs.features.equipment.api.serializers import EquipmentCreateSerializer

    serializer = EquipmentCreateSerializer(
        data={"kind_id": 1, "sku": "EQ-GROUP-INPUT", "group_id": 7, "department_id": 6}
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["group"] == 7
    assert serializer.validated_data["department"] == 6


def test_equipment_list_query_preloads_department_group_for_named_relations():
    from core.labs.features.equipment.queries.equipment import list_equipment

    queryset = list_equipment()

    assert {"department", "group"} <= set(queryset.query.select_related)


@pytest.mark.django_db
def test_category_queryset_preloads_department_group_for_multiple_rows(equipment, django_assert_num_queries):
    from core.labs.models.resource.base.resource import Department, ResourceGroup

    list_view = resolve("/equipment/computing", urlconf=URLCONF).func.view_class
    department = Department.objects.create(name="Category query department")
    group = ResourceGroup.objects.create(name="Category query group", department=department)
    equipment.department = department
    equipment.group = group
    equipment.save(update_fields=["department", "group"])
    another = type(equipment).objects.create(
        kind=equipment.kind,
        sku="EQ-CATEGORY-QUERY-02",
        name="Second grouped equipment",
        department=department,
        group=group,
    )
    queryset = list_view.queryset_provider()

    # Relation access from the category queryset must not issue per-row queries.
    with django_assert_num_queries(1):
        rows = list(queryset.filter(pk__in=(equipment.pk, another.pk)))
        [(row.department.name, row.group.name) for row in rows]


def test_equipment_serializer_groups_acquisition_as_nullable_money_object():
    equipment = SimpleNamespace(
        acquisition_price=Decimal("1299.00"),
        acquisition_currency="EUR",
    )

    assert EquipmentSerializer().get_acquisition_price(equipment) == {
        "amount": "1299.00",
        "currency": "EUR",
    }
    assert (
        EquipmentSerializer().get_acquisition_price(SimpleNamespace(acquisition_price=None, acquisition_currency=None))
        is None
    )


@pytest.mark.parametrize("key", CATEGORY_DEFINITIONS)
def test_equipment_sku_is_writable_on_create_but_read_only_on_update(key):
    list_view = resolve(f"/equipment/{key}", urlconf=URLCONF).func.view_class
    detail_view = resolve(f"/equipment/{key}/42", urlconf=URLCONF).func.view_class

    create_sku = list_view.create_serializer_class().fields["sku"]
    update_serializer = detail_view.update_serializer_class(instance=object(), data={"sku": "NEW"})

    assert not create_sku.read_only
    with pytest.raises(serializers.ValidationError) as exc_info:
        update_serializer.to_internal_value({"sku": "NEW"})
    assert exc_info.value.detail["code"][0] == "resource_field_immutable"


def test_generic_base_does_not_assume_resources_or_user_stamps():
    request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))
    generic = RetrieveUpdateDeleteAPIView()
    obj = SimpleNamespace(pk=12, title="booking title")  # No resource fields, _meta, or user stamps.
    serializer = Mock(validated_data={"title": "new title"})
    assert generic.get_save_kwargs(request) == {}
    assert ListCreateAPIView().get_save_kwargs(request) == {}
    assert generic.get_old_values(obj, serializer) == {}
    assert generic.get_response_instance(obj) is obj
    generic.get_object_queryset = Mock(return_value=Mock())
    generic.get_write_queryset().select_for_update.assert_not_called()
    generic.perform_update(obj, serializer, request)
    serializer.save.assert_called_once_with()


def test_equipment_opts_into_domain_hooks():
    assert EquipmentRetrieveUpdateDeleteAPIView.lock_on_write
    view = EquipmentRetrieveUpdateDeleteAPIView()
    request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))
    assert view.get_save_kwargs(request) == {"last_modified_by": request.user}
    assert view.get_old_values.__func__.__qualname__.startswith("ResourceChangeLogMixin.")


@pytest.mark.parametrize("key", CATEGORY_DEFINITIONS)
def test_partial_update_validates_existing_kind_category(key):
    view = resolve(f"/equipment/{key}/42", urlconf=URLCONF).func.view_class
    wrong_kind = SimpleNamespace(pk=1, category_id=0, active=True, category=SimpleNamespace(name="Wrong", active=True))
    obj = SimpleNamespace(kind=wrong_kind, type=None, manufacturer=None, product_model=None, owner=None)
    serializer = view.update_serializer_class(instance=obj, data={}, partial=True)
    with pytest.raises(serializers.ValidationError) as error:
        serializer.validate({})
    assert "kind" in error.value.detail


def test_m2m_read_queries_are_prefetched():
    for key in ("display", "instrument", "sample"):
        view = resolve(f"/equipment/{key}", urlconf=URLCONF).func.view_class
        queryset = view.queryset_provider()
        for name in CATEGORY_DEFINITIONS[key].fields:
            if view.model._meta.get_field(name).many_to_many:
                assert name in queryset._prefetch_related_lookups


def test_generated_classes_are_available_for_introspection():
    module = import_module("core.labs.features.equipment.api.urls")
    assert module.DisplayEquipmentDetailSerializer
    assert module.RetrieveUpdateDisplayEquipmentAPIView


def test_equipment_schema_covers_all_category_operations():
    from drf_spectacular.generators import SchemaGenerator

    from core.labs.features.equipment.api.urls import urlpatterns

    schema = SchemaGenerator(patterns=urlpatterns).get_schema(request=None, public=True)
    for key in CATEGORY_DEFINITIONS:
        assert {"get", "post"} <= schema["paths"][f"/equipment/{key}"].keys()
        detail_path = next(p for p in schema["paths"] if p.startswith(f"/equipment/{key}/{{"))
        assert {"get", "put", "patch", "delete"} <= schema["paths"][detail_path].keys()
        assert "get" in schema["paths"][f"/equipment/{key}/reference-data"]
    assert not any(path.endswith("/computing/" + "os-names") for path in schema["paths"])


def test_equipment_reference_serializers_are_reused_between_list_and_detail_views():
    list_view = resolve("/equipment/display", urlconf=URLCONF).func.view_class
    detail_view = resolve("/equipment/display/42", urlconf=URLCONF).func.view_class

    list_serializer = list_view.list_serializer_class()
    detail_serializer = detail_view.response_serializer_class()

    assert list_serializer.fields["size"].__class__ is detail_serializer.fields["size"].__class__
    assert list_serializer.fields["size"].__class__.__name__ == "DisplaySizeReferenceSerializer"


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/42", "/reference-data", "/options"])
async def test_generated_handlers_preserve_async_dispatch(monkeypatch, suffix):
    from django.contrib.auth.models import AnonymousUser
    from rest_framework.response import Response
    from rest_framework.test import APIRequestFactory

    view = resolve(f"/equipment/display{suffix}", urlconf=URLCONF).func.view_class
    monkeypatch.setattr(view, "authentication_classes", [])
    monkeypatch.setattr(view, "permission_classes", [])
    monkeypatch.setattr(view, "throttle_classes", [])
    monkeypatch.setattr(view, "handle_get", lambda self, request, **kwargs: Response({"data": {"ok": True}}))
    request = APIRequestFactory().get(f"/equipment/display{suffix}")
    request.user = AnonymousUser()
    response = await view.as_view()(request, **({"pk": 42} if suffix == "/42" else {}))
    assert response.status_code == 200
    assert response.data["data"]["ok"]


@pytest.mark.asyncio
async def test_generated_status_handler_preserves_async_dispatch(monkeypatch):
    from django.contrib.auth.models import AnonymousUser
    from rest_framework.response import Response
    from rest_framework.test import APIRequestFactory

    view = resolve("/equipment/display/42/actions/change-status", urlconf=URLCONF).func.view_class
    monkeypatch.setattr(view, "authentication_classes", [])
    monkeypatch.setattr(view, "permission_classes", [])
    monkeypatch.setattr(view, "throttle_classes", [])
    monkeypatch.setattr(view, "handle_post", lambda self, request, **kwargs: Response({"data": {"ok": True}}))
    request = APIRequestFactory().post("/equipment/display/42/actions/change-status", data={}, format="json")
    request.user = AnonymousUser()
    response = await view.as_view()(request, pk=42)
    assert response.status_code == 200
    assert response.data["data"]["ok"]


def test_change_log_snapshots_mutable_data_independently():
    from core.labs.features.base.resource_change_log import ResourceChangeLogMixin
    from core.labs.models.resource.equipment import DisplayEquipment

    instance = DisplayEquipment(metadata={"nested": [1]})
    snapshot = ResourceChangeLogMixin().get_old_values(instance, SimpleNamespace(validated_data={"metadata": {}}))
    instance.metadata["nested"].append(2)
    assert snapshot == {"metadata": {"nested": [1]}}


@pytest.mark.parametrize("key", CATEGORY_DEFINITIONS)
def test_category_operations_use_shared_defaults_without_redundant_overrides(key):
    definition = CATEGORY_DEFINITIONS[key]
    assert definition.key == key
    assert EQUIPMENT_REGISTRY[key].model is definition.model
    assert definition.searchable_fields[: len(COMMON_EQUIPMENT_SEARCH_FIELDS)] == COMMON_EQUIPMENT_SEARCH_FIELDS
    for operation in ("list", "create", "update", "detail"):
        override = getattr(definition, f"{operation}_fields")
        assert override is None or override != definition.fields
        assert definition.fields_for(operation) == (definition.fields if override is None else override)


def test_category_field_defaults_preserve_explicit_empty_overrides():
    definition = EquipmentCategoryAPIConfig(
        model=CATEGORY_DEFINITIONS["display"].model,
        fields=("size",),
        list_fields=(),
    )
    assert definition.fields_for("list") == ()
    for operation in ("create", "update", "detail"):
        assert definition.fields_for(operation) == ("size",)
    with pytest.raises(ValueError, match="Unsupported category operation"):
        definition.fields_for("delete")


def test_computing_shared_defaults_preserve_existing_api_contract():
    definition = CATEGORY_DEFINITIONS["computing"]
    assert definition.update_fields == ("monitored_devices", "technical_user")
    assert definition.detail_fields is None
    assert definition.fields_for("list") == ("ip_address", "os_name", "mac_address")
    assert definition.fields_for("create") == ("mac_address",)

    list_view = resolve("/equipment/computing", urlconf=URLCONF).func.view_class
    detail_view = resolve("/equipment/computing/42", urlconf=URLCONF).func.view_class
    list_fields = list_view.list_serializer_class().get_fields()
    create_fields = list_view.create_serializer_class().get_fields()
    update_fields = detail_view.update_serializer_class().get_fields()
    detail_fields = detail_view.response_serializer_class().get_fields()
    detailed_fields = {"disk_usage", "system_info", "monitored_devices", "rdp_file", "technical_user"}
    agent_owned_fields = {"ip_address", "os_name", "disk_usage", "system_info"}
    server_managed_fields = {"rdp_file"}
    detailed_write_fields = {"monitored_devices", "technical_user_id"}
    assert not detailed_fields & list_fields.keys()
    assert agent_owned_fields.isdisjoint(create_fields)
    assert server_managed_fields.isdisjoint(create_fields)
    assert agent_owned_fields.isdisjoint(update_fields)
    assert server_managed_fields.isdisjoint(update_fields)
    assert "mac_address" in create_fields and "mac_address" not in update_fields
    assert "hostname" not in list_fields
    assert detailed_write_fields <= update_fields.keys()
    assert detailed_fields <= detail_fields.keys()
    assert detail_fields["technical_user"].fields["name"].source == "username"
    assert tuple(list_view.text_search_fields) == definition.searchable_fields


def test_computing_agent_snapshot_fields_are_read_only_in_response_schema():
    detail_view = resolve("/equipment/computing/42", urlconf=URLCONF).func.view_class
    response_fields = detail_view.response_serializer_class().get_fields()

    for field_name in ("ip_address", "os_name", "disk_usage", "system_info", "hostname"):
        assert response_fields[field_name].read_only


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("create", {"ip_address": "192.0.2.4"}),
        ("create", {"os_name": "Linux"}),
        ("create", {"hostname": "lab-pc"}),
        ("create", {"system_info": {"hostname": "lab-pc"}}),
        ("update", {"ip_address": "192.0.2.4"}),
        ("update", {"os_name": "Linux"}),
        ("update", {"disk_usage": [{"mount": "/", "used_bytes": 1}]}),
        ("update", {"system_info": {"hostname": "lab-pc"}}),
        ("update", {"hostname": "lab-pc"}),
        ("update", {"rdp_file": "generated.rdp"}),
    ],
)
def test_computing_category_serializer_rejects_agent_owned_and_server_managed_fields(operation, payload):
    list_view = resolve("/equipment/computing", urlconf=URLCONF).func.view_class
    detail_view = resolve("/equipment/computing/42", urlconf=URLCONF).func.view_class
    if operation == "create":
        serializer = list_view.create_serializer_class(data={"kind_id": 1, "sku": "EQ-COMP-NEW", **payload})
    else:
        serializer = detail_view.update_serializer_class(instance=object(), data=payload, partial=True)

    assert not serializer.is_valid()
    assert set(serializer.errors) == set(payload)
    assert all("Unknown or read-only field." in str(error) for error in serializer.errors.values())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("os_name", "Linux"),
        ("hostname", "lab-pc"),
        ("system_info", {"hostname": "lab-pc"}),
    ],
)
def test_computing_category_create_request_rejects_agent_owned_and_server_managed_fields(admin_client, field, value):
    payload = {"kind_id": 1, "sku": "EQ-COMP-NEW", field: value}
    response = admin_client.post("/api/labs/equipment/computing", payload, format="json")

    assert response.status_code == 422
    assert response.data["error"]["code"] == "validation_failed"
    assert response.data["error"]["details"]
    assert any(
        detail["field"] == field and detail["code"] in {"unknown_field", "read_only_field"}
        for detail in response.data["error"]["details"]
    )


@pytest.mark.parametrize("key", CATEGORY_DEFINITIONS)
def test_category_search_fields_are_explicit_valid_model_paths(key):
    definition = CATEGORY_DEFINITIONS[key]
    view = resolve(f"/equipment/{key}", urlconf=URLCONF).func.view_class
    assert tuple(view.text_search_fields) == definition.searchable_fields
    for field_path in definition.searchable_fields:
        model = definition.model
        parts = field_path.split("__")
        for index, field_name in enumerate(parts):
            field = model._meta.get_field(field_name)
            if index < len(parts) - 1:
                assert field.is_relation and field.related_model is not None
                model = field.related_model


@pytest.mark.parametrize("key", CATEGORY_DEFINITIONS)
def test_category_url_reverse_names_follow_consistent_generated_convention(key):
    from django.urls import reverse

    assert reverse(f"{key}-list-create", urlconf=URLCONF) == f"/equipment/{key}"
    assert reverse(f"{key}-reference-data", urlconf=URLCONF) == f"/equipment/{key}/reference-data"
    assert reverse(f"{key}-retrieve-update", kwargs={"pk": 42}, urlconf=URLCONF) == f"/equipment/{key}/42"
    assert (
        reverse(f"{key}-action-change-status", kwargs={"pk": 42}, urlconf=URLCONF)
        == f"/equipment/{key}/42/actions/change-status"
    )
    assert reverse(f"{key}-options", urlconf=URLCONF) == f"/equipment/{key}/options"
    assert reverse("equipment-options", urlconf=URLCONF) == "/equipment/options"
    assert resolve("/equipment/options", urlconf=URLCONF).func.view_class is EquipmentOptionsAPIView


def test_route_names_option_is_retained_but_not_applied_yet():
    from core.labs.features.equipment.api.categories import build_category_urlpatterns

    definition = replace(
        CATEGORY_DEFINITIONS["computing"],
        route_names=("legacy-list", "legacy-reference", "legacy-detail"),
    )
    patterns = build_category_urlpatterns(definition, module="core.labs.features.equipment.api.urls")
    assert [pattern.name for pattern in patterns[:3]] == [
        "computing-list-create",
        "computing-reference-data",
        "computing-retrieve-update",
    ]
