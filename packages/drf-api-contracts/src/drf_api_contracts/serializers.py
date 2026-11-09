from rest_framework import serializers


class ResponseEnvelopeSerializer(serializers.Serializer):
    """Base serializer for successful API responses."""


class EmptyPayloadSerializer(serializers.Serializer):
    """Payload serializer for successful responses whose data object is empty."""


class PaginationMetadataSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    page = serializers.IntegerField(min_value=1)
    page_size = serializers.IntegerField(min_value=1)
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)


class PaginatedResponseEnvelopeSerializer(ResponseEnvelopeSerializer):
    meta = serializers.DictField()


class ProblemDetailSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.ListField(child=serializers.DictField(), allow_empty=True)
    request_id = serializers.CharField()


class ProblemResponseEnvelopeSerializer(serializers.Serializer):
    """Document the envelope emitted by ResponseContract.respond_problem()."""

    error = ProblemDetailSerializer()
