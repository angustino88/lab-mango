"""Base classes and operation contract helpers for Support Desk API views."""

from typing import Any

from drf_api_contracts import OperationContract

from core.common.api.api_views import AppListAPIView
from core.common.api.command_views import CommandAPIView
from core.common.api.operations import operation as common_operation
from core.support_desk.features.tickets.api.permissions import IsSupportRequester


def operation(name: str = "", payload: Any = None, *, query: Any = None, many: bool = False, **kwargs: Any) -> OperationContract:
    """Support Desk contract: documents 403, and a list is paginated only when it has a query serializer."""
    kwargs.setdefault("forbidden", True)
    return common_operation(name, payload, query=query, many=many, paginated=many and query is not None, **kwargs)


class SupportAPIView(AppListAPIView, CommandAPIView):
    """Base API view for Support Desk endpoints.

    Domain errors propagate to the global mapper; this class only declares access and schema tags.
    """

    permission_classes = [IsSupportRequester]
    schema_tags = ("Support Desk",)
