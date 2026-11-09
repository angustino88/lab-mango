# API operation contracts

Scope: HTTP runtime and OpenAPI conventions, subordinate to the
[feature template](feature-template.md) for layering and ownership. HTTP
`OperationContract` declarations belong in API views or their schema module,
not in feature domain contracts. Examples below are target adapter patterns;
named command/query/actor adapters must be supplied by the owning feature.

Transport validates shape, creates typed command inputs, calls its own
application/queries and maps output. It does not save serializers, own workflow
transactions or implement eligibility. Domain exceptions are mapped centrally;
each operation documents the resulting authentication/authorization/domain errors.

Use `OperationContract` as the single source of truth for each HTTP method.
An operation contract owns:

- The request payload serializer, when the method accepts a body.
- Every success and problem response returned by that method.
- OpenAPI request and response generation.
- Runtime request serializer construction.
- Runtime success and application error responses.

GET, POST, PUT, PATCH, and DELETE use the same declaration pattern.

## OpenAPI metadata ownership and verification

Agent-facing endpoints use agent terminology consistently: `AgentInfoAPIView`,
`AgentEnrollmentAPIView`, and `AgentHeartbeatAPIView` serve `/agent/info`,
`/agent/enrollments`, and `/agent/heartbeat`. Schema operation IDs, tags, and
URL names likewise use `agent`, not `device`; these APIs concern the agent
software regardless of the physical device hosting it.

Tags describe an endpoint's owning feature, not its transport mount. Declare
semantic tags on the owning view or operation; the schema endpoint uses its local
`SchemaAPIView` with the `Schema` tag. Never globally map a generic `Api` tag to
`Schema`: unrelated operations must not be reclassified by metadata normalization.

`ProjectAutoSchema` removes only a verified `/api/` mount from generated path
tokens. Actual request paths, explicitly declared operation IDs, resource names
such as API keys, and path-parameter suffixes remain intact. Summary fallback
uses the resulting operation ID without guessing or stripping resource names.
Root tag definitions are deduplicated only when identical after normalization;
conflicting definitions fail generation. Standalone modules retain root-level
security schemes referenced through inherited security requirements.

This metadata hardening does not change HTTP routes, permissions, payloads, or
status codes. Operation IDs and tags can affect generated-client method names and
grouping; review regenerated diffs with client owners before merge. This is not
an assertion that every endpoint conforms to the response standard.

Verification follows [quality gates](ai-team/quality-gates.md): focused schema
tests, regeneration, bundling, and Spectral linting are separate checks. A
`spectacular_modules --dry-run` prepares documents without writing them; it is
not a substitute for OpenAPI validation, example validation, or runtime contract
tests. Production-settings parity, SDK compatibility, and base-branch contract
comparison require separate evidence.

## Response formats

Successful single-resource responses use the project envelope:

```json
{
  "data": {
    "id": 42,
    "display_name": "Example User"
  }
}
```

Collection responses always include a bounded `data` array and `meta.pagination`
with `count`, `page`, `page_size`, `next`, and `previous`. Lists are paginated even
when the caller does not provide pagination query parameters.

Errors use the application JSON envelope described in the response standard:

The HTTP response status line is authoritative for the status code (for example,
`HTTP/1.1 422 Unprocessable Content`). Do not repeat `status` in the JSON body;
clients should use the HTTP status for protocol handling and the stable `error.code`
for application-specific handling.

```json
{
    "error": {
        "code": "validation_failed",
        "message": "One or more fields are invalid.",
        "details": [
            {"field": "display_name", "code": "required", "message": "This field is required."}
        ],
        "request_id": "b1f2c3d4"
  }
}
```

For domain-specific alternatives, use the shorter `ResponseContract.polymorphic(...)`
helper:

```python
success = ResponseContract.polymorphic(
    "BookingCountAnalyticsResponse",
    [
        AnalyticsCountTrendSerializer,
        AnalyticsAggregatedLogSerializer(many=True),
    ],
)

get_contract = OperationContract(
    success=success,
    bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
)
```

This helper is equivalent to `documented(...)` with
`ResponseSchemaFactory.polymorphic(...)`, using `200 OK` by default. Provide
`status_code=` when the polymorphic success response uses another successful
HTTP status. Use `ResponseSchemaFactory.list_variants(...)` only when alternatives are exactly a
plain list and a paginated list.

## Complete view example

Declare reusable response shapes once, then compose an exact response set for
each method.

```python
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppDetailAPIView
from drf_api_contracts import OperationContract, ResponseContract, ResponseSet

from .serializers import UpdateUserSerializer, UserSerializer
from ..application import UpdateUserInput, update_user
from ..queries import get_user


class RetrieveUserView(AppDetailAPIView):
    success_response = ResponseContract.success("User", UserSerializer)
    not_found_response = ResponseContract.problem(status.HTTP_404_NOT_FOUND)

    get_contract = OperationContract(
        responses=ResponseSet(
            success=success_response,
            not_found=not_found_response,
        ),
    )
    patch_contract = OperationContract(
        request=UpdateUserSerializer,
        responses=ResponseSet(
            success=success_response,
            bad_request=ResponseContract.problem(status.HTTP_400_BAD_REQUEST),
            not_found=not_found_response,
        ),
    )

    def handle_get(self, request: Request, pk: int) -> Response:
        user = get_user(pk=pk, actor=actor_from_request(request))
        return self.respond(user)

    def handle_patch(self, request: Request, pk: int) -> Response:
        serializer, error = self.validate_request(partial=True)
        if error is not None:
            return error
        user = update_user(
            pk=pk,
            data=UpdateUserInput(**serializer.validated_data),
            actor=actor_from_request(request),
        )
        return self.respond(user)
```

The base view discovers `{method}_contract`, registers its schema, resolves the
current operation, validates input, and serializes output. No normal CRUD
handler needs a schema decorator. `actor_from_request` denotes the configured
identity-to-neutral-context adapter, not an implemented helper assumed here.
Commands fetch and authorize mutable state themselves; do not pass an earlier
unlocked ORM instance as the command's correctness boundary.

## Required API view template

All new and migrated `AppAPIView` endpoints must follow this template:

```python
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppAPIView
from drf_api_contracts import OperationContract, ResponseContract, ResponseSet

from .serializers import ItemCreateSerializer, ItemSerializer
from ..application import CreateItemInput, create_item
from ..queries import get_item


class ItemAPIView(AppAPIView):
    permission_classes = [...]

    item_response = ResponseContract.success("Item", ItemSerializer)
    bad_request_response = ResponseContract.problem(status.HTTP_400_BAD_REQUEST)
    not_found_response = ResponseContract.problem(status.HTTP_404_NOT_FOUND)

    get_contract = OperationContract(
        responses=ResponseSet(
            success=item_response,
            not_found=not_found_response,
        ),
    )
    post_contract = OperationContract(
        request=ItemCreateSerializer,
        responses=ResponseSet(
            success=item_response,
            bad_request=bad_request_response,
        ),
    )

    def handle_get(self, request: Request, *args, **kwargs) -> Response:
        item = get_item(actor=actor_from_request(request), **kwargs)
        return self.respond(item)

    def handle_post(self, request: Request, *args, **kwargs) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        item = create_item(
            data=CreateItemInput(**serializer.validated_data),
            actor=actor_from_request(request),
        )
        return self.respond(item)
```

Rules for this template:

1. Define response contracts as class attributes. Do not create module-global
   endpoint response constants such as `CURRENT_USER_RESPONSE`.
2. Define one `{method}_contract` for every exposed method: `get_contract`,
   `post_contract`, `put_contract`, `patch_contract`, or `delete_contract`.
3. Implement `handle_get`, `handle_post`, `handle_put`, `handle_patch`, and
    `handle_delete` for synchronous endpoint work. `AppAPIView` dispatches these
    handlers through `sync_to_async`; direct async HTTP methods are also
    supported when an endpoint requires asynchronous control flow.
4. Use `self.respond(...)` for model or serializer-backed instances and
   `self.respond_data(...)` only for already-shaped primitive payloads.
5. Use `self.validate_request()` for request-body validation and return its
   error before executing domain work.
6. Return problems through `self.respond_problem(<name>, ...)`, where `<name>`
    matches the named response in the operation's `ResponseSet`.

`AppAPIView` owns the async HTTP dispatch. Keeping endpoint logic in synchronous
`handle_<method>` methods ensures database work is executed through the shared
dispatcher and keeps the operation contract, schema, validation, and runtime
response aligned.

## Declaring HTTP methods

Every method receives a complete operation contract. Configure only responses
that the method can actually return.

```python
detail_response = ResponseContract.success("Item", ItemSerializer)
created_response = ResponseContract.success(
    "CreatedItem",
    ItemSerializer,
    status_code=status.HTTP_201_CREATED,
)
bad_request = ResponseContract.problem(status.HTTP_400_BAD_REQUEST)
not_found = ResponseContract.problem(status.HTTP_404_NOT_FOUND)

get_contract = OperationContract(
    responses=ResponseSet(
        success=detail_response,
        not_found=not_found,
    ),
)

post_contract = OperationContract(
    request=CreateItemSerializer,
    responses=ResponseSet(
        success=created_response,
        bad_request=bad_request,
    ),
)

put_contract = OperationContract(
    request=ReplaceItemSerializer,
    responses=ResponseSet(
        success=detail_response,
        bad_request=bad_request,
        not_found=not_found,
    ),
)

patch_contract = OperationContract(
    request=UpdateItemSerializer,
    responses=ResponseSet(
        success=detail_response,
        bad_request=bad_request,
        not_found=not_found,
    ),
)

delete_contract = OperationContract(
    responses=ResponseSet(
        success=ResponseContract.no_content(),
        not_found=not_found,
    ),
)
```

`AppAPIView` applies these contracts to matching handler methods by convention.
Use `contract.schema(...)` directly only as an escape hatch when an unusual
operation needs explicit drf-spectacular options:

```python
@get_contract.schema()
async def custom_operation(...):
    ...
```

The operation automatically documents every configured response. There is no
separate `response_names` list that can drift from the response set.

## Request payloads

POST, PUT, and PATCH declare a DRF serializer class in `request`. The same class
generates the OpenAPI request body and creates the runtime serializer.

Create:

```python
serializer = self.post_contract.serializer(
    data=request.data,
    context={"request": request},
)
```

Full replacement:

```python
serializer = self.put_contract.serializer(
    instance=item,
    data=request.data,
    context={"request": request},
)
```

Partial update:

```python
serializer = self.patch_contract.serializer(
    instance=item,
    data=request.data,
    partial=True,
    context={"request": request},
)
```

Use `partial=True` only for PATCH. Serializer validation remains explicit:

Legacy partial-PUT endpoints are compatibility exceptions, not the default for
new operations. Keep their current behavior until an approved client migration.
Command inputs must preserve omitted-versus-null distinctions for updates;
using a dataclass default of `None` for both silently loses PATCH semantics.

```python
if not serializer.is_valid():
    return self.patch_contract.respond_problem(
        "bad_request",
        code=MessageCode.VALIDATION_ERROR,
        errors=serializer.errors,
    )
```

GET and normal DELETE operations omit `request`. They can generate schemas and
responses, but cannot construct a request serializer.

## Success contracts

A success contract owns the status, payload serializer, OpenAPI response
schema, envelope, and list cardinality.

```python
detail_response = ResponseContract.success("User", UserSerializer)

list_response = ResponseContract.success(
    "Users",
    UserSerializer,
    many=True,
)

created_response = ResponseContract.success(
    "CreatedUser",
    UserSerializer,
    status_code=status.HTTP_201_CREATED,
)
```

Return model instances or serializer-compatible objects, not pre-serialized
`.data`:

```python
return self.get_contract.respond(user, context={"request": request})
```

For a computed payload that is already a primitive dictionary or list, use the
explicit no-serialization path. This is appropriate for analytics selectors and
cache values that are already schema-compatible:

```python
return self.respond_data(computed_payload)
```

Do not use `respond_data` for model instances; use `respond` so the response
serializer remains the payload source of truth.

## Lists and variants

Use `AppListAPIView` for ordinary serializer-backed collections. It returns a
normal list when no `page` query parameter is supplied and a paginated envelope
when pagination is requested or `paginate_by_default = True`.

```python
class ListItemsView(AppListAPIView):
    pagination_class = EquipmentPagination
    paginate_by_default = False
    get_contract = OperationContract(
        success=ResponseContract.documented(
            status.HTTP_200_OK,
            ResponseSchemaFactory.list_variants("Items", ItemSerializer),
        ),
    )

    def handle_get(self, request: Request) -> Response:
        return self.list_response_sync(list_items(actor=actor_from_request(request)))
```

For a mandatory paginated endpoint, use `ResponseContract.paginated(...)`
and set `paginate_by_default = True`. For an endpoint that can return either a
list or a paginated envelope, use the existing schema factory helper:

```python
success = ResponseContract.documented(
    status.HTTP_200_OK,
    ResponseSchemaFactory.list_variants("Items", ItemSerializer),
)
```

## Problem contracts

Declare problem responses with DRF status constants:

```python
bad_request = ResponseContract.problem(status.HTTP_400_BAD_REQUEST)
not_found = ResponseContract.problem(status.HTTP_404_NOT_FOUND)
conflict = ResponseContract.problem(status.HTTP_409_CONFLICT)
upstream_error = ResponseContract.problem(status.HTTP_502_BAD_GATEWAY)
```

Return one through the current operation:

```python
return self.patch_contract.respond_problem(
    "bad_request",
    code=MessageCode.VALIDATION_ERROR,
    errors=serializer.errors,
)
```

Supported arguments are:

- `code`: preferably a stable `MessageCode`.
- `detail`: human-readable detail, `MessageCode`, or `MessageError`.
- `errors`: structured field or domain errors.
- `problem_type`: RFC 9457 problem type URI; defaults to `about:blank`.

## Current constraints

- `ResponseSet` has a required `success` response and accepts arbitrary named
    4xx/5xx problem responses, such as `conflict` or `upstream_error`.
- The success response uses the standard `{data: ...}` envelope.
- Problem contracts require a 4xx or 5xx status.
- `ResponseContract.empty(...)` documents an empty JSON success envelope.
- File downloads, redirects, cookies, multipart upload behavior, raw 204
    responses, and router-driven ViewSets require dedicated transport adapters.

`ResponseContract.no_content()` documents 204; verify the adapter emits no body
or success envelope. Upload/download/auth adapters still call application/queries
for business behavior. A router or async view does not exempt layer rules.

## Migration checklist

1. Declare one `OperationContract` per implemented HTTP method.
2. Give each operation a `ResponseSet` containing exactly its responses.
3. Share immutable `ResponseContract` objects only when status and shape
   are identical.
4. Give POST, PUT, and PATCH their request serializer.
5. Remove normal CRUD schema decorators; the base view discovers contracts.
6. Construct body serializers with `method_contract.serializer()`.
7. Return success with `method_contract.respond(instance)`.
8. Return errors with `method_contract.respond_problem(name, ...)`.
9. Remove duplicate schema dictionaries, raw statuses, and manual serialization.
10. Migrate shared base views before their individual subclasses.
11. Use `@method_contract.schema(...)` only for unusual explicit overrides.
12. Run lint, tests, and OpenAPI module generation.
13. Replace serializer writes/ad hoc ORM reads with typed commands/named queries;
    test denied non-HTTP commands as well as endpoint permissions.

## Selector and Options Endpoints Contract (`/options`)

`GET /api/<resource>/options/` (and canonical `/options`) is reserved for selector data:
- **Response Shape:** Flat array of `{ "id", "sku", "name" }` inside `{"data": [...]}`. These three keys are fixed for every options endpoint.
- **Key Semantics:**
  - `id`: Primary key to submit in mutation payloads and relation foreign keys.
  - `name`: Display text rendered in user interface dropdowns/selectors.
  - `sku`: Secondary identifier (code/asset tag/search badge).
- **No Extra Fields:** Anything beyond `id`, `sku`, and `name` belongs on the list or detail endpoint.
- **Filtering:** Accepts the same query parameters as the list endpoint and reuses the same FilterSet / query serializer.
- **Pagination:** None (or high cap), since selectors need the full set of choices.
- **Ordering:** Stable default, by `name` (`order_by("name", "id")`).
- **Querying:** Strict `.only("id", "sku", "name")`, avoiding joins or prefetches. Use `Exists(...)` / `~Exists(...)` for has/has-not relations.

## Validation

```powershell
.\.venv\Scripts\ruff.exe check core tests
.\.venv\Scripts\python.exe -m pytest tests\unit\test_api_response_schema.py tests\unit\test_payload_openapi_schema.py -q
.\.venv\Scripts\python.exe manage.py spectacular_modules --output-dir openapi --dry-run
.\.venv\Scripts\python.exe manage.py spectacular_modules --output-dir openapi
```

`spectacular_modules` regenerates the master document, shared components, and
feature modules under `openapi/`, plus `api-catalog.json` containing a
readable API catalog with example request and response payloads. The catalog
uses the same generated schema as the OpenAPI documents. To generate only that
JSON artifact, run `python scripts/openapi/generate_api_catalog.py`;
`--output-dir` selects a different destination. It fails when a generated path cannot be
assigned to a feature URL module; use `--include-untagged` only when an
unclassified module is intentional. Run `--dry-run` in CI or before release to
validate generation without changing files (including the API catalog). By default, a successful run
removes stale `.yml` and `.yaml` files from the output directory; use
`--no-clean` only when retaining stale generated files is intentional.
