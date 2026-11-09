from rest_framework import serializers


class SendOTPSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=255)
    otp = serializers.CharField(max_length=64)


class SendOTPResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
