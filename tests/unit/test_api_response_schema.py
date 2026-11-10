"""Contract tests for shared API response schema generation."""

from types import SimpleNamespace

import pytest
from drf_api_contracts import (
    OperationContract,
    PaginatedResponseEnvelopeSerializer,
    ProblemDetailSerializer,
    ResponseContract,
    ResponseEnvelopeSerializer,
    ResponseSchemaFactory,
    ResponseSet,
    api_schema,
)
from drf_api_contracts.serializers import ProblemResponseEnvelopeSerializer
from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers, status

from core.common.api.api_views import AppAPIView


class ExamplePayloadSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    label = serializers.SerializerMethodField()

    def get_label(self, obj):
        return f"example-{obj['id']}"


class ExampleEnvelopeSerializer(ResponseEnvelopeSerializer):
    data = ExamplePayloadSerializer()


def test_success_schema_supports_detail_and_list_payloads():
    detail = ResponseSchemaFactory.success("Example", ExamplePayloadSerializer)
    listing = ResponseSchemaFactory.success("Example", ExamplePayloadSerializer, many=True)

    assert detail is ResponseSchemaFactory.success("Example", ExamplePayloadSerializer)
    assert issubclass(detail, ResponseEnvelopeSerializer)
    assert isinstance(detail().fields["data"], ExamplePayloadSerializer)
    assert isinstance(listing().fields["data"], serializers.ListSerializer)
    assert isinstance(listing().fields["data"].child, ExamplePayloadSerializer)


def test_paginated_schema_matches_paging_response_contract():
    response = ResponseSchemaFactory.paginated("Example", ExamplePayloadSerializer)()

    assert isinstance(response, PaginatedResponseEnvelopeSerializer)
    assert set(response.fields) == {"data", "meta"}
    assert isinstance(response.fields["data"], serializers.ListSerializer)
    assert isinstance(response.fields["data"].child, ExamplePayloadSerializer)
    assert set(response.fields["meta"].fields) == {"pagination"}
    assert set(response.fields["meta"].fields["pagination"].fields) == {
        "count",
        "page",
        "page_size",
        "next",
        "previous",
    }


def test_paginated_contract_reuses_payload_serializer_for_runtime_list_items():
    contract = ResponseContract.paginated("Example", ExamplePayloadSerializer)

    assert contract.schema is ResponseSchemaFactory.paginated("Example", ExamplePayloadSerializer)
    assert contract.payload_serializer is ExamplePayloadSerializer
    assert contract.many is True


def test_problem_detail_schema_matches_standard_error_contract():
    serializer = ProblemDetailSerializer()

    assert set(serializer.fields) == {
        "code",
        "message",
        "details",
        "request_id",
    }
    assert serializer.fields["code"].required
    assert serializer.fields["details"].required
    assert serializer.fields["request_id"].required


def test_empty_and_variant_schemas_cover_non_payload_and_variant_responses():
    empty = ResponseSchemaFactory.empty("Example")()
    detail = ResponseSchemaFactory.success("Example", ExamplePayloadSerializer)
    variants = ResponseSchemaFactory.variants("ExampleVariant", [detail, empty.__class__])

    assert isinstance(empty.fields["data"], serializers.DictField)
    assert empty.fields["data"].read_only
    assert isinstance(variants, PolymorphicProxySerializer)


def test_list_variants_compose_normal_and_paginated_response_schemas():
    variants = ResponseSchemaFactory.list_variants("ExampleList", ExamplePayloadSerializer)

    assert variants.component_name == "ExampleListResponseVariant"
    assert variants.serializers == [
        ResponseSchemaFactory.success("ExampleList", ExamplePayloadSerializer, many=True),
        ResponseSchemaFactory.paginated("ExampleList", ExamplePayloadSerializer),
    ]


def test_polymorphic_remains_a_compatibility_alias_for_variants():
    detail = ResponseSchemaFactory.success("Example", ExamplePayloadSerializer)

    variants = ResponseSchemaFactory.polymorphic("ExampleVariant", [detail])

    assert isinstance(variants, PolymorphicProxySerializer)
    assert variants.serializers == [detail]


def test_empty_contract_serializes_through_an_empty_payload_serializer():
    contract = ResponseContract.empty("EmptyExample")

    response = contract.serialize({})

    assert response.data == {"data": {}}


@pytest.mark.parametrize("name", ["", "   ", None])
def test_schema_names_must_be_non_empty(name):
    with pytest.raises(ValueError, match="name must be a non-empty string"):
        ResponseSchemaFactory.success(name, ExamplePayloadSerializer)


def test_payload_must_be_a_serializer_class():
    with pytest.raises(TypeError, match="payload_serializer must be a DRF serializer class"):
        ResponseSchemaFactory.success("Example", object)


def test_success_contract_rejects_an_envelope_as_its_payload_at_construction():
    with pytest.raises(TypeError, match="inner payload"):
        ResponseContract.success("Example", ExampleEnvelopeSerializer)


def test_variant_schema_requires_at_least_one_variant():
    with pytest.raises(ValueError, match="at least one serializer"):
        ResponseSchemaFactory.variants("ExampleVariant", [])


def test_api_schema_preserves_request_parameters_and_response_metadata():
    decorator = api_schema(
        request=ExamplePayloadSerializer,
        parameters=[ExamplePayloadSerializer],
        responses={201: ExamplePayloadSerializer},
    )

    @decorator
    def operation():
        return None

    schema = operation.kwargs["schema"]
    assert schema.__name__ == "ExtendedSchema"
    assert callable(schema.get_request_serializer)
    assert callable(schema.get_override_parameters)
    assert callable(schema.get_response_serializers)


def test_response_contract_owns_status_schema_and_runtime_response():
    contract = ResponseContract.success(
        "CreatedExample",
        ExamplePayloadSerializer,
        status_code=201,
    )

    response = contract.serialize({"id": 7})

    assert contract.document() == {201: contract.schema}
    assert response.status_code == 201
    assert response.data == {"data": {"id": 7, "label": "example-7"}}


def test_success_contract_defaults_to_200_and_supports_201():
    default_contract = ResponseContract.success(
        "DefaultExample",
        ExamplePayloadSerializer,
    )
    created_contract = ResponseContract.success(
        "CreatedExample",
        ExamplePayloadSerializer,
        status_code=status.HTTP_201_CREATED,
    )

    assert default_contract.status_code == status.HTTP_200_OK
    assert created_contract.status_code == status.HTTP_201_CREATED
    assert created_contract.serialize({"id": 7}).status_code == status.HTTP_201_CREATED


def test_response_contract_validates_materialized_data_without_rewriting_it():
    contract = ResponseContract.success("Example", ExamplePayloadSerializer)

    response = contract.respond_data({"id": 7})

    assert response.data == {"data": {"id": 7}}

    with pytest.raises(serializers.ValidationError):
        contract.respond_data({"label": "missing-id"})


def test_response_contract_allows_documented_only_data_without_serializer():
    contract = ResponseContract.documented(status.HTTP_200_OK, ExamplePayloadSerializer)

    response = contract.respond_data({"result": "documented externally"})

    assert response.data == {"data": {"result": "documented externally"}}


def test_response_contract_accepts_a_composed_success_schema():
    schema = ResponseSchemaFactory.list_variants("ExampleList", ExamplePayloadSerializer)

    contract = ResponseContract.from_schema(schema, status_code=status.HTTP_206_PARTIAL_CONTENT)

    assert contract.document() == {status.HTTP_206_PARTIAL_CONTENT: schema}


def test_app_api_view_responds_using_its_declared_contract():
    contract = ResponseContract.success("ViewExample", ExamplePayloadSerializer)

    class ExampleView(AppAPIView):
        responses = ResponseSet(success=contract)

    view = ExampleView()
    view.request = object()

    response = view.respond({"id": 7})

    assert response.status_code == contract.status_code
    assert response.data == {"data": {"id": 7, "label": "example-7"}}


def test_app_api_view_responds_with_a_named_problem_contract():
    contracts = ResponseSet(
        success=ResponseContract.success("ViewExample", ExamplePayloadSerializer),
        bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
    )

    class ExampleView(AppAPIView):
        responses = contracts

    view = ExampleView()
    view.request = SimpleNamespace(request_id="a" * 32)
    response = view.respond_problem(
        "bad_request",
        code="validation_failed",
        errors={"id": ["This field is required."]},
    )

    assert contracts.document("bad_request") == {
        200: contracts.success.schema,
        400: ProblemResponseEnvelopeSerializer,
    }
    assert response.status_code == 400
    assert response.data["error"] == {
        "code": "validation_failed",
        "message": "One or more fields are invalid.",
        "details": [{"field": "id[0]", "code": "invalid", "message": "This field is required."}],
        "request_id": "a" * 32,
    }


def test_operation_contract_uses_one_request_serializer_for_schema_and_validation():
    responses = ResponseSet(
        success=ResponseContract.success("ViewExample", ExamplePayloadSerializer),
        bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
    )
    operation = OperationContract(
        request=ExamplePayloadSerializer,
        responses=responses,
    )

    @operation.schema()
    def endpoint():
        return None

    serializer = operation.serializer(data={"id": 7})
    schema = endpoint.kwargs["schema"]

    assert serializer.is_valid()
    assert serializer.validated_data == {"id": 7}
    assert callable(schema.get_request_serializer)
    assert callable(schema.get_response_serializers)

    response = operation.respond({"id": 7})
    problem = operation.respond_problem("bad_request", errors={"id": ["Invalid."]})

    assert response.data == {"data": {"id": 7, "label": "example-7"}}
    assert problem.status_code == status.HTTP_400_BAD_REQUEST


def test_operation_contract_accepts_a_schema_and_named_problems_directly():
    schema = ResponseSchemaFactory.list_variants("ExampleList", ExamplePayloadSerializer)

    operation = OperationContract(
        success=schema,
        bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
    )

    assert operation.responses.document_configured() == {
        status.HTTP_200_OK: schema,
        status.HTTP_400_BAD_REQUEST: ProblemResponseEnvelopeSerializer,
    }


def test_operation_without_request_body_cannot_create_a_serializer():
    operation = OperationContract(
        responses=ResponseSet(
            success=ResponseContract.success("ViewExample", ExamplePayloadSerializer)
        )
    )

    with pytest.raises(TypeError, match="request serializer class"):
        operation.serializer(data={"id": 7})


def test_app_api_view_registers_method_contract_schema_by_convention():
    operation = OperationContract(
        responses=ResponseSet(
            success=ResponseContract.success("ConventionExample", ExamplePayloadSerializer)
        )
    )

    class ExampleView(AppAPIView):
        get_contract = operation

        def get(self, request):
            return self.respond({"id": 7})

    schema = ExampleView.get.kwargs["schema"]

    assert schema.__name__ == "ExtendedSchema"


def test_app_api_view_uses_current_method_operation_for_runtime_response():
    operation = OperationContract(
        responses=ResponseSet(
            success=ResponseContract.success("ConventionRuntime", ExamplePayloadSerializer)
        )
    )

    class ExampleView(AppAPIView):
        get_contract = operation

    view = ExampleView()
    view.request = type("Request", (), {"method": "GET"})()

    response = view.respond({"id": 7})

    assert response.data == {"data": {"id": 7, "label": "example-7"}}


def test_success_contract_owns_list_cardinality():
    contract = ResponseContract.success("ViewExamples", ExamplePayloadSerializer, many=True)

    response = contract.serialize([{"id": 7}, {"id": 8}])

    assert response.data == {
        "data": [
            {"id": 7, "label": "example-7"},
            {"id": 8, "label": "example-8"},
        ]
    }


def test_problem_contract_cannot_serialize_a_success_payload():
    contract = ResponseContract.problem(status.HTTP_400_BAD_REQUEST)

    with pytest.raises(TypeError, match="success contract"):
        contract.serialize({"id": 7})


def test_problem_contract_owns_status_schema_and_runtime_response():
    bad_request = ResponseContract.problem(status.HTTP_400_BAD_REQUEST)

    response = bad_request.respond_problem(
        code="validation_failed",
        errors={"id": ["This field is required."]},
    )

    assert bad_request.document() == {400: ProblemResponseEnvelopeSerializer}
    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_failed"
    assert response.data["error"]["request_id"] == "unknown"
    assert response.data["error"]["details"] == [
        {"field": "id[0]", "code": "invalid", "message": "This field is required."}
    ]


def test_response_contracts_compose_without_repeating_status_codes():
    success = ResponseContract.success("ExampleContract", ExamplePayloadSerializer)
    bad_request = ResponseContract.problem(status.HTTP_400_BAD_REQUEST)

    assert ResponseContract.document_many(success, bad_request) == {
        200: success.schema,
        400: ProblemResponseEnvelopeSerializer,
    }

    with pytest.raises(ValueError, match="duplicate response status code"):
        ResponseContract.document_many(success, success)


def test_response_set_supports_arbitrary_named_problem_statuses():
    responses = ResponseSet(
        success=ResponseContract.success("ExtensibleExample", ExamplePayloadSerializer),
        conflict=ResponseContract.problem(status.HTTP_409_CONFLICT),
        upstream_error=ResponseContract.problem(status.HTTP_502_BAD_GATEWAY),
    )

    assert set(responses.document_configured()) == {200, 409, 502}
    assert responses.get("conflict").status_code == status.HTTP_409_CONFLICT


def test_operation_contract_reuses_query_serializer_for_schema_and_validation():
    operation = OperationContract(
        query=ExamplePayloadSerializer,
        responses=ResponseSet(
            success=ResponseContract.success("QueryExample", ExamplePayloadSerializer),
            bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
        ),
    )

    @operation.schema()
    def endpoint():
        return None

    serializer = operation.query_serializer(data={"id": 7})

    assert serializer.is_valid()
    assert serializer.validated_data == {"id": 7}
    assert callable(endpoint.kwargs["schema"].get_override_parameters)

