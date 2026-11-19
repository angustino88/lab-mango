"""License checks: how agents read licenses on lab computers, and what they found.

A check is configured in the web app (probe, extraction mapping, carrier, targets). Agents of the
targeted computers fetch it, run it read-only and report one run at a time. Each run updates the
license observations of that check on that computer, and matched licenses are compared with the
inventory (``License.serial_number`` is the match key).
"""

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel

CHECK_KEY_VALIDATOR = RegexValidator(r"^[a-z][a-z0-9_-]{0,31}$", "Use a lowercase slug of at most 32 characters.")
MIN_CHECK_INTERVAL_MINUTES = 15


class LicenseCheck(TimeStampedModel, UserStampedModel):
    """One configured check. ``revision`` increases on every change agents must pick up."""

    key = models.CharField(max_length=32, unique=True, validators=[CHECK_KEY_VALIDATOR])
    name = models.CharField(max_length=128)
    vendor = models.CharField(max_length=128, blank=True, default="")
    probe = models.JSONField(help_text="Probe of the closed catalog: command, file or registry.")
    extract = models.JSONField(help_text="Declarative mapping from the probe output to license fields.")
    carrier = models.JSONField(
        help_text="What holds the licenses: computer, device, dongle, server, equipment, mapped."
    )
    interval_minutes = models.PositiveIntegerField(
        default=360, validators=[MinValueValidator(MIN_CHECK_INTERVAL_MINUTES)]
    )
    is_enabled = models.BooleanField(default=True)
    is_lab_wide = models.BooleanField(default=False, help_text="Runs on every computer with an agent.")
    revision = models.PositiveIntegerField(default=1)
    preset_key = models.CharField(max_length=32, blank=True, default="", help_text="Preset it was created from.")
    expected_licenses = models.ManyToManyField(
        "labs.License",
        blank=True,
        related_name="expecting_checks",
        help_text="Licenses this check should find; one no run reports is flagged missing.",
    )

    class Meta:
        app_label = "labs"
        ordering = ("name", "pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(interval_minutes__gte=MIN_CHECK_INTERVAL_MINUTES), name="license_check_min_interval"
            ),
            models.CheckConstraint(condition=Q(revision__gte=1), name="license_check_revision_positive"),
        ]

    def __str__(self) -> str:
        return self.name


class LicenseCheckTarget(models.Model):
    """Where a check runs: exactly one of room, station, bench, equipment category or computer."""

    license_check = models.ForeignKey("labs.LicenseCheck", related_name="targets", on_delete=models.CASCADE)
    room = models.ForeignKey("labs.Room", null=True, blank=True, related_name="+", on_delete=models.CASCADE)
    station = models.ForeignKey("labs.Station", null=True, blank=True, related_name="+", on_delete=models.CASCADE)
    bench = models.ForeignKey("labs.Bench", null=True, blank=True, related_name="+", on_delete=models.CASCADE)
    category = models.ForeignKey(
        "labs.EquipmentCategory", null=True, blank=True, related_name="+", on_delete=models.CASCADE
    )
    equipment = models.ForeignKey("labs.Equipment", null=True, blank=True, related_name="+", on_delete=models.CASCADE)

    TARGET_FIELDS = ("room", "station", "bench", "category", "equipment")

    class Meta:
        app_label = "labs"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        room__isnull=False,
                        station__isnull=True,
                        bench__isnull=True,
                        category__isnull=True,
                        equipment__isnull=True,
                    )
                    | Q(
                        room__isnull=True,
                        station__isnull=False,
                        bench__isnull=True,
                        category__isnull=True,
                        equipment__isnull=True,
                    )
                    | Q(
                        room__isnull=True,
                        station__isnull=True,
                        bench__isnull=False,
                        category__isnull=True,
                        equipment__isnull=True,
                    )
                    | Q(
                        room__isnull=True,
                        station__isnull=True,
                        bench__isnull=True,
                        category__isnull=False,
                        equipment__isnull=True,
                    )
                    | Q(
                        room__isnull=True,
                        station__isnull=True,
                        bench__isnull=True,
                        category__isnull=True,
                        equipment__isnull=False,
                    )
                ),
                name="license_check_target_exactly_one",
            ),
        ]

    @property
    def kind(self) -> str:
        return next(name for name in self.TARGET_FIELDS if getattr(self, f"{name}_id") is not None)


class LicenseCheckRunStatus(models.TextChoices):
    OK = "ok", "OK"
    NOT_INSTALLED = "not_installed", "Not installed"
    FAILED = "failed", "Failed"
    REJECTED = "rejected", "Rejected by the agent"


class LicenseCheckRun(models.Model):
    """One reported run of a check on one computer (the reporting agent's computing unit)."""

    license_check = models.ForeignKey("labs.LicenseCheck", related_name="runs", on_delete=models.CASCADE)
    computing = models.ForeignKey("labs.Equipment", related_name="license_check_runs", on_delete=models.CASCADE)
    agent_uid = models.UUIDField()
    idempotency_key = models.UUIDField()
    content_hash = models.CharField(max_length=64)
    revision = models.PositiveIntegerField()
    sequence = models.PositiveBigIntegerField()
    status = models.CharField(max_length=16, choices=LicenseCheckRunStatus.choices)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.CharField(max_length=512, blank=True, default="")
    started_at = models.DateTimeField()
    duration_ms = models.PositiveIntegerField(default=0)
    license_count = models.PositiveIntegerField(default=0)
    is_applied = models.BooleanField(default=False, help_text="False for stale or outdated-revision runs.")
    received_at = models.DateTimeField()

    class Meta:
        app_label = "labs"
        ordering = ("-received_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("computing", "license_check", "idempotency_key"), name="license_check_run_idempotency_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=("license_check", "computing", "-sequence"), name="license_check_run_latest_idx"),
            models.Index(fields=("received_at",), name="license_check_run_received_idx"),
        ]


class LicenseObservationStatus(models.TextChoices):
    """Outcome of comparing one reported license with the inventory (proposal section 5.4)."""

    MATCHED = "matched", "Matched"
    UNREGISTERED = "unregistered", "Not in inventory"
    AMBIGUOUS = "ambiguous", "Several licenses match"
    CARRIER_UNLINKED = "carrier_unlinked", "Carrier not linked"
    CARRIER_NOT_AT_COMPUTER = "carrier_not_at_computer", "Carrier not at this computer"
    CARRIER_MISMATCH = "carrier_mismatch", "Assigned elsewhere"
    UNASSIGNED = "unassigned", "Not assigned"


class LicenseObservation(models.Model):
    """The current state of one license a check found on one computer.

    ``removed_at`` is set when a complete run no longer lists it; a later run that lists it again
    clears it. Raw tool output, license keys and activation IDs are never stored.
    """

    license_check = models.ForeignKey("labs.LicenseCheck", related_name="observations", on_delete=models.CASCADE)
    computing = models.ForeignKey("labs.Equipment", related_name="license_observations", on_delete=models.CASCADE)
    observation_key = models.CharField(max_length=255)
    vendor = models.CharField(max_length=128, blank=True, default="")
    product_code = models.CharField(max_length=128, blank=True, default="")
    product_name = models.CharField(max_length=255)
    license_serial = models.CharField(max_length=128, blank=True, default="")
    carrier_type = models.CharField(max_length=16)
    carrier_hardware_kind = models.CharField(max_length=32, blank=True, default="")
    carrier_hardware_value = models.CharField(max_length=512, blank=True, default="")
    carrier_equipment = models.ForeignKey(
        "labs.Equipment", null=True, blank=True, related_name="carried_license_observations", on_delete=models.SET_NULL
    )
    license = models.ForeignKey(
        "labs.License", null=True, blank=True, related_name="observations", on_delete=models.SET_NULL
    )
    status = models.CharField(max_length=32, choices=LicenseObservationStatus.choices)
    expires_at = models.DateTimeField(null=True, blank=True)
    final_expires_at = models.DateTimeField(null=True, blank=True)
    max_version = models.CharField(max_length=64, blank=True, default="")
    is_reactivatable = models.BooleanField(default=False)
    last_run = models.ForeignKey("labs.LicenseCheckRun", related_name="+", on_delete=models.PROTECT)
    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "labs"
        ordering = ("computing_id", "product_name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("license_check", "computing", "observation_key"), name="license_observation_key_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=("status",), condition=Q(removed_at__isnull=True), name="license_obs_status_idx"),
            models.Index(fields=("license",), name="license_obs_license_idx"),
        ]


class LicenseAlertKind(models.TextChoices):
    EXPIRY = "expiry", "Expiry"
    MISSING = "missing", "Missing"


class LicenseAlert(models.Model):
    """One alert already sent, so a daily job never sends it twice.

    ``key`` names the occasion: ``"30d:2027-04-09"`` (threshold and expiry date) for expiry alerts,
    ``"check:12"`` for a license a check no longer finds (deleted when it is found again).
    """

    license = models.ForeignKey("labs.License", related_name="alerts", on_delete=models.CASCADE)
    kind = models.CharField(max_length=16, choices=LicenseAlertKind.choices)
    key = models.CharField(max_length=64)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "labs"
        constraints = [models.UniqueConstraint(fields=("license", "kind", "key"), name="license_alert_once_uniq")]
