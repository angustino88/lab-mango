import pytest
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from rest_framework.views import APIView
from rest_framework import serializers, status

from drf_api_contracts import (
    ContractSettings,
    OperationContract,
    ResponseContract,
    ResponseSchemaFactory,
)


class WidgetSerializer(serializers.Serializer):
    id = serializers.IntegerField()


def test_success_contract_validates_and_preserves_materialized_payload():
    contract = ResponseContract.success("Widget", WidgetSerializer)

    assert contract.respond_data({"id": 7}).data == {"data": {"id": 7}}
    with pytest.raises(serializers.ValidationError):
        contract.respond_data({})


def test_named_response_factories_use_the_expected_http_statuses():
    assert ResponseContract.ok("Widget", WidgetSerializer).status_code == status.HTTP_200_OK
    assert ResponseContract.created("Widget", WidgetSerializer).status_code == status.HTTP_201_CREATED
    assert ResponseContract.accepted("Widget", WidgetSerializer).status_code == status.HTTP_202_ACCEPTED
    assert ResponseContract.no_content().status_code == status.HTTP_204_NO_CONTENT
    assert ResponseContract.bad_request().status_code == status.HTTP_400_BAD_REQUEST
    assert ResponseContract.not_found().status_code == status.HTTP_404_NOT_FOUND


def test_polymorphic_contract_wraps_multiple_success_shapes():
    contract = ResponseContract.polymorphic(
        "WidgetAnalytics",
        [WidgetSerializer, WidgetSerializer(many=True)],
    )

    assert contract.status_code == status.HTTP_200_OK
    assert contract.schema.component_name == "WidgetAnalytics"
    assert len(contract.schema.serializers) == 2


def test_paginated_contract_owns_runtime_and_schema_shape():
    contract = ResponseContract.paginated("Widget", WidgetSerializer)

    response = contract.respond_page(
        1,
        [{"id": 7}],
        page=1,
        page_size=25,
        next="/widgets/?page=2",
    )

    assert response.data == {
        "data": [{"id": 7}],
        "meta": {
            "pagination": {
                "count": 1,
                "page": 1,
                "page_size": 25,
                "next": "/widgets/?page=2",
                "previous": None,
            }
        },
    }
    assert contract.schema is ResponseSchemaFactory.paginated("Widget", WidgetSerializer)


def test_application_settings_customize_wire_conventions():
    settings = ContractSettings(success_key="result", pagination_meta_key="metadata")
    contract = ResponseContract.paginated("WidgetCustom", WidgetSerializer, settings=settings)

    response = contract.respond_page(1, [{"id": 7}], page=1, page_size=10)

    assert response.data["result"] == [{"id": 7}]
    assert response.data["metadata"]["pagination"]["page_size"] == 10


def test_paginated_contract_rejects_ambiguous_materialized_data():
    contract = ResponseContract.paginated("Widget", WidgetSerializer)

    with pytest.raises(TypeError, match="respond_page\(\) with explicit page metadata"):
        contract.respond_data({"total_count": 1, "results": [{"id": 7}]})


def test_paginated_contract_supports_empty_page_with_positive_page_size():
    contract = ResponseContract.paginated("Widget", WidgetSerializer)

    response = contract.respond_page(0, [], page=1)

    assert response.data["data"] == []
    assert response.data["meta"]["pagination"]["page_size"] == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"total_count": -1}, "total_count must be non-negative"),
        ({"page": 0}, "page must be at least 1"),
        ({"page_size": 0}, "page_size must be positive"),
    ],
)
def test_paginated_contract_validates_metadata(kwargs, message):
    contract = ResponseContract.paginated("Widget", WidgetSerializer)

    with pytest.raises(ValueError, match=message):
        total_count = kwargs.pop("total_count", 1)
        contract.respond_page(total_count, [{"id": 7}], **kwargs)


def test_operation_contract_combines_documentation_and_runtime_behavior():
    operation = OperationContract(
        success=ResponseContract.success("WidgetOperation", WidgetSerializer),
        not_found=ResponseContract.problem(status.HTTP_404_NOT_FOUND),
        tags=["widgets", "operations"],
    )

    assert set(operation.responses.document_configured()) == {200, 404}
    assert operation.respond({"id": 7}).data == {"data": {"id": 7}}
    assert operation.respond_problem("not_found").status_code == 404

    class WidgetView(APIView):
        @operation.schema()
        def get(self, request):
            return operation.respond({"id": 7})

    schema = SchemaGenerator(patterns=[path("widgets", WidgetView.as_view())]).get_schema(
        request=None,
        public=True,
    )

    assert schema["paths"]["/widgets/"]["get"]["tags"] == ["widgets", "operations"]


def test_explicit_schema_tags_override_contract_defaults():
    operation = OperationContract(
        success=ResponseContract.success("WidgetOverride", WidgetSerializer),
        tags=["default"],
    )

    class WidgetView(APIView):
        @operation.schema(tags=["explicit"])
        def get(self, request):
            return operation.respond({"id": 7})

    schema = SchemaGenerator(patterns=[path("widgets", WidgetView.as_view())]).get_schema(
        request=None,
        public=True,
    )

    assert schema["paths"]["/widgets/"]["get"]["tags"] == ["explicit"]


def test_operation_contract_accepts_named_success_responses_directly():
    operation = OperationContract(
        success=ResponseContract.success("Widget", WidgetSerializer),
        created=ResponseContract.created("WidgetCreated", WidgetSerializer),
        not_found=ResponseContract.problem(status.HTTP_404_NOT_FOUND),
    )

    assert set(operation.responses.document_configured()) == {200, 201, 404}
    assert operation.responses.created.respond_data({"id": 7}).status_code == status.HTTP_201_CREATED


def test_operation_contract_rejects_invalid_or_duplicate_named_responses():
    with pytest.raises(ValueError, match="duplicate response status code"):
        OperationContract(
            success=ResponseContract.ok("Widget", WidgetSerializer),
            same_status=ResponseContract.ok("WidgetAgain", WidgetSerializer),
        ).responses.document_configured()
