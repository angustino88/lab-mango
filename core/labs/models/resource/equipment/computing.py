from django.contrib.postgres.indexes import GinIndex
from django.core.files.base import ContentFile
from django.db import models
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.equipment.equipment import MAC_ADDRESS_VALIDATOR, Equipment


class TechnicalUser(TimeStampedModel, UserStampedModel):
    username = models.CharField(max_length=255, unique=True)

    def __str__(self) -> str:
        return self.username

    class Meta:
        app_label = "labs"
        indexes = [
            GinIndex(fields=["username"], opclasses=["gin_trgm_ops"], name="technical_user_username_idx"),
        ]


class ComputingEquipment(Equipment):
    """Computing equipment extension of the shared equipment record."""

    EQUIPMENT_CATEGORY_KEY = "computing"

    # Reported by the monitoring agent; not collected manually.
    hostname = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="DNS name used for remote access; falls back to the SKU when empty.",
    )
    mac_address = models.CharField(max_length=17, blank=True, default="", validators=[MAC_ADDRESS_VALIDATOR])
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    os_name = models.CharField(max_length=255, blank=True, default="")
    disk_usage = models.JSONField(default=list, blank=True)
    system_info = models.JSONField(default=dict, blank=True)
    monitored_devices = models.JSONField(default=dict, blank=True)
    rdp_file = models.FileField(upload_to="rdp_file/", null=True, blank=True)
    technical_user = models.ForeignKey(
        "labs.TechnicalUser",
        related_name="computing_equipment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    @property
    def rdp_host(self) -> str:
        """Host name written into the .rdp file (hostname, else the SKU)."""
        return (self.hostname or self.sku or "").strip()

    @property
    def computer_name(self) -> str:
        return self.name

    @computer_name.setter
    def computer_name(self, value: str) -> None:
        self.name = value

    @property
    def computer_ip(self):
        return self.ip_address

    @computer_ip.setter
    def computer_ip(self, value) -> None:
        self.ip_address = value

    @property
    def sys_info(self) -> dict:
        return self.system_info

    @sys_info.setter
    def sys_info(self, value: dict) -> None:
        self.system_info = value

    @property
    def monitoring(self) -> dict:
        return self.monitored_devices

    @monitoring.setter
    def monitoring(self, value: dict) -> None:
        self.monitored_devices = value

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        if "sku" in field_names:
            instance._initial_sku = values[field_names.index("sku")]
        if "hostname" in field_names:
            instance._initial_hostname = values[field_names.index("hostname")]
        if "technical_user" in field_names:
            instance._initial_technical_user_id = values[field_names.index("technical_user")]
        elif "technical_user_id" in field_names:
            instance._initial_technical_user_id = values[field_names.index("technical_user_id")]
        return instance

    def generate_rdp_file(self, *, commit: bool = False) -> None:
        """Generate and attach an in-memory .rdp file using the computing SKU and technical user."""
        if not self.rdp_host:
            return

        from core.infrastructure.remote_access.rdp_file import create_rdp_file

        if self.rdp_file and self.rdp_file.name:
            try:
                self.rdp_file.delete(save=False)
            except Exception:
                pass

        file_name = f"{self.sku}.rdp"
        temp_file = create_rdp_file(self.rdp_host, self.technical_user)
        self.rdp_file.save(file_name, ContentFile(temp_file.getvalue()), save=commit)

    def save(self, *args, **kwargs) -> None:
        self.sku = self.sku.strip() if self.sku else ""
        update_fields = kwargs.get("update_fields")

        should_generate = False
        if not self.rdp_file:
            should_generate = True
        elif getattr(self, "_state", None) and self._state.adding:
            should_generate = True
        elif hasattr(self, "_initial_sku") and self._initial_sku != self.sku:
            should_generate = True
        elif hasattr(self, "_initial_hostname") and self._initial_hostname != self.hostname:
            should_generate = True
        elif hasattr(self, "_initial_technical_user_id") and self._initial_technical_user_id != self.technical_user_id:
            should_generate = True

        if should_generate and self.sku:
            is_partial_update = update_fields is not None
            touches_relevant_fields = is_partial_update and bool(
                {"sku", "hostname", "technical_user", "technical_user_id"} & set(update_fields)
            )
            if not is_partial_update or touches_relevant_fields or not self.rdp_file:
                self.generate_rdp_file(commit=False)
                if update_fields is not None and "rdp_file" not in update_fields:
                    kwargs["update_fields"] = set(update_fields) | {"rdp_file"}
                self._initial_sku = self.sku
                self._initial_hostname = self.hostname
                self._initial_technical_user_id = self.technical_user_id

        super().save(*args, **kwargs)

    def hard_delete(self, using: str | None = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        """Permanently delete this row and clean up its associated RDP file from storage."""
        if self.rdp_file and self.rdp_file.name:
            try:
                self.rdp_file.delete(save=False)
            except Exception:
                pass
        return super().hard_delete(using=using, keep_parents=keep_parents)

    class Meta:
        app_label = "labs"
        indexes = [
            GinIndex(
                fields=("os_name",),
                opclasses=("gin_trgm_ops",),
                name="computing_os_name_idx",
            ),
        ]
