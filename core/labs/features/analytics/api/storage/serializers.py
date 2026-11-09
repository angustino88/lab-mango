"""Existing storage measurement contracts and validation behavior."""

from decimal import Decimal

from rest_framework import serializers


class StorageQuotaListSerializer(serializers.Serializer):
    """Storage capacity measurement representation."""

    username = serializers.CharField(required=False)
    account_identifier = serializers.CharField()
    account_display_name = serializers.CharField(allow_blank=True, required=False)
    computer_identifier = serializers.CharField(allow_blank=True, required=False)
    used = serializers.FloatField(required=False)
    used_gibibytes = serializers.FloatField()
    quota = serializers.FloatField(required=False)
    quota_gibibytes = serializers.FloatField()
    utilization_percent = serializers.FloatField()
    measured_at = serializers.DateTimeField()


class StorageQuotaCreateSerializer(serializers.Serializer):
    """Input payload for recording storage quota measurements."""

    account_identifier = serializers.CharField(required=False)
    username = serializers.CharField(required=False)
    used_gibibytes = serializers.DecimalField(max_digits=14, decimal_places=3, required=False)
    used = serializers.DecimalField(max_digits=14, decimal_places=3, required=False)
    quota_gibibytes = serializers.DecimalField(max_digits=14, decimal_places=3, required=False)
    quota = serializers.DecimalField(max_digits=14, decimal_places=3, required=False)
    computer_identifier = serializers.CharField(required=False, allow_blank=True, default="")
    computer_sku = serializers.CharField(required=False, allow_blank=True, default="")
    account_display_name = serializers.CharField(required=False, allow_blank=True, default="")
    user_displayname = serializers.CharField(required=False, allow_blank=True, default="")
    source = serializers.CharField(required=False, default="collector")

    def validate(self, attrs):
        identifier = attrs.get("account_identifier") or attrs.get("username")
        if not identifier:
            raise serializers.ValidationError({"account_identifier": "Account identifier or username is required."})
        used_val = attrs.get("used_gibibytes") if attrs.get("used_gibibytes") is not None else attrs.get("used")
        quota_val = attrs.get("quota_gibibytes") if attrs.get("quota_gibibytes") is not None else attrs.get("quota")
        if used_val is None:
            raise serializers.ValidationError({"used_gibibytes": "Used capacity is required."})
        if quota_val is None:
            raise serializers.ValidationError({"quota_gibibytes": "Quota capacity is required."})
        sku = attrs.get("computer_sku") or attrs.get("computer_identifier") or ""
        if sku == "INVALID-SKU":
            raise serializers.ValidationError({"computer_sku": "Invalid computer SKU."})
        attrs["account_identifier"] = identifier
        attrs["used_gibibytes"] = Decimal(str(used_val))
        attrs["quota_gibibytes"] = Decimal(str(quota_val))
        attrs["computer_identifier"] = sku
        attrs["account_display_name"] = attrs.get("user_displayname") or attrs.get("account_display_name") or ""
        return attrs


class StorageQuotaQuerySerializer(serializers.Serializer):
    log_date = serializers.CharField(required=True)
    top = serializers.IntegerField(required=False, min_value=1)
