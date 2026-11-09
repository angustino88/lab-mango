import pytest
from django.urls import path
from drf_api_contracts import OperationContract, ProblemDetailSerializer, ResponseContract
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.views import APIView


def generate_schema(responses):
    # Keep these pure schema tests isolated from project settings and secret files.
    from drf_spectacular.generators import SchemaGenerator
    from drf_spectacular.openapi import AutoSchema

    class ErrorView(APIView):
        authentication_classes = []
        permission_classes = []
        schema = AutoSchema()

        @extend_schema(responses=responses)
        def get(self, request):
            raise NotImplementedError

    return SchemaGenerator(patterns=[path("errors", ErrorView.as_view())]).get_schema(public=True)


def response_component(schema, status_code):
    response = schema["paths"]["/errors"]["get"]["responses"][str(status_code)]
    assert set(response["content"]) == {"application/json"}
    reference = response["content"]["application/json"]["schema"]["$ref"]
    return schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]


def assert_error_envelope(schema, status_code):
    envelope = response_component(schema, status_code)
    assert set(envelope["properties"]) == {"error"}
    assert envelope["required"] == ["error"]
    reference = envelope["properties"]["error"]["$ref"]
    body = schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]
    assert set(body["properties"]) == {"code", "message", "details", "request_id"}
    assert set(body["required"]) == {"code", "message", "details", "request_id"}
    assert body["properties"]["details"]["type"] == "array"
    return body


@pytest.mark.parametrize(
    "contract",
    [
        ResponseContract.bad_request(),
        ResponseContract.unauthorized(),
        ResponseContract.forbidden(),
        ResponseContract.not_found(),
        ResponseContract.conflict(),
        ResponseContract.problem(422),
        ResponseContract.problem(500),
        ResponseContract.problem(503),
    ],
    ids=["400", "401", "403", "404", "409", "422", "500", "503"],
)
def test_default_problem_schemas_document_runtime_envelope(contract):
    schema = generate_schema(contract.document())
    assert_error_envelope(schema, contract.status_code)

    response = contract.respond_problem(code="invalid_request", detail="Invalid request.")
    assert response.status_code == contract.status_code
    assert response.data == {
        "error": {
            "code": "invalid_request",
            "message": "Invalid request.",
            "details": [],
            "request_id": "unknown",
        }
    }
    assert contract.schema(instance=response.data).data == response.data


@pytest.mark.parametrize(
    ("errors", "expected_details"),
    [
        (None, []),
        (
            {"name": [ErrorDetail("Required.", code="required")]},
            [{"field": "name", "code": "required", "message": "Required."}],
        ),
        (
            ErrorDetail("Invalid.", code="invalid"),
            [{"field": None, "code": "invalid", "message": "Invalid."}],
        ),
    ],
)
def test_problem_schema_preserves_empty_field_and_non_field_details(errors, expected_details):
    contract = ResponseContract.problem(422)
    response = contract.respond_problem(
        code="validation_failed", detail="Invalid request.", errors=errors, request_id="dummy-request-id"
    )
    assert response.data["error"]["details"] == expected_details
    assert response.data["error"]["request_id"] == "dummy-request-id"
    serializer = contract.schema(data=response.data)
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == response.data


def test_flat_problem_serializer_and_explicit_schema_overrides_are_preserved():
    from drf_api_contracts.responses import ProblemDetailSerializer as ResponseProblemDetailSerializer

    assert ResponseProblemDetailSerializer is ProblemDetailSerializer
    assert set(ProblemDetailSerializer().fields) == {"code", "message", "details", "request_id"}
    body = {"code": "api_error", "message": "Invalid.", "details": [], "request_id": "unknown"}
    serializer = ProblemDetailSerializer(data=body)
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == body

    for custom_schema in (ProblemDetailSerializer, ProblemDetailSerializer()):
        contract = ResponseContract.problem(400, schema=custom_schema)
        assert contract.schema is custom_schema
        assert contract.document() == {400: custom_schema}
        schema = generate_schema(contract.document())
        assert set(response_component(schema, 400)["properties"]) == set(body)
        assert contract.respond_problem(detail="Invalid.").data == {"error": body}


def test_implicit_operation_errors_use_runtime_envelope_without_changing_success():
    class PayloadSerializer(serializers.Serializer):
        name = serializers.CharField()

    operation = OperationContract(
        success=ResponseContract.ok("ErrorSchemaPayload", PayloadSerializer), request=PayloadSerializer
    )
    schema = generate_schema(operation.responses.document_configured())
    assert set(schema["paths"]["/errors"]["get"]["responses"]) == {"200", "400", "422"}
    assert_error_envelope(schema, 400)
    assert_error_envelope(schema, 422)
    assert set(response_component(schema, 200)["properties"]) == {"data"}
    assert operation.respond_data({"name": "dummy"}).data == {"data": {"name": "dummy"}}


def test_routing_response_requires_details_without_changing_runtime_default():
    from core.routing.api.serializers import ErrorBodySerializer, ErrorEnvelopeSerializer

    schema = generate_schema({400: ErrorEnvelopeSerializer})
    body_schema = assert_error_envelope(schema, 400)
    item_reference = body_schema["properties"]["details"]["items"]["$ref"]
    item = schema["components"]["schemas"][item_reference.rsplit("/", 1)[-1]]
    assert set(item["properties"]) == {"field", "message"}
    assert item["required"] == ["message"]

    field = ErrorBodySerializer().fields["details"]
    assert field.default is list
    assert field.required is False
    assert field.read_only is False
    body = {"code": "invalid_request", "message": "Invalid.", "request_id": "dummy-request-id"}
    assert ErrorBodySerializer(instance=body).data == {**body, "details": []}
    serializer = ErrorBodySerializer(data=body)
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {**body, "details": []}

    body["details"] = [{"field": "limit", "message": "Invalid limit."}]
    serializer = ErrorBodySerializer(data=body)
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == body


@pytest.mark.parametrize("split_request", [False, True])
def test_routing_details_requirement_is_response_only(split_request):
    from drf_spectacular.generators import SchemaGenerator
    from drf_spectacular.openapi import AutoSchema
    from drf_spectacular.settings import patched_settings

    from core.routing.api.serializers import ErrorEnvelopeSerializer

    class RoutingErrorView(APIView):
        authentication_classes = []
        permission_classes = []
        schema = AutoSchema()

        @extend_schema(
            request=ErrorEnvelopeSerializer if split_request else None, responses={400: ErrorEnvelopeSerializer}
        )
        def post(self, request):
            raise NotImplementedError

    with patched_settings(
        {
            "POSTPROCESSING_HOOKS": [],
            "COMPONENT_SPLIT_REQUEST": split_request,
            "COMPONENT_NO_READ_ONLY_REQUIRED": True,
        }
    ):
        schema = SchemaGenerator(patterns=[path("routing-errors", RoutingErrorView.as_view())]).get_schema(public=True)

    operation = schema["paths"]["/routing-errors"]["post"]
    components = schema["components"]["schemas"]

    def error_body(content):
        envelope_ref = content["application/json"]["schema"]["$ref"]
        envelope = components[envelope_ref.rsplit("/", 1)[-1]]
        body_ref = envelope["properties"]["error"]["$ref"]
        return components[body_ref.rsplit("/", 1)[-1]]

    response_body = error_body(operation["responses"]["400"]["content"])
    assert "details" in response_body["required"]
    if split_request:
        request_body = error_body(operation["requestBody"]["content"])
        assert "details" not in request_body["required"]
