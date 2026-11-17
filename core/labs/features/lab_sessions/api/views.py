"""HTTP views for the lab sessions feature."""

from __future__ import annotations

from typing import Any

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.api_views import AppListAPIView
from core.labs.features.base import CommandAPIView
from core.labs.features.lab_sessions.api.serializers import SessionLogItemSerializer, SessionLogListQuerySerializer
from core.labs.features.lab_sessions.queries import list_session_logs


class SessionLogListAPIView(AppListAPIView, CommandAPIView):
    """List completed remote sessions (newest login first). Lab coordinators and admins only (O11)."""

    schema_tags = ("Lab Sessions",)
    get_contract = OperationContract(
        query=SessionLogListQuerySerializer,
        success=ResponseContract.paginated("SessionLogList", SessionLogItemSerializer),
        bad_request=ResponseContract.bad_request(),
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        clean = {key: value for key, value in (filters or {}).items() if key not in ("page", "page_size")}
        return self._execute(lambda: list_session_logs(**clean))


__all__ = ["SessionLogListAPIView"]
