# DRF API Contracts

`drf-api-contracts` keeps runtime response generation and OpenAPI response
documentation in one reusable contract.

```python
from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import serializers, status


class WidgetSerializer(serializers.Serializer):
    id = serializers.IntegerField()


operation = OperationContract(
    success=ResponseContract.success("Widget", WidgetSerializer),
    created=ResponseContract.created("WidgetCreated", WidgetSerializer),
    not_found=ResponseContract.problem(status.HTTP_404_NOT_FOUND),
    tags=["widgets"],
)

response = operation.respond({"id": 7})
```

`success` is the primary successful response. Additional named successful
responses, such as `created`, can be declared directly with 2xx or 3xx
contracts. Named 4xx and 5xx contracts are documented as problem responses.

`OperationContract.schema()` forwards these tags to `drf-spectacular`'s
`extend_schema`, so generated OpenAPI operations include `tags: ["widgets"]`.
Explicit `schema(tags=[...])` arguments take precedence over the contract tags.

Applications can supply `ContractSettings` to customize envelope keys, problem
details, error codes, and pagination conventions without coupling the package to
application models or enums.

## Development

```shell
python -m pip install -e ".[test]"
python -m pytest
```

## Repository split and release

The `packages/drf-api-contracts` directory is self-contained and can become its
own Git repository without importing any LabMango module. After moving it to a
new repository, publish a tagged wheel to a private package index or PyPI and
replace the host application's path source with a normal version constraint:

```toml
dependencies = ["drf-api-contracts>=0.1,<1"]
```

Use semantic versioning. Public names exported from `drf_api_contracts` are the
supported API; internal modules may evolve between minor releases.
