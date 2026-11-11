
from django.test import RequestFactory
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import serializers
from rest_framework.exceptions import ParseError
from rest_framework.request import Request

from core.common.api.api_views import AppAPIView
from core.common.api.pagination import ResultsSetPagination
from core.labs.features.benches.api.serializers import BenchListQuerySerializer


def test_canonical_pagination_uses_data_array_and_mandatory_pagination() -> None:
    paginator = ResultsSetPagination()
    paginator.page = type(
        "Page",
        (),
        {
            "paginator": type("Paginator", (), {"count": 1})(),
            "number": 1,
        },
    )()
    paginator.request = Request(RequestFactory().get("/api/labs/benches/"))
    paginator.get_next_link = lambda: None
    paginator.get_previous_link = lambda: None

    response = paginator.get_paginated_response([{"uid": "item-1"}])

    assert response.status_code == 200
    assert response.data == {
        "data": [{"uid": "item-1"}],
        "meta": {"pagination": {"count": 1, "page": 1, "page_size": 25, "next": None, "previous": None}},
    }


def test_canonical_pagination_enforces_maximum_page_size() -> None:
    request = Request(RequestFactory().get("/api/labs/benches/?page_size=101"))

    try:
        ResultsSetPagination().get_page_size(request)
    except ParseError as error:
        assert "page_size" in error.detail
    else:
        raise AssertionError("oversized page_size must be rejected, not clamped")


def test_query_serializer_does_not_declare_unsupported_filter_keys() -> None:
    serializer = BenchListQuerySerializer()

    assert "unknown_filter" not in serializer.fields


def test_user_list_query_contract_accepts_username_filter() -> None:
    from core.users.features.profile.list_users.api import UsersListQuerySerializer

    serializer = UsersListQuerySerializer(data={"username": "alice"})

    assert serializer.is_valid()
    assert serializer.validated_data == {"username": "alice"}


def test_validate_query_allows_pagination_and_rejects_unknown_filter() -> None:
    class QuerySerializer(serializers.Serializer):
        search = serializers.CharField(required=False)

    class ExampleView(AppAPIView):
        get_contract = OperationContract(
            query=QuerySerializer,
            success=ResponseContract.success("Example", QuerySerializer),
            bad_request=ResponseContract.bad_request(),
        )

    request = RequestFactory().get("/api/example?page=2&page_size=10&search=bench")
    view = ExampleView()
    view.setup(request)
    view.request = Request(request)

    filters, error = view.validate_query()

    assert error is None
    assert filters == {"search": "bench"}

    request = RequestFactory().get("/api/example?unexpected=value")
    view = ExampleView()
    view.setup(request)
    view.request = Request(request)

    filters, error = view.validate_query()

    assert filters is None
    assert error.status_code == 400
    assert error.data["error"]["code"] == "invalid_query"


def test_validate_query_rejects_repeated_and_oversized_pagination_values() -> None:
    class QuerySerializer(serializers.Serializer):
        search = serializers.CharField(required=False)

    class ExampleView(AppAPIView):
        get_contract = OperationContract(
            query=QuerySerializer,
            success=ResponseContract.paginated("Examples", QuerySerializer),
        )

    for query in ("page_size=10&page_size=20", "page_size=101", "page=0"):
        request = RequestFactory().get(f"/api/example/?{query}")
        view = ExampleView()
        view.setup(request)
        view.request = Request(request)

        filters, error = view.validate_query()

        assert filters is None
        assert error.status_code == 400


def test_operation_contract_adds_bad_request_response_for_declared_query() -> None:
    class QuerySerializer(serializers.Serializer):
        search = serializers.CharField(required=False)

    class ExampleView(AppAPIView):
        get_contract = OperationContract(
            query=QuerySerializer,
            success=ResponseContract.success("Example", QuerySerializer),
        )

    request = RequestFactory().get("/api/example?unexpected=value")
    view = ExampleView()
    view.setup(request)
    view.request = Request(request)

    filters, error = view.validate_query()

    assert error is not None
    assert error.status_code == 400
    assert error.data["error"]["code"] == "invalid_query"


def test_declared_server_problem_includes_request_correlation_id() -> None:
    class ExampleView(AppAPIView):
        get_contract = OperationContract(
            success=ResponseContract.success("Example", serializers.Serializer),
            service_unavailable=ResponseContract.problem(503),
        )

    request_id = "0123456789abcdef0123456789abcdef"
    request = RequestFactory().get("/api/example", HTTP_X_REQUEST_ID=request_id)
    view = ExampleView()
    view.setup(request)
    view.request = Request(request)

    response = view.respond_problem("service_unavailable", detail="Temporarily unavailable.")

    assert response.status_code == 503
    assert response.data["error"]["request_id"] == request_id


def test_create_response_has_location_for_created_resource() -> None:
    class PayloadSerializer(serializers.Serializer):
        id = serializers.IntegerField()

    class ExampleView(AppAPIView):
        post_contract = OperationContract(
            success=ResponseContract.created("Example", PayloadSerializer),
        )

    request = RequestFactory().post("/api/examples", data="{}", content_type="application/json")
    view = ExampleView()
    view.setup(request)
    view.request = Request(request)

    response = view.respond_data({"id": 42})

    assert response.status_code == 201
    assert response["Location"].endswith("/api/examples/42")


def test_nested_contract_errors_use_bracket_indexes():
    from drf_api_contracts.responses import _error_details
    from rest_framework.exceptions import ErrorDetail

    assert _error_details({"items": [{"quantity": [ErrorDetail("Invalid.", code="invalid")]}]}) == [
        {"field": "items[0].quantity", "code": "invalid", "message": "Invalid."}
    ]


def test_error_details_preserve_preformatted_field_detail():
    from drf_api_contracts.responses import _error_details

    assert _error_details(
        [
            {
                "field": "setup_location_id",
                "code": "does_not_exist",
                "message": "Select an existing setup location.",
            }
        ]
    ) == [
        {
            "field": "setup_location_id",
            "code": "does_not_exist",
            "message": "Select an existing setup location.",
        }
    ]


def test_public_error_codes_are_normalized_to_snake_case():
    from drf_api_contracts.settings import default_code_value

    assert default_code_value("INVALID_REFRESH_TOKEN") == "invalid_refresh_token"
    assert default_code_value("InvalidStateTransition") == "invalid_state_transition"


def test_equipment_create_contract_is_created_and_uses_detail_shape():
    from core.labs.features.equipment.api.collection import EquipmentCollectionAPIView, EquipmentDetailSerializer

    view = EquipmentCollectionAPIView
    assert view.post_contract.responses.success.status_code == 201
    assert view.post_contract.responses.success.payload_serializer is EquipmentDetailSerializer


def test_strict_request_validation_rejects_unknown_fields_and_coercible_types() -> None:
    class InputSerializer(serializers.Serializer):
        count = serializers.IntegerField()
        enabled = serializers.BooleanField()

    class ExampleView(AppAPIView):
        post_contract = OperationContract(
            request=InputSerializer,
            success=ResponseContract.success("Example", InputSerializer),
        )

    request = RequestFactory().post("/api/example", data="{}", content_type="application/json")
    view = ExampleView()
    view.setup(request)
    view.request = Request(request)

    serializer, error = view.validate_request(data={"count": "7", "enabled": 1, "extra": True})

    assert serializer is None
    assert error.status_code == 422
    details = {item["field"]: item["code"] for item in error.data["error"]["details"]}
    assert details == {"count": "invalid_type", "enabled": "invalid_type", "extra": "unknown_field"}


def test_missing_required_request_field_is_semantic_422() -> None:
    class InputSerializer(serializers.Serializer):
        name = serializers.CharField()

    class ExampleView(AppAPIView):
        post_contract = OperationContract(
            request=InputSerializer,
            success=ResponseContract.success("Example", InputSerializer),
        )

    request = RequestFactory().post("/api/example", data="{}", content_type="application/json")
    view = ExampleView()
    view.setup(request)
    view.request = Request(request)

    serializer, error = view.validate_request(data={})

    assert serializer is None
    assert error.status_code == 422
    assert error.data["error"]["details"][0]["code"] == "required"


def test_invalid_request_id_is_replaced_with_canonical_uuid_hex() -> None:
    from core.common.api.correlation import get_request_id

    request = RequestFactory().get("/api/example", HTTP_X_REQUEST_ID="not-a-canonical-id")

    request_id = get_request_id(request)

    assert len(request_id) == 32
    assert all(character in "0123456789abcdef" for character in request_id)


def test_collection_contract_declares_mandatory_paginated_envelope() -> None:
    class ExamplePayloadSerializer(serializers.Serializer):
        uid = serializers.CharField()

    contract = ResponseContract.paginated("ExampleCollection", ExamplePayloadSerializer)

    assert contract.many is True
    assert contract.is_paginated is True
