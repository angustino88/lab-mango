from drf_api_contracts import ResponseEnvelopeSerializer
from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=1024, write_only=True, trim_whitespace=False)


class LoginResponseSerializer(serializers.Serializer):
    username = serializers.CharField()
    access = serializers.CharField()
    is_active = serializers.BooleanField()


class LoginEnvelopeSerializer(ResponseEnvelopeSerializer):
    data = LoginResponseSerializer()
