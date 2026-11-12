"""Contract-aware transport factory using owner-provided callbacks only.

No business app imports or automatic model discovery. Input fields derive from
an explicit owner allowlist; model validation remains in the create command.
"""

import dataclasses
from collections.abc import Sequence
from typing import Any, Callable

from django.urls import path
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .api_views import AppAPIView, AppListAPIView
from .pagination import PageNumberQuerySerializer


def reference_urlpatterns(
    *,
    resource: Any,
    prefix: str,
    tag: str,
    module: str,
    create: Callable,
    listing: Callable,
    retrieve: Callable,
    permission_classes: Sequence[Any] | None = None,
    can_write: Callable[[Any], bool] | None = None,
    read_only: bool = False,
) -> list:
    """Bind one explicitly declared resource to owner commands and queries.

    ``permission_classes`` lets the owning app set its access policy; the default is authenticated users.
    ``can_write`` is the owner's write rule ``(actor) -> bool``; the default is the model's ``add_`` permission.
    ``read_only`` publishes list and detail only: the collection has no POST (405), and ``create`` is unused.
    """
    access = list(permission_classes) if permission_classes is not None else [IsAuthenticated]
    if can_write is not None:
        # The owner's write rule travels with the resource into the import command's policy check.
        resource = dataclasses.replace(resource, can_write=can_write)
    name = resource.model.__name__
    meta = type("Meta", (), {"model": resource.model, "fields": resource.fields, "validators": []})
    shape = type(f"{name}ImportShape", (serializers.ModelSerializer,), {"Meta": meta})()
    inputs: dict[str, Any] = {}
    outputs: dict[str, Any] = {"id": serializers.IntegerField(read_only=True)}
    query: dict[str, Any] = {"search": serializers.CharField(required=False, max_length=255)}
    for field_name in resource.fields:
        field = resource.model._meta.get_field(field_name)
        if field.many_to_one:
            inputs[field.attname] = serializers.IntegerField(
                min_value=1, required=not field.blank, allow_null=field.null
            )
            outputs[field.attname] = serializers.IntegerField(read_only=True, allow_null=field.null)
            query[field.attname] = serializers.IntegerField(required=False, min_value=1)
        elif field.many_to_many:
            inputs[field_name] = serializers.ListField(
                child=serializers.IntegerField(min_value=1), max_length=100, required=not field.blank
            )
            outputs[field_name] = serializers.SerializerMethodField()
        else:
            input_field = shape.fields[field_name]
            input_field.validators = [v for v in input_field.validators if v.__class__.__name__ != "UniqueValidator"]
            input_field.read_only = False
            if field_name == resource.label:
                input_field.required = True
                input_field.allow_blank = False
            inputs[field_name] = input_field
            outputs[field_name] = shape.fields[field_name].__deepcopy__({})
            outputs[field_name].read_only = True
    for field_name in resource.fields:
        if resource.model._meta.get_field(field_name).many_to_many:

            def related_ids(self, obj, key=field_name) -> list[int]:
                return sorted(row.pk for row in getattr(obj, key).all())

            outputs[f"get_{field_name}"] = related_ids
    if "active" in resource.fields:
        query["active"] = serializers.BooleanField(required=False, allow_null=True, default=None)
    input_serializer: Any = type(f"{name}CatalogCreate", (serializers.Serializer,), inputs)

    # Fields are deep-copied by DRF from their original constructor arguments.
    # Strip uniqueness after that copy: replay must reach the atomic command.
    def input_fields(self):
        fields = serializers.Serializer.get_fields(self)
        for field in fields.values():
            field.validators = [v for v in field.validators if v.__class__.__name__ != "UniqueValidator"]
        return fields

    input_serializer.get_fields = input_fields
    output_serializer = type(f"{name}CatalogRecord", (serializers.Serializer,), outputs)
    query_serializer = type(f"{name}ReferenceQuery", (PageNumberQuerySerializer,), query)

    class Collection(AppListAPIView):
        permission_classes = access
        schema_tags = (tag,)
        get_contract = OperationContract(
            query=query_serializer,
            success=ResponseContract.paginated(f"{name}ReferenceList", output_serializer),
            bad_request=ResponseContract.bad_request(),
        )

        def handle_get(self, request, **kwargs):
            filters, error = self.validate_query()
            if error is not None:
                return error
            return self.list_response_sync(listing(resource, actor=request.user, filters=dict(filters or {})))

        if not read_only:
            post_contract = OperationContract(
                request=input_serializer,
                success=ResponseContract.created(f"{name}ReferenceCreate", output_serializer),
                bad_request=ResponseContract.bad_request(),
                conflict=ResponseContract.problem(409),
                validation_error=ResponseContract.problem(422),
            )

            def handle_post(self, request, **kwargs):
                serializer, error = self.validate_request()
                if error is not None:
                    return error
                if serializer is None:
                    raise TypeError("Request validation returned no serializer.")
                result = create(
                    resource,
                    values=dict(serializer.validated_data),
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    actor=request.user,
                )
                response = Response({"data": result.data}, status=201)
                response["Location"] = request.build_absolute_uri(f"{request.path}/{result.data['id']}")
                if result.replayed:
                    response["Idempotency-Replayed"] = "true"
                return response

    class Detail(AppAPIView):
        permission_classes = access
        schema_tags = (tag,)
        get_contract = OperationContract(
            success=ResponseContract.success(f"{name}ReferenceDetail", output_serializer),
            not_found=ResponseContract.not_found(),
        )

        def handle_get(self, request, reference_id: int, **kwargs):
            return self.respond(retrieve(resource, actor=request.user, reference_id=reference_id))

    Collection.__module__ = Detail.__module__ = module
    Collection.__name__ = f"{name}ReferenceCollectionAPIView"
    Detail.__name__ = f"{name}ReferenceDetailAPIView"
    collection_schemas: dict[str, Any] = {
        "get": extend_schema(
            description=(
                f"List {name} reference records in a paginated data envelope. "
                "Validates the declared search, relation and pagination query parameters "
                "and delegates filtering and access checks to the owner-provided listing callback."
            ),
        ),
    }
    if not read_only:
        collection_schemas["post"] = extend_schema(
            description=(
                f"Create a {name} reference record from the declared writable fields. "
                "Passes the validated values, authenticated user and Idempotency-Key to the "
                "owner-provided create callback. Returns a 201 data envelope with Location; "
                "a replay reported by the callback also includes Idempotency-Replayed: true."
            ),
            parameters=[
                OpenApiParameter(
                    "Idempotency-Key",
                    str,
                    OpenApiParameter.HEADER,
                    required=True,
                    description="Required replay key (max 128 characters); receipts retained until explicitly purged.",
                )
            ],
        )
    extend_schema_view(**collection_schemas)(Collection)
    extend_schema_view(
        get=extend_schema(
            description=(
                f"Retrieve one {name} reference record by reference_id in a data envelope. "
                "Delegates lookup and access checks to the owner-provided retrieve callback; "
                "a missing or unavailable record is documented as 404."
            ),
        ),
    )(Detail)
    return [
        path(prefix, Collection.as_view(), name=f"{resource.key}-list-create"),
        path(f"{prefix}/<int:reference_id>", Detail.as_view(), name=f"{resource.key}-detail"),
    ]
