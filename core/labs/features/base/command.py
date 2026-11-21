"""Reusable API foundations for command- and selector-driven features, with the Labs access policy."""

from core.common.api.command_views import CommandAPIView as _CommandAPIView
from core.common.api.operations import operation

from .access import LAB_OPERATIONS_ACCESS


class CommandAPIView(_CommandAPIView):
    # Labs command view. Default access: lab operators (``lab_operations.manage``). The inherited docstring is kept
    # because generated API descriptions fall back to it.
    __doc__ = _CommandAPIView.__doc__
    permission_classes = LAB_OPERATIONS_ACCESS


__all__ = ["CommandAPIView", "operation"]
