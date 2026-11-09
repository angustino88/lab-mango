"""The single factory for operation response contracts (ADR 001, D7).

Every feature declares ``get_contract`` / ``post_contract`` / ... with ``operation()`` instead of
keeping a private copy. Feature-specific needs are keyword flags, not new factories.
"""

from typing import Any

from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import OpenApiParameter


def operation(
    name: str = "",
    payload: Any = None,
    *,
    request: Any = None,
    query: Any = None,
    created: bool = False,
    many: bool = False,
    delete: bool = False,
    paginated: bool | None = None,
    bad_request: bool = True,
    validation_error: bool = True,
    forbidden: bool = False,
    parameters: tuple[OpenApiParameter, ...] | list[OpenApiParameter] | None = None,
) -> OperationContract:
    """Declare one operation's success and problem responses.

    ``paginated=None`` keeps the Labs rule: a list is paginated when it has a query serializer or no
    request body. Pass ``paginated`` explicitly when a list must be (or must not be) paginated
    regardless. ``forbidden`` additionally documents a 403 for role-gated operations.
    """
    if paginated is None:
        paginated = many and not created and not delete and (query is not None or request is None)

    if delete:
        success = ResponseContract.no_content()
    elif created:
        success = ResponseContract.created(name, payload)
    elif paginated:
        success = ResponseContract.paginated(name, payload)
    elif many:
        success = ResponseContract.success(name, payload, many=True)
    else:
        success = ResponseContract.success(name, payload)

    responses: dict[str, ResponseContract] = {
        "not_found": ResponseContract.not_found(),
        "conflict": ResponseContract.conflict(),
    }
    if forbidden:
        responses["forbidden"] = ResponseContract.forbidden()
    if many and query is not None and not created and not delete:
        responses["bad_request"] = ResponseContract.bad_request()
    if request is not None:
        if bad_request:
            responses["bad_request"] = ResponseContract.bad_request()
        if validation_error:
            responses["validation_error"] = ResponseContract.problem(422)
    return OperationContract(
        request=request,
        query=query,
        success=success,
        parameters=parameters,
        **responses,
    )


__all__ = ["operation"]
