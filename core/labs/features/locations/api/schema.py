"""HTTP response contracts for location endpoints."""

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import status


def operation(
    name,
    payload,
    *,
    request=None,
    query=None,
    created=False,
    many=False,
    delete=False,
    bad_request=True,
    validation_error=True,
):
    success = (
        ResponseContract.no_content()
        if delete
        else ResponseContract.created(name, payload)
        if created
        else ResponseContract.paginated(name, payload)
        if many and not created and not delete and (query is not None or request is None)
        else ResponseContract.success(name, payload, many=True)
        if many
        else ResponseContract.success(name, payload)
    )
    responses = {"not_found": ResponseContract.not_found()}
    if many and query is not None:
        responses["bad_request"] = ResponseContract.bad_request()
    if request is not None and bad_request:
        responses["bad_request"] = ResponseContract.problem(status.HTTP_400_BAD_REQUEST)
    if request is not None and validation_error:
        responses["validation_error"] = ResponseContract.problem(status.HTTP_422_UNPROCESSABLE_ENTITY)
    if request is not None:
        responses["conflict"] = ResponseContract.conflict()
    return OperationContract(
        request=request,
        query=query,
        success=success,
        **responses,
    )


__all__ = ["operation"]
