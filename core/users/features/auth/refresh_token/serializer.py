from drf_api_contracts import ResponseEnvelopeSerializer
from rest_framework import serializers


class RefreshTokenResponseSerializer(serializers.Serializer):
    access = serializers.CharField()


class RefreshTokenEnvelopeSerializer(ResponseEnvelopeSerializer):
    data = RefreshTokenResponseSerializer()
