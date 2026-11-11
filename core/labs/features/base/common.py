"""Labs base views: the shared foundations with the Labs access policy applied (``access.py``)."""

from core.common.api.command_views import FeatureAPIView as _FeatureAPIView
from core.common.api.options import OptionsAPIView as _OptionsAPIView

from .access import LABS_STAFF_ACCESS


class FeatureAPIView(_FeatureAPIView):
    """Labs feature view. Default access: lab coordinators and admins."""

    permission_classes = LABS_STAFF_ACCESS


class OptionsAPIView(_OptionsAPIView):
    """Labs dropdown selector view. Default access: lab coordinators and admins."""

    permission_classes = LABS_STAFF_ACCESS


__all__ = ["FeatureAPIView", "OptionsAPIView"]
