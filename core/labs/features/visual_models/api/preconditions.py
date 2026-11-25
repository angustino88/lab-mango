import re

from drf_spectacular.utils import OpenApiParameter
from rest_framework.exceptions import APIException, ParseError


class ModelPreconditionRequired(APIException):
    status_code = 428
    default_detail = "Send If-Match with the current quoted version, or If-None-Match: * to create where documented."
    default_code = "precondition_required"


IF_MATCH = OpenApiParameter(
    "If-Match", str, OpenApiParameter.HEADER, description='Current quoted version, for example "1".'
)
VERSION_PRECONDITIONS = [IF_MATCH]
CREATE_OR_VERSION_PRECONDITIONS = [
    IF_MATCH,
    OpenApiParameter(
        "If-None-Match", str, OpenApiParameter.HEADER, description="Use * on PUT to assign a target that has no model."
    ),
]


def expected_version(request, *, allow_create=False):
    match = request.headers.get("If-Match")
    absent = request.headers.get("If-None-Match")
    if match is None and absent is None:
        raise ModelPreconditionRequired
    if allow_create and absent == "*" and match is None:
        return 0
    if absent is not None or not match or not re.fullmatch(r'"[1-9][0-9]*"', match):
        raise ParseError("Use one quoted version in If-Match.")
    return int(match[1:-1])
