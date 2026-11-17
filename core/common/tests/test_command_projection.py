"""The optional projection flag must preserve the command result when disabled."""

from drf_api_contracts import OperationContract, ResponseContract
from rest_framework import serializers
from rest_framework.response import Response

from core.common.api.command_views import CommandAPIView


class ProjectionPayload(serializers.Serializer):
    value = serializers.IntegerField()


def test_disabled_projection_returns_the_original_command_result(monkeypatch):
    view = CommandAPIView()
    contract = OperationContract(success=ResponseContract.success("ProjectionPayload", ProjectionPayload))
    monkeypatch.setattr(view, "operation", lambda: contract)
    monkeypatch.setattr(view, "respond", lambda value: Response({"data": value}))
    snapshot = {"value": 7}
    response = view._execute(lambda: snapshot, project=False)
    assert response.status_code == 200
    assert response.data == {"data": {"value": 7}}
