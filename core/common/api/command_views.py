"""Shared base views for feature APIs (ADR 001, D5/D6/D7).

``FeatureAPIView`` declares the one authentication policy every feature inherits: an API key
(agent, API test client) or an authenticated user. A feature that needs stricter access overrides
``permission_classes`` explicitly; it never combines ``HasAPIKeyAccess`` ad hoc.

``CommandAPIView`` runs one command or selector per handler. Business errors are not caught here:
``DomainError`` subclasses and ``ObjectDoesNotExist`` propagate to ``api_exception_handler``, the
single mapper. Only request-validation errors are rendered here, because their status (422 or 400)
depends on the operation's declared contract.
"""

from collections.abc import Callable
from typing import Any, ClassVar

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema_view
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .api_views import AppAPIView
from .permissions import HasAPIKeyAccess, is_authenticated


def actor_from_request(request: Any) -> Any:
    """Return the request's authenticated user, or ``None`` for anonymous and API-key callers."""
    user = getattr(request, "user", None)
    return user if is_authenticated(user) else None


class FeatureAPIView(AppAPIView):
    """Cross-feature API foundation without domain-specific behavior."""

    permission_classes = [HasAPIKeyAccess | IsAuthenticated]
    required_attributes: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def validate_configuration(cls) -> None:
        missing = [name for name in cls.required_attributes if getattr(cls, name, None) is None]
        if missing:
            raise TypeError(f"{cls.__name__} must define: {', '.join(missing)}")

    @property
    def acting_user(self) -> Any:
        """The authenticated user, or ``None`` for API-key callers (their writes record no creator)."""
        return actor_from_request(self.request)


class CommandAPIView(FeatureAPIView):
    """HTTP mapping for domain commands and selector projections."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        async_methods = [method for method in cls.http_method_names if iscoroutinefunction(getattr(cls, method, None))]
        super().__init_subclass__(**kwargs)
        schemas = {
            method: contract.schema()
            for method in cls.http_method_names
            if f"handle_{method}" in cls.__dict__
            if (contract := getattr(cls, f"{method}_contract", None)) is not None
        }
        if schemas:
            extend_schema_view(**schemas)(cls)
        for method in async_methods:
            markcoroutinefunction(getattr(cls, method))

    def project_result(self, result: Any) -> Any:
        return result

    def _execute(
        self,
        function: Callable[[], Any],
        *,
        project: Callable[[Any], Any] | bool | None = None,
        delete: bool = False,
    ) -> Response:
        try:
            result = function()
            if delete:
                return Response(status=204)
            if project is True:
                result = self.project_result(result)
            elif project is not None:
                result = project(result)
            if isinstance(result, Response):
                # The projection already produced the HTTP response (status, headers);
                # serializing it again would emit the Response object as the payload.
                return result
            if self.operation().responses.success.is_paginated:
                return self.list_response_sync(result)
            return self.respond(result)
        except DRFValidationError as error:
            return self.respond_problem(self._validation_problem_name(), code="validation_failed", errors=error.detail)
        except ValidationError as error:
            errors = error.message_dict if hasattr(error, "message_dict") else {"non_field_errors": error.messages}
            return self.respond_problem(self._validation_problem_name(), code="validation_failed", errors=errors)

    def _write(
        self,
        function: Callable[..., Any],
        *,
        lookup: dict[str, Any] | None = None,
        partial: bool = False,
        project: Callable[[Any], Any] | bool | None = None,
    ) -> Response:
        serializer, error = self.validate_request(partial=partial)
        if error is not None:
            return error
        return self._execute(
            lambda: function(actor=self.request.user, **(lookup or {}), **serializer.validated_data),
            project=project,
        )

    def _validation_problem_name(self) -> str:
        return "validation_error" if self.operation().responses.validation_error is not None else "bad_request"


__all__ = ["CommandAPIView", "FeatureAPIView", "actor_from_request"]
