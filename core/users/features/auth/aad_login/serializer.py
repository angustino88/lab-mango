from rest_framework import serializers


class AADLoginResponseSerializer(serializers.Serializer):
    username = serializers.CharField()
    access = serializers.CharField()
    is_active = serializers.BooleanField()
    csrf_token = serializers.CharField(required=False)


class AADLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField(write_only=True, max_length=16384, trim_whitespace=False)
    nonce_secret = serializers.CharField(
        write_only=True,
        min_length=43,
        max_length=128,
        trim_whitespace=False,
        help_text="The browser's random secret; the ID token's nonce is base64url(SHA-256(nonce_secret)).",
    )


class CSRFTokenResponseSerializer(serializers.Serializer):
    csrf_token = serializers.CharField()
