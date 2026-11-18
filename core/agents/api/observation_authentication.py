"""Bound observation bodies before signature authentication materializes bytes."""

from io import BytesIO

from rest_framework.exceptions import APIException, ParseError

from core.agents.api.authentication import AgentSignatureAuthentication, AgentSignatureAuthScheme


class ObservationTooLarge(APIException):
    status_code = 413
    error_code = "payload_too_large"
    default_detail = "Snapshot exceeds 256 KiB."


class ObservationSignatureAuthentication(AgentSignatureAuthentication):
    def authenticate(self, request):
        if request.method in {"POST", "GET"}:
            original = request._request
            try:
                declared = int(request.META.get("CONTENT_LENGTH") or 0)
            except ValueError:
                raise ParseError("Invalid content length.") from None
            if declared > 262144:
                raise ObservationTooLarge()
            body = original.read(262145)
            if len(body) > 262144:
                raise ObservationTooLarge()
            original._body = body
            original._stream = BytesIO(body)
        return super().authenticate(request)


class ObservationSignatureScheme(AgentSignatureAuthScheme):
    name = "observationSignatureAuth"
    target_class = "core.agents.api.observation_authentication.ObservationSignatureAuthentication"
