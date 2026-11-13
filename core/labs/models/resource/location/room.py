from decimal import Decimal

from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from model_utils.models import TimeStampedModel

from core.common.models import UserStampedModel
from core.labs.models.resource.base.resource import ResourceModel, ResourceStatusRecordModel
from core.labs.models.resource.location.physical_location import PhysicalLocationNode


class Country(TimeStampedModel, UserStampedModel):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        app_label = "labs"
        verbose_name_plural = "Countries"


class City(TimeStampedModel, UserStampedModel):
    """A city inside a country. The same name may exist in different countries."""

    name = models.CharField(max_length=100)
    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cities",
    )

    def __str__(self):
        return self.name

    class Meta:
        app_label = "labs"
        verbose_name_plural = "Cities"
        ordering = ("country__code", "name")
        constraints = [
            models.UniqueConstraint(fields=("country", "name"), name="city_country_name_uniq"),
            models.UniqueConstraint(
                fields=("name",),
                condition=models.Q(country__isnull=True),
                name="city_name_without_country_uniq",
            ),
        ]
        indexes = [
            GinIndex(fields=("name",), opclasses=["gin_trgm_ops"], name="city_name_trgm_idx"),
        ]


class Building(TimeStampedModel, UserStampedModel):
    """A building inside a city."""

    name = models.CharField(max_length=100)
    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="buildings",
    )
    address = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return self.name

    class Meta:
        app_label = "labs"
        ordering = ("city__name", "name")
        constraints = [
            models.UniqueConstraint(fields=("city", "name"), name="building_city_name_uniq"),
            models.UniqueConstraint(
                fields=("name",),
                condition=models.Q(city__isnull=True),
                name="building_name_without_city_uniq",
            ),
        ]
        indexes = [
            GinIndex(fields=("name",), opclasses=["gin_trgm_ops"], name="building_name_trgm_idx"),
        ]


class RoomStatus(models.TextChoices):
    AVAILABLE = "available", _("Available")
    RESERVED = "reserved", _("Reserved")
    ISSUE = "issue", _("Issue")
    RESTRICTED = "restricted", _("Restricted")
    CLOSED = "closed", _("Closed")
    MAINTENANCE = "maintenance", _("Maintenance")
    RETIRED = "retired", _("Retired")


class Room(ResourceModel, PhysicalLocationNode):
    """Static room configuration, separate from timestamped RoomObservation data.

    ResourceModel owns identity, ownership, images, remarks and soft deletion.
    """

    IMAGE_UPLOAD_FOLDER = "room"

    map_url = models.URLField(max_length=500, blank=True, default="")
    length_m = models.DecimalField(
        max_digits=9,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
        null=True,
        blank=True,
    )
    width_m = models.DecimalField(
        max_digits=9,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
        null=True,
        blank=True,
    )
    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rooms",
    )
    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rooms",
    )
    building = models.ForeignKey(
        Building,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rooms",
    )
    floor = models.CharField(max_length=50, blank=True, default="")
    layout_rows = models.PositiveIntegerField(validators=[MinValueValidator(1)], null=True, blank=True)
    layout_columns = models.PositiveIntegerField(validators=[MinValueValidator(1)], null=True, blank=True)
    usable_height_m = models.DecimalField(
        max_digits=9,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
        null=True,
        blank=True,
    )
    coordinate_unit = models.CharField(max_length=8, default="mm", editable=False)
    floor_plan_revision = models.CharField(max_length=64, blank=True, default="")
    floor_plan_url = models.URLField(max_length=500, blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=RoomStatus.choices,
        default=RoomStatus.AVAILABLE,
        db_index=True,
        help_text="Current lifecycle status. Changed only by the record status command; history is in status_records.",
    )
    max_occupancy = models.PositiveSmallIntegerField(null=True, blank=True)
    power_capacity_w = models.PositiveIntegerField(null=True, blank=True)
    cooling_capacity_w = models.PositiveIntegerField(null=True, blank=True)
    network_port_capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    utilities = models.JSONField(default=dict, blank=True)

    @property
    def area_m2(self) -> Decimal | None:
        """Return floor area in square metres when both dimensions are known."""
        if self.length_m is None or self.width_m is None:
            return None
        return Decimal(str(self.length_m)) * Decimal(str(self.width_m))

    @property
    def slot_capacity(self) -> int | None:
        """Derive capacity from the grid rather than storing a second value."""
        if self.layout_rows is None or self.layout_columns is None:
            return None
        return self.layout_rows * self.layout_columns

    def clean(self) -> None:
        super().clean()
        self.floor_plan_revision = self.floor_plan_revision.strip()
        if (self.layout_rows is None) != (self.layout_columns is None):
            missing = "layout_rows" if self.layout_rows is None else "layout_columns"
            raise ValidationError({missing: "Layout rows and columns must be provided together."})
        self._sync_location_hierarchy()

    def _sync_location_hierarchy(self) -> None:
        """Keep country > city > building consistent (derive upwards from the building)."""
        if self.building_id and self.building.city_id:
            city = self.building.city
            if self.city_id and self.city_id != city.pk:
                raise ValidationError({"building": "The building is not in the selected city."})
            self.city = city
        if self.city_id and self.city.country_id:
            country = self.city.country
            if self.country_id and self.country_id != country.pk:
                raise ValidationError({"city": "The city is not in the selected country."})
            self.country = country

    def get_location_parent(self) -> None:
        return None

    def get_location_segment(self) -> str | None:
        """Return this room's geographic and local identifier."""
        parts = (
            self.country.code if self.country else None,
            self.city.name if self.city else None,
            self.building.name if self.building else None,
            f"{self.floor}F" if self.floor else None,
            super().get_location_segment(),
        )
        return self.LOCATION_SEPARATOR.join(part for part in parts if part) or None

    def __str__(self) -> str:
        return self.get_location_segment() or "Unnamed room"

    class Meta:
        app_label = "labs"
        ordering = ("sku",)
        constraints = [
            *ResourceModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(status__in=RoomStatus.values),
                name="room_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(layout_rows__isnull=True, layout_columns__isnull=True)
                    | models.Q(
                        layout_rows__isnull=False,
                        layout_columns__isnull=False,
                        layout_rows__gt=0,
                        layout_columns__gt=0,
                    )
                ),
                name="room_layout_positive_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(length_m__isnull=True) | models.Q(length_m__gt=0),
                name="room_length_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(width_m__isnull=True) | models.Q(width_m__gt=0),
                name="room_width_positive",
            ),
        ]


class RoomStatusRecord(ResourceStatusRecordModel):
    room = models.ForeignKey(
        "labs.Room",
        related_name="status_records",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        max_length=255,
        choices=RoomStatus.choices,
    )

    class Meta:
        app_label = "labs"
        ordering = ("-created", "-id")
        indexes = [
            models.Index(fields=("room", "-created", "-id"), name="room_status_latest_idx"),
        ]
