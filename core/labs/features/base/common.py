"""Labs base views: the shared foundations with the Labs access policy applied (``access.py``)."""

from core.common.api.command_views import FeatureAPIView as _FeatureAPIView
from core.common.api.options import OptionsAPIView as _OptionsAPIView

from .access import LAB_OPERATIONS_ACCESS


class FeatureAPIView(_FeatureAPIView):
    # Labs feature view. Default access: lab operators (``lab_operations.manage``). The inherited docstring is kept
    # because generated API descriptions fall back to it.
    __doc__ = _FeatureAPIView.__doc__
    permission_classes = LAB_OPERATIONS_ACCESS


class OptionsAPIView(_OptionsAPIView):
    # Labs dropdown selector view. Default access: lab operators (``lab_operations.manage``); docstring kept
    # (see above).
    __doc__ = _OptionsAPIView.__doc__
    permission_classes = LAB_OPERATIONS_ACCESS


__all__ = ["FeatureAPIView", "OptionsAPIView"]
