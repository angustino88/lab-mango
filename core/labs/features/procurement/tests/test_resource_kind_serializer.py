from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType

from core.labs.features.procurement.api.serializers import (
    PurchaseItemResourceCreateSerializer,
    PurchaseItemResourceSerializer,
)
from core.labs.features.procurement.application.commands import CreatePurchaseItemResourceInput
from core.labs.features.procurement.queries.selectors import list_purchase_item_resources
from core.labs.models import Bench, Equipment, License, Purchase, PurchaseItem, PurchaseItemResource, Station
from core.users.models import URSGroup

pytestmark = pytest.mark.django_db
_role_sequence = 0


def _authorize_coordinator(api_client, user):
    global _role_sequence
    _role_sequence += 1
    group = Group.objects.create(name=f"procurement-test-coord-{_role_sequence}")
    URSGroup.objects.create(group=group, urs_group_id=2000 + _role_sequence, labs_role="coord")
    user.groups.add(group)
    api_client.force_authenticate(user=user)


@pytest.mark.parametrize(
    ("kind", "model"),
    (("bench", Bench), ("equipment", Equipment), ("license", License), ("station", Station)),
)
def test_resource_kind_validates_to_canonical_content_type(kind, model):
    serializer = PurchaseItemResourceCreateSerializer(
        data={
            "resource_kind": kind,
            "resource_id": 1,
            "acquisition_price": "1.00",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["resource_type_id"] == ContentType.objects.get_for_model(model).pk


def test_stable_kind_post_creates_allocation_through_endpoint(api_client, user):
    purchase = Purchase.objects.create(
        supplier="Supplier",
        purchase_date="2026-01-01",
        total_amount="1.00",
        creator=user,
    )
    item = PurchaseItem.objects.create(
        purchase=purchase,
        description="Bench",
        quantity=1,
        unit_price="1.00",
        creator=user,
    )
    bench = Bench.objects.create(name="Bench", sku="BENCH", creator=user)
    _authorize_coordinator(api_client, user)
    with patch(
        "core.labs.features.procurement.api.views.public.create_purchase_item_resource",
        return_value=PurchaseItemResource(
            purchase_item=item,
            resource_type=ContentType.objects.get_for_model(Bench),
            resource_id=bench.pk,
            acquisition_price=Decimal("1.00"),
            creator=user,
        ),
    ) as create_allocation:
        response = api_client.post(
            f"/api/labs/purchase-items/{item.pk}/resources",
            {"resource_kind": "bench", "resource_id": bench.pk, "acquisition_price": "1.00"},
            format="json",
        )

    assert response.status_code == 201, response.content
    assert response.data["data"]["resource_kind"] == "bench"
    command = create_allocation.call_args.args[0]
    assert isinstance(command, CreatePurchaseItemResourceInput)
    assert command.resource_type_id == ContentType.objects.get_for_model(Bench).pk
    assert command.resource_id == bench.pk


def test_legacy_kind_post_creates_allocation_through_endpoint(api_client, user):
    purchase = Purchase.objects.create(
        supplier="Supplier",
        purchase_date="2026-01-01",
        total_amount="1.00",
        creator=user,
    )
    item = PurchaseItem.objects.create(
        purchase=purchase,
        description="Bench",
        quantity=1,
        unit_price="1.00",
        creator=user,
    )
    bench = Bench.objects.create(name="Bench", sku="BENCH", creator=user)
    content_type = ContentType.objects.get_for_model(Bench)
    _authorize_coordinator(api_client, user)
    with patch(
        "core.labs.features.procurement.api.views.public.create_purchase_item_resource",
        return_value=PurchaseItemResource(
            purchase_item=item,
            resource_type=content_type,
            resource_id=bench.pk,
            acquisition_price=Decimal("1.00"),
            creator=user,
        ),
    ) as create_allocation:
        response = api_client.post(
            f"/api/labs/purchase-items/{item.pk}/resources",
            {"resource_type_id": content_type.pk, "resource_id": bench.pk, "acquisition_price": "1.00"},
            format="json",
        )

    assert response.status_code == 201, response.content
    assert response.data["data"]["resource_kind"] == "bench"
    assert create_allocation.call_args.args[0].resource_type_id == content_type.pk


@pytest.mark.parametrize(
    "payload",
    (
        {"resource_id": 1, "acquisition_price": "1.00"},
        {"resource_kind": "bench", "resource_type_id": 1, "resource_id": 1, "acquisition_price": "1.00"},
    ),
)
def test_invalid_kind_input_returns_422_without_creating_allocation(api_client, user, payload):
    with patch(
        "core.labs.features.procurement.api.views.public.create_purchase_item_resource",
    ) as create_allocation:
        _authorize_coordinator(api_client, user)

        response = api_client.post(
            "/api/labs/purchase-items/1/resources",
            payload,
            format="json",
        )

        assert response.status_code == 422
        create_allocation.assert_not_called()


def test_legacy_resource_type_id_is_still_accepted():
    content_type = ContentType.objects.get_for_model(Bench)
    serializer = PurchaseItemResourceCreateSerializer(
        data={
            "resource_type_id": content_type.pk,
            "resource_id": 1,
            "acquisition_price": "1.00",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["resource_type_id"] == content_type.pk


def test_matching_stable_and_legacy_inputs_are_accepted():
    content_type = ContentType.objects.get_for_model(Bench)
    serializer = PurchaseItemResourceCreateSerializer(
        data={
            "resource_kind": "bench",
            "resource_type_id": content_type.pk,
            "resource_id": 1,
            "acquisition_price": "1.00",
        }
    )

    assert serializer.is_valid(), serializer.errors


def test_mismatched_stable_and_legacy_inputs_are_rejected():
    serializer = PurchaseItemResourceCreateSerializer(
        data={
            "resource_kind": "bench",
            "resource_type_id": ContentType.objects.get_for_model(Equipment).pk,
            "resource_id": 1,
            "acquisition_price": "1.00",
        }
    )

    assert not serializer.is_valid()
    assert "resource_type_id" in serializer.errors


def test_one_of_stable_or_legacy_input_is_required():
    serializer = PurchaseItemResourceCreateSerializer(
        data={
            "resource_id": 1,
            "acquisition_price": "1.00",
        }
    )

    assert not serializer.is_valid()
    assert "resource_kind" in serializer.errors


def test_unsupported_legacy_content_type_is_rejected():
    unsupported_type = ContentType.objects.get_for_model(Station.room.field.related_model)
    serializer = PurchaseItemResourceCreateSerializer(
        data={
            "resource_type_id": unsupported_type.pk,
            "resource_id": 1,
            "acquisition_price": "1.00",
        }
    )

    assert not serializer.is_valid()
    assert "resource_type_id" in serializer.errors


def test_resource_kind_with_missing_content_type_is_validation_error(monkeypatch):
    manager = ContentType.objects
    queryset = manager.none()

    def no_kind_content_type(*args, **kwargs):
        return queryset

    monkeypatch.setattr(manager, "filter", no_kind_content_type)
    serializer = PurchaseItemResourceCreateSerializer(
        data={
            "resource_kind": "bench",
            "resource_id": 1,
            "acquisition_price": "1.00",
        }
    )

    assert not serializer.is_valid()
    assert "resource_kind" in serializer.errors


def test_resource_kind_is_read_only_output_with_stable_enum(user):
    purchase = Purchase.objects.create(
        supplier="Supplier",
        purchase_date="2026-01-01",
        total_amount="1.00",
        creator=user,
    )
    item = PurchaseItem.objects.create(
        purchase=purchase,
        description="Equipment",
        quantity=1,
        unit_price="1.00",
        creator=user,
    )
    bench = Bench.objects.create(name="Bench", sku="BENCH", creator=user)
    allocation = PurchaseItemResource.objects.create(
        purchase_item=item,
        resource_type=ContentType.objects.get_for_model(Bench),
        resource_id=bench.pk,
        acquisition_price=Decimal("1.00"),
        creator=user,
    )
    output_serializer = PurchaseItemResourceSerializer(instance=allocation)
    output_fields = output_serializer.fields
    write_fields = PurchaseItemResourceCreateSerializer().fields

    assert output_fields["resource_kind"].read_only
    assert output_serializer.data["resource_kind"] == "bench"
    assert write_fields["resource_kind"].write_only
    assert set(write_fields["resource_kind"].choices) == {"bench", "equipment", "license", "station"}
    assert write_fields["resource_type_id"].write_only


def test_openapi_create_schema_requires_either_resource_kind_identifier():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    component = schema["components"]["schemas"]["PurchaseItemResourceCreate"]

    assert component["anyOf"] == [
        {"required": ["resource_kind"]},
        {"required": ["resource_type_id"]},
    ]
    assert {"resource_id", "acquisition_price"}.issubset(component["required"])


def test_resource_allocation_list_query_budget(django_assert_num_queries, user):
    purchase = Purchase.objects.create(
        supplier="Supplier",
        purchase_date="2026-01-01",
        total_amount="3.00",
        creator=user,
    )
    item = PurchaseItem.objects.create(
        purchase=purchase,
        description="Equipment",
        quantity=3,
        unit_price="1.00",
        creator=user,
    )
    content_type = ContentType.objects.get_for_model(Bench)
    benches = [Bench.objects.create(name=f"Bench {index}", sku=f"BENCH-{index}", creator=user) for index in range(3)]
    for resource in benches:
        PurchaseItemResource.objects.create(
            purchase_item=item,
            resource_type=content_type,
            resource_id=resource.pk,
            acquisition_price="1.00",
            creator=user,
        )

    with django_assert_num_queries(3):
        allocations = list(list_purchase_item_resources(purchase_item_id=item.pk))
        assert [
            PurchaseItemResourceSerializer(instance=allocation).data["resource_kind"] for allocation in allocations
        ] == ["bench", "bench", "bench"]
