"""Wire shapes of the license-check staff API."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.summary_serializers import choice_field, embedded_resource
from core.labs.features.base.serializers import NamedReferenceSerializer, UIDNamedReferenceSerializer
from core.labs.models import LicenseCheckRunStatus, LicenseObservationStatus

TARGET_KIND_CHOICES = (
    ("room", "Room"),
    ("station", "Station"),
    ("bench", "Bench"),
    ("category", "Equipment category"),
    ("equipment", "Computer"),
)
CONFIG_HELP = {
    "probe": "Closed catalog: {type: command, executable, args, timeout_s, encoding} | {type: file, path} | "
    "{type: registry, hive: HKLM, key, values}.",
    "extract": "{format: xml|json|text|values, records, fields: {product_name, product_code, max_version, "
    "expires_at, final_expires_at, carrier_id, license_serial, is_reactivatable, carrier_type}, date_formats, "
    "never_values}.",
    "carrier": "{type: computer|device|dongle|server|equipment|mapped, hardware_id_kind, equipment_uid, "
    "type_map, default_type}.",
}


@embedded_resource
class LicenseCheckTargetSerializer(serializers.Serializer):
    """One scope the check runs on; owned by the check."""

    id = serializers.IntegerField(help_text="Id of the room, station, bench, category or computer.")
    kind = choice_field(TARGET_KIND_CHOICES)
    name = serializers.CharField()


@extend_schema_field(LicenseCheckTargetSerializer(many=True))
class TargetsField(serializers.Field):
    def __init__(self, **kwargs):
        kwargs.setdefault("read_only", True)
        kwargs.setdefault("source", "*")
        super().__init__(**kwargs)

    def to_representation(self, check):
        labels = dict(TARGET_KIND_CHOICES)
        items = []
        for target in check.targets.all():
            kind = target.kind
            related = getattr(target, kind)
            items.append(
                {
                    "id": related.pk,
                    "kind": {"value": kind, "label": labels[kind]},
                    "name": getattr(related, "name", ""),
                }
            )
        return items


class LicenseCheckSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    key = serializers.CharField()
    name = serializers.CharField()
    vendor = serializers.CharField()
    probe = serializers.JSONField(help_text=CONFIG_HELP["probe"])
    extract = serializers.JSONField(help_text=CONFIG_HELP["extract"])
    carrier = serializers.JSONField(help_text=CONFIG_HELP["carrier"])
    interval_minutes = serializers.IntegerField()
    is_enabled = serializers.BooleanField()
    is_lab_wide = serializers.BooleanField(help_text="Runs on every computer with an agent.")
    revision = serializers.IntegerField(help_text="Increases on every change agents pick up.")
    preset_key = serializers.CharField()
    targets = TargetsField()
    license_count = serializers.IntegerField(help_text="Licenses currently found by this check.")
    attention_count = serializers.IntegerField(help_text="Found licenses that are not matched.")
    created_at = serializers.DateTimeField(source="created")
    updated_at = serializers.DateTimeField(source="modified")


class LicenseCheckTargetRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=TARGET_KIND_CHOICES)
    target_id = serializers.IntegerField(
        min_value=1, help_text="Id of the room, station, bench, category or computer."
    )


class LicenseCheckWriteSerializer(serializers.Serializer):
    """Create (from scratch or a preset) or change a check. Admin-only: vendor, probe, extract, carrier."""

    preset_key = serializers.CharField(
        max_length=32, required=False, help_text="Create from this preset; probe, extract and carrier are copied."
    )
    key = serializers.RegexField(r"^[a-z][a-z0-9_-]{0,31}$", max_length=32, required=False)
    name = serializers.CharField(max_length=128, required=False)
    vendor = serializers.CharField(max_length=128, required=False, allow_blank=True)
    probe = serializers.JSONField(required=False, help_text=CONFIG_HELP["probe"])
    extract = serializers.JSONField(required=False, help_text=CONFIG_HELP["extract"])
    carrier = serializers.JSONField(required=False, help_text=CONFIG_HELP["carrier"])
    interval_minutes = serializers.IntegerField(min_value=15, max_value=10080, required=False)
    is_enabled = serializers.BooleanField(required=False)
    is_lab_wide = serializers.BooleanField(required=False)
    targets = LicenseCheckTargetRequestSerializer(many=True, required=False)


class LicenseCheckQuerySerializer(PageNumberQuerySerializer):
    q = serializers.CharField(required=False, allow_blank=True, max_length=128)
    is_enabled = serializers.BooleanField(required=False, allow_null=True, default=None)


class LicenseCheckPresetSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    vendor = serializers.CharField()
    description = serializers.CharField()
    interval_minutes = serializers.IntegerField()
    probe = serializers.JSONField()
    extract = serializers.JSONField()
    carrier = serializers.JSONField()


class LicenseCheckPresetListSerializer(serializers.Serializer):
    items = LicenseCheckPresetSerializer(many=True)


@embedded_resource
class LicenseCheckRunSerializer(serializers.Serializer):
    """Newest run of the check on one computer."""

    id = serializers.IntegerField()
    computing = UIDNamedReferenceSerializer()
    revision = serializers.IntegerField()
    status = choice_field(LicenseCheckRunStatus.choices)
    error_code = serializers.CharField()
    error_message = serializers.CharField()
    license_count = serializers.IntegerField()
    is_applied = serializers.BooleanField()
    started_at = serializers.DateTimeField()
    duration_ms = serializers.IntegerField()
    received_at = serializers.DateTimeField()


class LicenseCheckRunListSerializer(serializers.Serializer):
    items = LicenseCheckRunSerializer(many=True)


@embedded_resource
class InventoryValuesSerializer(serializers.Serializer):
    """The matched license's registered values, to compare with what the agent found."""

    serial_number = serializers.CharField()
    expires_at = serializers.DateTimeField(source="expiry_date", allow_null=True)
    max_version = serializers.CharField()


class LicenseObservationSerializer(serializers.Serializer):
    """A license an agent found, and how it compares with the inventory."""

    id = serializers.IntegerField()
    check = NamedReferenceSerializer(source="license_check")
    computing = UIDNamedReferenceSerializer()
    observation_key = serializers.CharField()
    vendor = serializers.CharField()
    product_code = serializers.CharField()
    product_name = serializers.CharField()
    license_serial = serializers.CharField()
    carrier_type = serializers.CharField()
    carrier_hardware_kind = serializers.CharField()
    carrier_hardware_value = serializers.CharField()
    carrier_equipment = UIDNamedReferenceSerializer(allow_null=True)
    license = UIDNamedReferenceSerializer(allow_null=True)
    inventory = InventoryValuesSerializer(source="license", allow_null=True)
    status = choice_field(LicenseObservationStatus.choices)
    expires_at = serializers.DateTimeField(allow_null=True)
    final_expires_at = serializers.DateTimeField(allow_null=True, help_text="Null: perpetual.")
    max_version = serializers.CharField()
    is_reactivatable = serializers.BooleanField()
    first_seen_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()
    removed_at = serializers.DateTimeField(allow_null=True)


class LicenseObservationQuerySerializer(PageNumberQuerySerializer):
    status = serializers.ChoiceField(choices=LicenseObservationStatus.choices, required=False)
    check_id = serializers.IntegerField(min_value=1, required=False)
    license_id = serializers.IntegerField(min_value=1, required=False)
    computing_id = serializers.IntegerField(min_value=1, required=False)
    is_attention_required = serializers.BooleanField(required=False, allow_null=True, default=None)
    include_removed = serializers.BooleanField(required=False, default=False)
    q = serializers.CharField(required=False, allow_blank=True, max_length=128)
