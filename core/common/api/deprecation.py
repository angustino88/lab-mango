"""Deprecated route aliases (response standard VER-3, request standard CMP-3).

A deprecated path keeps working for one release: every method is marked ``deprecated`` in the schema, and each
response carries ``Deprecation: true`` and a ``Link`` to the successor route. The gate (``contract_rules``) then
treats the alias as on its way out instead of as a design to follow.
"""

from collections.abc import Callable
from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view

_METHODS = ("get", "post", "put", "patch", "delete")


def deprecated_alias(view_class: type, *, successor: Callable[..., str], description: str) -> type:
    """Return a subclass of ``view_class`` serving a deprecated path.

    ``successor(**kwargs)`` builds the successor path from the URL keyword arguments.
    """

    def finalize_response(self, request: Any, response: Any, *args: Any, **kwargs: Any) -> Any:
        response = view_class.finalize_response(self, request, response, *args, **kwargs)
        response["Deprecation"] = "true"
        response["Link"] = f'<{successor(**self.kwargs)}>; rel="successor-version"'
        return response

    alias = type(
        f"Deprecated{view_class.__name__}",
        (view_class,),
        {"__module__": view_class.__module__, "__doc__": description, "finalize_response": finalize_response},
    )
    # Only the operations the view really serves: those with a contract.
    methods = [method for method in _METHODS if getattr(view_class, f"{method}_contract", None) is not None]
    return extend_schema_view(
        **{method: extend_schema(deprecated=True, description=description) for method in methods}
    )(alias)


__all__ = ["deprecated_alias"]
