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
from .search import SearchQueryMixin
from .summary_serializers import choice_field
from .wire_names import wire_name


def _renamed(field: Any, *, source: str, wire: str, read_only: bool = False, **overrides: Any) -> Any:
    """Rebuild ``field`` from its constructor arguments with the given source; DRF copies fields that way."""
    kwargs = {**field._kwargs, **overrides}
    if wire != source:
        kwargs["source"] = source
    if read_only:
        for key in ("required", "allow_blank", "validators", "default", "write_only"):
            kwargs.pop(key, None)
        kwargs["read_only"] = True
    return type(field)(*field._args, **kwargs)


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
    explicit_names = dict(getattr(resource, "wire_names", ()) or ())
    meta = type("Meta", (), {"model": resource.model, "fields": resource.fields, "validators": []})
    shape = type(f"{name}ImportShape", (serializers.ModelSerializer,), {"Meta": meta})()
    inputs: dict[str, Any] = {}
    outputs: dict[str, Any] = {"id": serializers.IntegerField(read_only=True)}
    query: dict[str, Any] = {"search_target": "search"}  # SearchQueryMixin: q, deprecated `search`
    for field_name in resource.fields:
        field = resource.model._meta.get_field(field_name)
        wire = wire_name(field, explicit_names)
        if field.many_to_one:
            # REL-16 id form: catalog records are joined by id; the same `<relation>_id` is read, written and
            # filtered (NAM-6), and the parent catalog supplies the name.
            inputs[field.attname] = serializers.IntegerField(
                min_value=1, required=not field.blank, allow_null=field.null
            )
            outputs[field.attname] = serializers.IntegerField(read_only=True, allow_null=field.null)
            query[field.attname] = serializers.IntegerField(required=False, min_value=1)
        elif field.many_to_many:
            # REL-9 / REL-16 id form: `<relation>_ids` read and written (replace semantics).
            if field_name.endswith("ies"):
                singular = f"{field_name[:-3]}y"
            else:
                singular = field_name[:-1] if field_name.endswith("s") else field_name
            inputs[f"{singular}_ids"] = serializers.ListField(
                child=serializers.IntegerField(min_value=1),
                max_length=100,
                required=not field.blank,
                source=field_name,
            )
            outputs[f"{singular}_ids"] = serializers.SerializerMethodField()

            def related_ids(self, obj, key=field_name) -> list[int]:
                return sorted(row.pk for row in getattr(obj, key).all())

            outputs[f"get_{singular}_ids"] = related_ids
        else:
            model_input = shape.fields[field_name]
            label_rules = {"required": True, "allow_blank": False} if field_name == resource.label else {}
            inputs[wire] = _renamed(model_input, source=field_name, wire=wire, **label_rules)
            if field.choices:
                # ENU-1: a choice column reads as `{value, label}` and is written as the plain value.
                outputs[wire] = choice_field(field.choices, source=None if wire == field_name else field_name)
            else:
                outputs[wire] = _renamed(model_input, source=field_name, wire=wire, read_only=True)
    if "active" in resource.fields:
        query["is_active"] = serializers.BooleanField(required=False, allow_null=True, default=None, source="active")
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
    query_serializer = type(f"{name}ReferenceQuery", (SearchQueryMixin, PageNumberQuerySerializer), query)

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
