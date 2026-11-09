from drf_api_contracts import ResponseEnvelopeSerializer
from rest_framework import serializers


class LogoutEnvelopeSerializer(ResponseEnvelopeSerializer):
    data = serializers.JSONField(allow_null=True)
