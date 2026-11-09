from rest_framework import serializers


class AADLoginResponseSerializer(serializers.Serializer):
    username = serializers.CharField()
    access = serializers.CharField()
    is_active = serializers.BooleanField()
    csrf_token = serializers.CharField(required=False)


class AADLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField(write_only=True, max_length=16384, trim_whitespace=False)


class AADChallengeResponseSerializer(serializers.Serializer):
    nonce = serializers.CharField()
    csrf_token = serializers.CharField()
