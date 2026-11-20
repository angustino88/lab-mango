"""Gateways (collectors with a Lab Mango identity) and sources (devices a gateway reads)."""

from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel


class TelemetryDeviceRole(models.TextChoices):
    GATEWAY = "gateway", _("Gateway")
    SOURCE = "source", _("Source")


class TelemetryDeviceKind(models.TextChoices):
    # Gateway kinds: the target type of their scope.
    ROOM_HOST = "room_host", _("Room gateway")
    STATION_PC = "station_pc", _("Station gateway")
    EQUIPMENT_AGENT = "equipment_agent", _("Equipment self-reporting agent")
    # Source kinds: how a gateway reaches the device.
    MODBUS_TCP = "modbus_tcp", _("Modbus TCP endpoint")


GATEWAY_KINDS = (
    TelemetryDeviceKind.ROOM_HOST,
    TelemetryDeviceKind.STATION_PC,
    TelemetryDeviceKind.EQUIPMENT_AGENT,
)
SOURCE_KINDS = (TelemetryDeviceKind.MODBUS_TCP,)


class TelemetryDeviceState(models.TextChoices):
    DISCOVERED = "discovered", _("Discovered")
    CLAIMED = "claimed", _("Claimed")
    RETIRED = "retired", _("Retired")


class TelemetryDevice(TimeStampedModel, UserStampedModel):
    """A gateway or a source in the telemetry system.

    `state` (discovered → claimed → retired) is the device's registration lifecycle, separate from the
    linked equipment's lifecycle and from connectivity (AGENTS.md rule 2). `installed_at` is where a source
    physically is; it decides which gateway reads it and is never used to attribute readings. Kind-specific
    settings live in one-to-one tables (e.g. `ModbusSourceSettings`). Retired rows are kept for provenance
    (`PROTECT` from readings). Owner: telemetry feature.
    """

    role = models.CharField(max_length=16, choices=TelemetryDeviceRole.choices)
    kind = models.CharField(max_length=32, choices=TelemetryDeviceKind.choices)
    device_uid = models.CharField(
        max_length=64,
        unique=True,
        help_text="Source: normalized MAC or serial. Gateway: its agent_uid.",
    )
    equipment = models.OneToOneField(
        "labs.Equipment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="telemetry_device",
        help_text="The physical asset; empty only while discovered.",
    )
    manufacturer = models.CharField(max_length=120, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    installed_at = models.ForeignKey(
        "labs.TelemetryTarget",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="installed_devices",
        help_text="Sources only: where the device physically is.",
    )
    state = models.CharField(
        max_length=16, choices=TelemetryDeviceState.choices, default=TelemetryDeviceState.DISCOVERED
    )
    reported_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_devices",
        help_text="Gateway that last reported this device in discovery.",
    )
    last_seen_address = models.CharField(
        max_length=255, blank=True, default="", help_text="Informational address from the latest discovery report."
    )
    config_version = models.PositiveIntegerField(default=0, help_text="Gateways: bumped on any change to its config.")
    config_version_applied = models.PositiveIntegerField(
        null=True, blank=True, help_text="Gateways: last config version the gateway reported using."
    )
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "labs"
        constraints = [
            models.CheckConstraint(
                condition=(Q(role=TelemetryDeviceRole.GATEWAY) & Q(kind__in=GATEWAY_KINDS))
                | (Q(role=TelemetryDeviceRole.SOURCE) & Q(kind__in=SOURCE_KINDS)),
                name="telemetry_device_kind_matches_role",
            ),
            models.CheckConstraint(condition=~Q(device_uid=""), name="telemetry_device_uid_present"),
            models.CheckConstraint(
                condition=Q(state=TelemetryDeviceState.DISCOVERED) | Q(equipment__isnull=False),
                name="telemetry_device_claimed_has_equipment",
            ),
            models.CheckConstraint(
                condition=Q(role=TelemetryDeviceRole.GATEWAY)
                | Q(state=TelemetryDeviceState.DISCOVERED)
                | Q(installed_at__isnull=False),
                name="telemetry_source_claimed_installed",
            ),
            models.CheckConstraint(
                condition=Q(role=TelemetryDeviceRole.SOURCE) | Q(installed_at__isnull=True),
                name="telemetry_gateway_not_installed",
            ),
            models.CheckConstraint(
                condition=Q(config_version_applied__isnull=True) | Q(config_version_applied__lte=F("config_version")),
                name="telemetry_device_applied_version_known",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.device_uid}"


class ModbusFraming(models.TextChoices):
    MBAP = "mbap", _("Modbus TCP (MBAP header)")
    RTU_OVER_TCP = "rtu_over_tcp", _("Modbus RTU frames over a TCP socket")


class SerialInterface(models.TextChoices):
    NONE = "", _("None (native network device)")
    RS485 = "rs485", _("RS485")
    RS232 = "rs232", _("RS232")


class SerialParity(models.TextChoices):
    NONE = "N", _("None")
    EVEN = "E", _("Even")
    ODD = "O", _("Odd")


class ModbusSourceSettings(TimeStampedModel):
    """How a gateway reaches one claimed `modbus_tcp` source.

    Created when a source is claimed and removed when it is retired, so `(network_host, port)` is unique
    among sources in use. Serial fields describe the bus behind a converter (the converter holds the real
    setting); they are all empty for a native Modbus TCP device. Deleted with its device (no independent
    meaning). Owner: telemetry feature.
    """

    device = models.OneToOneField(
        TelemetryDevice, on_delete=models.CASCADE, primary_key=True, related_name="modbus_settings"
    )
    network_host = models.CharField(max_length=253, help_text="IP address or host name on the gateway's network.")
    port = models.PositiveIntegerField(default=502)
    framing = models.CharField(max_length=16, choices=ModbusFraming.choices, default=ModbusFraming.MBAP)
    serial_interface = models.CharField(max_length=8, choices=SerialInterface.choices, blank=True, default="")
    baud_rate = models.PositiveIntegerField(null=True, blank=True)
    parity = models.CharField(max_length=1, choices=SerialParity.choices, blank=True, default="")
    data_bits = models.PositiveSmallIntegerField(null=True, blank=True)
    stop_bits = models.PositiveSmallIntegerField(null=True, blank=True)
    request_timeout_ms = models.PositiveIntegerField(default=800)
    serialize_requests = models.BooleanField(
        default=True, help_text="One request in flight at a time (a shared half-duplex bus is behind the source)."
    )

    class Meta:
        app_label = "labs"
        constraints = [
            models.UniqueConstraint(fields=["network_host", "port"], name="telemetry_modbus_address_uniq"),
            models.CheckConstraint(condition=~Q(network_host=""), name="telemetry_modbus_host_present"),
            models.CheckConstraint(condition=Q(port__gte=1, port__lte=65535), name="telemetry_modbus_port_range"),
            models.CheckConstraint(
                condition=Q(request_timeout_ms__gte=50, request_timeout_ms__lte=30000),
                name="telemetry_modbus_timeout_range",
            ),
            models.CheckConstraint(
                condition=(
                    Q(serial_interface="")
                    & Q(baud_rate__isnull=True)
                    & Q(parity="")
                    & Q(data_bits__isnull=True)
                    & Q(stop_bits__isnull=True)
                )
                | (
                    ~Q(serial_interface="")
                    & Q(baud_rate__gte=300)
                    & ~Q(parity="")
                    & Q(data_bits__in=(7, 8))
                    & Q(stop_bits__in=(1, 2))
                ),
                name="telemetry_modbus_serial_all_or_none",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.network_host}:{self.port}"
