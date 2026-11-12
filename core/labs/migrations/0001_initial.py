"""Initial Labs schema (squashed 2026-11-12; the database had not reached production).

Hand-written parts: the pg_trgm and btree_gist extensions (trigram indexes, booking exclusion
constraints) and the four default purchase priorities.
"""

import uuid
from decimal import Decimal

import django.contrib.postgres.constraints
import django.contrib.postgres.fields
import django.contrib.postgres.fields.ranges
import django.contrib.postgres.indexes
import django.core.validators
import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
import model_utils.fields
from django.conf import settings
from django.contrib.postgres.operations import BtreeGistExtension, TrigramExtension
from django.db import migrations, models

import core.infrastructure.storage.uploads
import core.labs.models.booking.base
import core.labs.models.finance.billing


class SafeTrigramExtension(TrigramExtension):
    """Create pg_trgm when the database role may; an existing extension is enough otherwise."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        try:
            super().database_forwards(app_label, schema_editor, from_state, to_state)
        except Exception:
            pass


PURCHASE_PRIORITIES = (("low", "Low", 10), ("normal", "Normal", 20), ("high", "High", 30), ("urgent", "Urgent", 40))


def seed_purchase_priorities(apps, schema_editor):
    PurchasePriority = apps.get_model("labs", "PurchasePriority")
    manager = PurchasePriority.objects.using(schema_editor.connection.alias)
    for code, name, rank in PURCHASE_PRIORITIES:
        manager.get_or_create(code=code, defaults={"name": name, "rank": rank, "is_active": True})


def unseed_purchase_priorities(apps, schema_editor):
    PurchasePriority = apps.get_model("labs", "PurchasePriority")
    PurchasePriority.objects.using(schema_editor.connection.alias).filter(
        code__in=[code for code, _, _ in PURCHASE_PRIORITIES]
    ).delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        SafeTrigramExtension(),
        BtreeGistExtension(),
        migrations.CreateModel(
            name="Equipment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "uid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("sku", models.CharField(max_length=255)),
                (
                    "name",
                    models.CharField(blank=True, db_index=True, default="", max_length=255),
                ),
                ("remark", models.CharField(blank=True, default="", max_length=255)),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to=core.infrastructure.storage.uploads.ResourceImageUploadPath(),
                    ),
                ),
                (
                    "serial_number",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "firmware_version",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Firmware currently installed on this unit.",
                        max_length=255,
                    ),
                ),
                (
                    "log_label",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Label that already existed on the asset before it was registered.",
                        max_length=255,
                        verbose_name="previous / legacy label",
                    ),
                ),
                ("details", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "replacement_date",
                    models.DateField(
                        blank=True,
                        help_text="Planned date when the equipment should be replaced.",
                        null=True,
                    ),
                ),
                ("warranty_until", models.DateField(blank=True, null=True)),
                (
                    "power_draw_w",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Nameplate power consumption in watts.",
                        null=True,
                    ),
                ),
                (
                    "weight_kg",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=8,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "calibration_required",
                    models.BooleanField(
                        default=False,
                        help_text="History and due dates are kept as ResourceServiceRecord (kind=calibration).",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_owned_resources",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Department",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("active", models.BooleanField(db_index=True, default=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="AccessoryEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="ComputingEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
                (
                    "hostname",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="DNS name used for remote access; falls back to the SKU when empty.",
                        max_length=255,
                    ),
                ),
                (
                    "mac_address",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=17,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="Enter a MAC address like AA:BB:CC:DD:EE:FF.",
                                regex="^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$",
                            )
                        ],
                    ),
                ),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("os_name", models.CharField(blank=True, default="", max_length=255)),
                ("disk_usage", models.JSONField(blank=True, default=list)),
                ("system_info", models.JSONField(blank=True, default=dict)),
                ("monitored_devices", models.JSONField(blank=True, default=dict)),
                (
                    "rdp_file",
                    models.FileField(blank=True, null=True, upload_to="rdp_file/"),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="DebuggingEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="LaboratoryEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="OtherEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="ActiveLaboratoryObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "period_start",
                    models.DateTimeField(help_text="Inclusive start of the interval represented by this observation."),
                ),
                (
                    "period_end",
                    models.DateTimeField(help_text="Exclusive end of the interval represented by this observation."),
                ),
                (
                    "granularity",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                            ("ad_hoc", "Ad hoc"),
                        ],
                        default="daily",
                        max_length=16,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="application",
                        max_length=16,
                    ),
                ),
                (
                    "recorded_at",
                    models.DateTimeField(help_text="When this measurement was produced or ingested."),
                ),
                (
                    "active_laboratory_count",
                    models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0)]),
                ),
            ],
            options={
                "ordering": ("-period_start", "-recorded_at"),
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        fields=("period_start", "period_end", "granularity", "source"),
                        name="labs_active_lab_observation_period_source_uniq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ActiveUserObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "period_start",
                    models.DateTimeField(help_text="Inclusive start of the interval represented by this observation."),
                ),
                (
                    "period_end",
                    models.DateTimeField(help_text="Exclusive end of the interval represented by this observation."),
                ),
                (
                    "granularity",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                            ("ad_hoc", "Ad hoc"),
                        ],
                        default="daily",
                        max_length=16,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="application",
                        max_length=16,
                    ),
                ),
                (
                    "recorded_at",
                    models.DateTimeField(help_text="When this measurement was produced or ingested."),
                ),
                (
                    "active_user_count",
                    models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0)]),
                ),
            ],
            options={
                "ordering": ("-period_start", "-recorded_at"),
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        fields=("period_start", "period_end", "granularity", "source"),
                        name="labs_active_user_observation_period_source_uniq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Bench",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "uid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("sku", models.CharField(max_length=255)),
                (
                    "name",
                    models.CharField(blank=True, db_index=True, default="", max_length=255),
                ),
                ("remark", models.CharField(blank=True, default="", max_length=255)),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to=core.infrastructure.storage.uploads.ResourceImageUploadPath(),
                    ),
                ),
                ("description", models.TextField(blank=True, default="")),
                (
                    "documentation_url",
                    models.URLField(blank=True, default="", max_length=500),
                ),
                (
                    "lifecycle_status",
                    models.CharField(
                        choices=[
                            ("planned", "Planned"),
                            ("available", "Available"),
                            ("reserved", "Reserved"),
                            ("active", "Active"),
                            ("maintenance", "Maintenance"),
                            ("out_of_service", "Out of service"),
                            ("retired", "Retired"),
                        ],
                        default="planned",
                        max_length=32,
                    ),
                ),
                (
                    "criticality",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "requested_power_w",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "requested_load_kg",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "requested_cooling_w",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("required_utilities", models.JSONField(blank=True, default=dict)),
                ("commissioning_date", models.DateField(blank=True, null=True)),
                ("last_inspected_at", models.DateTimeField(blank=True, null=True)),
                ("next_inspection_due_at", models.DateTimeField(blank=True, null=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_owned_resources",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("sku",),
            },
        ),
        migrations.CreateModel(
            name="BenchBooking",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "booking_code",
                    models.CharField(db_index=True, max_length=64, unique=True),
                ),
                ("starts_at", models.DateTimeField(db_index=True)),
                ("ends_at", models.DateTimeField(db_index=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("reserved", "Reserved"),
                            ("in_progress", "In progress"),
                            ("completed", "Completed"),
                            ("cancelled", "Cancelled"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="reserved",
                        max_length=32,
                    ),
                ),
                (
                    "approval_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="approved",
                        max_length=32,
                    ),
                ),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("rejection_reason", models.TextField(blank=True, default="")),
                ("reason", models.TextField(blank=True, default="")),
                ("cancellation_reason", models.TextField(blank=True, default="")),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_%(class)ss",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "bench",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bookings",
                        to="labs.bench",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "requester",
                    models.ForeignKey(
                        blank=True,
                        help_text="Who the booking is for. Defaults to the creator when empty (booking on behalf of someone else).",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_%(class)ss",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-starts_at", "-created"),
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="BenchGroup",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("active", models.BooleanField(db_index=True, default=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.AddField(
            model_name="bench",
            name="bench_group",
            field=models.ForeignKey(
                blank=True,
                help_text="Function of the bench (e.g. Radar, Video). The owning team is ResourceModel.group.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="benches",
                to="labs.benchgroup",
            ),
        ),
        migrations.CreateModel(
            name="BenchType",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("active", models.BooleanField(db_index=True, default=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.AddField(
            model_name="bench",
            name="type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="benches",
                to="labs.benchtype",
            ),
        ),
        migrations.CreateModel(
            name="BookingOutcomeObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "period_start",
                    models.DateTimeField(help_text="Inclusive start of the interval represented by this observation."),
                ),
                (
                    "period_end",
                    models.DateTimeField(help_text="Exclusive end of the interval represented by this observation."),
                ),
                (
                    "granularity",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                            ("ad_hoc", "Ad hoc"),
                        ],
                        default="daily",
                        max_length=16,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="application",
                        max_length=16,
                    ),
                ),
                (
                    "recorded_at",
                    models.DateTimeField(help_text="When this measurement was produced or ingested."),
                ),
                (
                    "resource_kind",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional resource category, such as equipment or bench.",
                        max_length=32,
                    ),
                ),
                (
                    "completed_count",
                    models.PositiveIntegerField(
                        default=0,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "cancelled_count",
                    models.PositiveIntegerField(
                        default=0,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "expired_count",
                    models.PositiveIntegerField(
                        default=0,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "rejected_count",
                    models.PositiveIntegerField(
                        default=0,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
            ],
            options={
                "ordering": ("-period_start", "-recorded_at"),
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "resource_kind",
                            "period_start",
                            "period_end",
                            "granularity",
                            "source",
                        ),
                        name="labs_booking_outcome_period_source_uniq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="BookingVolumeObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "period_start",
                    models.DateTimeField(help_text="Inclusive start of the interval represented by this observation."),
                ),
                (
                    "period_end",
                    models.DateTimeField(help_text="Exclusive end of the interval represented by this observation."),
                ),
                (
                    "granularity",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                            ("ad_hoc", "Ad hoc"),
                        ],
                        default="daily",
                        max_length=16,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="application",
                        max_length=16,
                    ),
                ),
                (
                    "recorded_at",
                    models.DateTimeField(help_text="When this measurement was produced or ingested."),
                ),
                (
                    "booking_count",
                    models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0)]),
                ),
            ],
            options={
                "ordering": ("-period_start", "-recorded_at"),
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        fields=("period_start", "period_end", "granularity", "source"),
                        name="labs_booking_volume_observation_period_source_uniq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="City",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "Cities",
                "ordering": ("country__code", "name"),
            },
        ),
        migrations.CreateModel(
            name="Building",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("address", models.CharField(blank=True, default="", max_length=255)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "city",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="buildings",
                        to="labs.city",
                    ),
                ),
            ],
            options={
                "ordering": ("city__name", "name"),
            },
        ),
        migrations.CreateModel(
            name="Country",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("code", models.CharField(max_length=10, unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "Countries",
            },
        ),
        migrations.AddField(
            model_name="city",
            name="country",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cities",
                to="labs.country",
            ),
        ),
        migrations.AddField(
            model_name="equipment",
            name="department",
            field=models.ForeignKey(
                blank=True,
                help_text="Owning department.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_department_resources",
                to="labs.department",
            ),
        ),
        migrations.AddField(
            model_name="bench",
            name="department",
            field=models.ForeignKey(
                blank=True,
                help_text="Owning department.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_department_resources",
                to="labs.department",
            ),
        ),
        migrations.CreateModel(
            name="DisplayResolution",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "resolution",
                    models.CharField(
                        help_text="Label shown in the select, e.g. QHD.",
                        max_length=255,
                        unique=True,
                    ),
                ),
                ("width_px", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("height_px", models.PositiveSmallIntegerField(blank=True, null=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("resolution",),
            },
        ),
        migrations.CreateModel(
            name="DisplaySize",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "size",
                    models.CharField(
                        help_text='Label shown in the select, e.g. 27".',
                        max_length=255,
                        unique=True,
                    ),
                ),
                (
                    "diagonal_in",
                    models.DecimalField(
                        blank=True,
                        decimal_places=1,
                        help_text="Diagonal in inches.",
                        max_digits=4,
                        null=True,
                        unique=True,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("size",),
            },
        ),
        migrations.CreateModel(
            name="EquipmentAssignment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("role", models.CharField(default="default", max_length=64)),
                (
                    "position",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Display order of this equipment assignment within the bench; lower values appear first.",
                    ),
                ),
                ("monitor", models.BooleanField(default=False)),
                ("assigned_at", models.DateTimeField()),
                ("unassigned_at", models.DateTimeField(blank=True, null=True)),
                (
                    "bench",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment_assignments",
                        to="labs.bench",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "equipment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bench_assignments",
                        to="labs.equipment",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="EquipmentBooking",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "booking_code",
                    models.CharField(db_index=True, max_length=64, unique=True),
                ),
                ("starts_at", models.DateTimeField(db_index=True)),
                ("ends_at", models.DateTimeField(db_index=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("reserved", "Reserved"),
                            ("in_progress", "In progress"),
                            ("completed", "Completed"),
                            ("cancelled", "Cancelled"),
                            ("expired", "Expired"),
                        ],
                        db_index=True,
                        default="reserved",
                        max_length=32,
                    ),
                ),
                (
                    "approval_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="approved",
                        max_length=32,
                    ),
                ),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("rejection_reason", models.TextField(blank=True, default="")),
                ("reason", models.TextField(blank=True, default="")),
                ("cancellation_reason", models.TextField(blank=True, default="")),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_%(class)ss",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "equipment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bookings",
                        to="labs.equipment",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "requester",
                    models.ForeignKey(
                        blank=True,
                        help_text="Who the booking is for. Defaults to the creator when empty (booking on behalf of someone else).",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_%(class)ss",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-starts_at", "-created"),
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="BookingNotification",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("event_id", models.UUIDField()),
                ("dedupe_key", models.CharField(max_length=64, unique=True)),
                (
                    "channel",
                    models.CharField(choices=[("email", "Email"), ("teams", "Teams")], max_length=8),
                ),
                ("kind", models.CharField(max_length=16)),
                ("snapshot", models.JSONField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField()),
                (
                    "available_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("state", models.CharField(default="pending", max_length=12)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("lease_token", models.UUIDField(null=True)),
                ("lease_until", models.DateTimeField(null=True)),
                ("finished_at", models.DateTimeField(null=True)),
                ("outcome", models.CharField(blank=True, default="", max_length=32)),
                (
                    "booking",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="notifications",
                        to="labs.benchbooking",
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="booking_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "equipment_booking",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="notifications",
                        to="labs.equipmentbooking",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="EquipmentCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("name", models.CharField(max_length=120)),
                (
                    "key",
                    models.SlugField(
                        blank=True,
                        help_text="Stable code used by the code base (e.g. 'computing'). Filled from the name when empty. Renaming the category never changes it.",
                        max_length=32,
                        null=True,
                        unique=True,
                    ),
                ),
                ("definition", models.TextField()),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="EquipmentInterface",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="EquipmentKind",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("name", models.CharField(max_length=120)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="kinds",
                        to="labs.equipmentcategory",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("category__name", "name"),
            },
        ),
        migrations.AddField(
            model_name="equipment",
            name="kind",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="equipment",
                to="labs.equipmentkind",
            ),
        ),
        migrations.CreateModel(
            name="EquipmentManufacturer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("name", models.CharField(max_length=120)),
                (
                    "categories",
                    models.ManyToManyField(
                        blank=True,
                        related_name="manufacturers",
                        to="labs.equipmentcategory",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.AddField(
            model_name="equipment",
            name="manufacturer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_equipment",
                to="labs.equipmentmanufacturer",
            ),
        ),
        migrations.CreateModel(
            name="EquipmentProductModel",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("name", models.CharField(max_length=120)),
                (
                    "default_power_draw_w",
                    models.PositiveIntegerField(
                        blank=True,
                        help_text="Copied to new assets of this model when empty.",
                        null=True,
                    ),
                ),
                (
                    "default_weight_kg",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Copied to new assets of this model when empty.",
                        max_digits=8,
                        null=True,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "manufacturer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="product_models",
                        to="labs.equipmentmanufacturer",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.AddField(
            model_name="equipment",
            name="product_model",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_equipment",
                to="labs.equipmentproductmodel",
            ),
        ),
        migrations.CreateModel(
            name="EquipmentStatusRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("in_use", "In-use"),
                            ("available", "Available"),
                            ("in_storage", "In-storage"),
                            ("transferred", "Transferred"),
                            ("borrowed", "Borrowed"),
                            ("maintenance", "Maintenance"),
                            ("broken", "Broken"),
                            ("lost", "Lost"),
                            ("on_order", "On Order"),
                        ],
                        max_length=255,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "equipment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_records",
                        to="labs.equipment",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("-created", "-id"),
            },
        ),
        migrations.CreateModel(
            name="EquipmentType",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("name", models.CharField(max_length=120)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "kind",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="types",
                        to="labs.equipmentkind",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("kind__category__name", "kind__name", "name"),
            },
        ),
        migrations.AddField(
            model_name="equipmentproductmodel",
            name="equipment_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="product_models",
                to="labs.equipmenttype",
            ),
        ),
        migrations.AddField(
            model_name="equipment",
            name="type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_equipment",
                to="labs.equipmenttype",
            ),
        ),
        migrations.CreateModel(
            name="Expense",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("resource_id", models.PositiveBigIntegerField()),
                ("name", models.CharField(max_length=255)),
                (
                    "expense_type",
                    models.CharField(
                        choices=[
                            ("rent", "Rent"),
                            ("utilities", "Utilities"),
                            ("maintenance", "Maintenance"),
                            ("calibration", "Calibration"),
                            ("repair", "Repair"),
                            ("service_contract", "Service contract"),
                            ("license_fee", "License fee"),
                            ("insurance", "Insurance"),
                            ("service", "Service (legacy)"),
                            ("other", "Other"),
                        ],
                        max_length=20,
                    ),
                ),
                ("supplier", models.CharField(blank=True, default="", max_length=255)),
                ("reference", models.CharField(blank=True, default="", max_length=255)),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                (
                    "currency",
                    models.CharField(
                        default=core.labs.models.finance.billing.default_currency,
                        max_length=3,
                        validators=[core.labs.models.finance.billing.validate_currency_code],
                    ),
                ),
                (
                    "billing_period",
                    models.CharField(
                        choices=[
                            ("one_time", "One-time"),
                            ("monthly", "Monthly"),
                            ("quarterly", "Quarterly"),
                            ("annual", "Annual"),
                        ],
                        default="one_time",
                        max_length=20,
                    ),
                ),
                ("valid_from", models.DateField()),
                ("valid_until", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "resource_type",
                    models.ForeignKey(
                        limit_choices_to=models.Q(
                            ("app_label__in", {"labs"}),
                            (
                                "model__in",
                                {"bench", "equipment", "license", "room", "station"},
                            ),
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="expenses",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "ordering": ("-valid_from", "-id"),
            },
        ),
        migrations.CreateModel(
            name="ExpensePayment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "transaction_type",
                    models.CharField(
                        choices=[("payment", "Payment"), ("refund", "Refund")],
                        default="payment",
                        max_length=10,
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                ("paid_at", models.DateField()),
                ("reference", models.CharField(blank=True, default="", max_length=255)),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "expense",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="labs.expense",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("-paid_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="LaboratoryAvailabilityObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "period_start",
                    models.DateTimeField(help_text="Inclusive start of the interval represented by this observation."),
                ),
                (
                    "period_end",
                    models.DateTimeField(help_text="Exclusive end of the interval represented by this observation."),
                ),
                (
                    "granularity",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                            ("ad_hoc", "Ad hoc"),
                        ],
                        default="daily",
                        max_length=16,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="application",
                        max_length=16,
                    ),
                ),
                (
                    "recorded_at",
                    models.DateTimeField(help_text="When this measurement was produced or ingested."),
                ),
                (
                    "laboratory_identifier",
                    models.CharField(
                        help_text="Stable identifier supplied by the laboratory operations system.",
                        max_length=255,
                    ),
                ),
                (
                    "available_seconds",
                    models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(0)]),
                ),
                (
                    "unavailable_seconds",
                    models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(0)]),
                ),
            ],
            options={
                "ordering": ("-period_start", "-recorded_at"),
                "abstract": False,
                "indexes": [
                    models.Index(
                        fields=["laboratory_identifier", "period_start"],
                        name="lab_availability_lab_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "laboratory_identifier",
                            "period_start",
                            "period_end",
                            "granularity",
                            "source",
                        ),
                        name="labs_lab_availability_period_source_uniq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="LaboratoryVisitEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "occurred_at",
                    models.DateTimeField(help_text="Time at which the operational event occurred."),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="application",
                        max_length=16,
                    ),
                ),
                (
                    "external_reference",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional idempotency key from the source system.",
                        max_length=255,
                    ),
                ),
                (
                    "facility_identifier",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Stable identifier supplied by the laboratory access system.",
                        max_length=255,
                    ),
                ),
                (
                    "visitor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="laboratory_visit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-occurred_at", "-id"),
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="LabProject",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "project_name",
                    models.CharField(blank=True, db_index=True, default="", max_length=255),
                ),
                (
                    "code",
                    models.CharField(
                        blank=True,
                        help_text="Short unique project code, e.g. a cost-center number.",
                        max_length=50,
                        null=True,
                        unique=True,
                    ),
                ),
                ("starts_on", models.DateField(blank=True, null=True)),
                ("ends_on", models.DateField(blank=True, null=True)),
                ("active", models.BooleanField(db_index=True, default=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="owned_lab_projects",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("project_name",),
            },
        ),
        migrations.AddField(
            model_name="equipmentbooking",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)ss",
                to="labs.labproject",
            ),
        ),
        migrations.AddField(
            model_name="benchbooking",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)ss",
                to="labs.labproject",
            ),
        ),
        migrations.CreateModel(
            name="License",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "uid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("sku", models.CharField(max_length=255)),
                (
                    "name",
                    models.CharField(blank=True, db_index=True, default="", max_length=255),
                ),
                ("remark", models.CharField(blank=True, default="", max_length=255)),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to=core.infrastructure.storage.uploads.ResourceImageUploadPath(),
                    ),
                ),
                (
                    "max_version",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "identifier",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="License key or serial. Secret: never log or export it.",
                        max_length=255,
                    ),
                ),
                ("expiry_date", models.DateTimeField(blank=True, null=True)),
                (
                    "seats",
                    models.PositiveSmallIntegerField(
                        default=1,
                        help_text="How many assets may use the license at the same time.",
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "department",
                    models.ForeignKey(
                        blank=True,
                        help_text="Owning department.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_department_resources",
                        to="labs.department",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_owned_resources",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="LicenseAgreement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "price",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Amount charged per billing period.",
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                    ),
                ),
                (
                    "currency",
                    models.CharField(
                        default=core.labs.models.finance.billing.default_currency,
                        max_length=3,
                        validators=[core.labs.models.finance.billing.validate_currency_code],
                    ),
                ),
                (
                    "billing_period",
                    models.CharField(
                        choices=[
                            ("one_time", "One-time"),
                            ("monthly", "Monthly"),
                            ("quarterly", "Quarterly"),
                            ("annual", "Annual"),
                        ],
                        default="one_time",
                        max_length=20,
                    ),
                ),
                ("valid_from", models.DateField()),
                ("valid_until", models.DateField(blank=True, null=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "license",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="agreements",
                        to="labs.license",
                    ),
                ),
            ],
            options={
                "ordering": ("-valid_from", "-id"),
            },
        ),
        migrations.CreateModel(
            name="LicenseAssignment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "assigned_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("unassigned_at", models.DateTimeField(blank=True, null=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "equipment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="license_assignments",
                        to="labs.equipment",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "license",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="equipment_assignments",
                        to="labs.license",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="equipment",
            name="licenses",
            field=models.ManyToManyField(
                blank=True,
                related_name="equipment",
                through="labs.LicenseAssignment",
                to="labs.license",
            ),
        ),
        migrations.CreateModel(
            name="LicenseCategory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "License categories",
                "ordering": ("name",),
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="license",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="licenses",
                to="labs.licensecategory",
            ),
        ),
        migrations.CreateModel(
            name="LicensePayment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                    ),
                ),
                (
                    "currency",
                    models.CharField(
                        default=core.labs.models.finance.billing.default_currency,
                        max_length=3,
                        validators=[core.labs.models.finance.billing.validate_currency_code],
                    ),
                ),
                ("paid_at", models.DateField()),
                ("reference", models.CharField(blank=True, default="", max_length=255)),
                (
                    "agreement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="labs.licenseagreement",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("-paid_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="LicenseProduct",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="license",
            name="product",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="licenses",
                to="labs.licenseproduct",
            ),
        ),
        migrations.CreateModel(
            name="LicenseRestriction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="license",
            name="restriction",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="licenses",
                to="labs.licenserestriction",
            ),
        ),
        migrations.CreateModel(
            name="LicenseStatusRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("available", "Available"),
                            ("assigned", "Assigned"),
                            ("expired", "Expired"),
                            ("revoked", "Revoked"),
                            ("suspended", "Suspended"),
                        ],
                        max_length=255,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "license",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_records",
                        to="labs.license",
                    ),
                ),
            ],
            options={
                "ordering": ("-created", "-id"),
            },
        ),
        migrations.CreateModel(
            name="LicenseType",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="license",
            name="type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="licenses",
                to="labs.licensetype",
            ),
        ),
        migrations.CreateModel(
            name="LicenseVendor",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="licenseproduct",
            name="vendor",
            field=models.ForeignKey(
                blank=True,
                help_text="Vendor of the product; licenses must use the same vendor.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="products",
                to="labs.licensevendor",
            ),
        ),
        migrations.AddField(
            model_name="license",
            name="vendor",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="licenses",
                to="labs.licensevendor",
            ),
        ),
        migrations.CreateModel(
            name="Material",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="NetworkingProtocol",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=25, unique=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="ProjectUsageObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "period_start",
                    models.DateTimeField(help_text="Inclusive start of the interval represented by this observation."),
                ),
                (
                    "period_end",
                    models.DateTimeField(help_text="Exclusive end of the interval represented by this observation."),
                ),
                (
                    "granularity",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                            ("ad_hoc", "Ad hoc"),
                        ],
                        default="daily",
                        max_length=16,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="application",
                        max_length=16,
                    ),
                ),
                (
                    "recorded_at",
                    models.DateTimeField(help_text="When this measurement was produced or ingested."),
                ),
                (
                    "project_identifier",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Stable external project identifier retained after project removal.",
                        max_length=255,
                    ),
                ),
                (
                    "booking_count",
                    models.PositiveIntegerField(
                        default=0,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "booked_seconds",
                    models.PositiveBigIntegerField(
                        default=0,
                        validators=[django.core.validators.MinValueValidator(0)],
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="usage_observations",
                        to="labs.labproject",
                    ),
                ),
            ],
            options={
                "ordering": ("-period_start", "-recorded_at"),
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Purchase",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("supplier", models.CharField(max_length=255)),
                (
                    "purchase_order_number",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                ("purchase_date", models.DateField()),
                (
                    "currency",
                    models.CharField(
                        default=core.labs.models.finance.billing.default_currency,
                        help_text="ISO 4217 currency code.",
                        max_length=3,
                        validators=[core.labs.models.finance.billing.validate_currency_code],
                    ),
                ),
                (
                    "total_amount",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Agreed total purchase amount.",
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("ordered", "Ordered"),
                            ("received", "Received"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                ("version", models.PositiveIntegerField(default=1)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("-purchase_date", "-id"),
            },
        ),
        migrations.CreateModel(
            name="PurchaseAuditEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("item_id", models.PositiveBigIntegerField(blank=True, null=True)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("create", "Create"),
                            ("update", "Update"),
                            ("delete", "Delete"),
                        ],
                        max_length=8,
                    ),
                ),
                (
                    "credential_ref",
                    models.CharField(blank=True, max_length=128, null=True),
                ),
                ("request_id", models.CharField(max_length=128)),
                ("before", models.JSONField(blank=True, null=True)),
                ("after", models.JSONField(blank=True, null=True)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="purchase_audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "purchase",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_events",
                        to="labs.purchase",
                    ),
                ),
            ],
            options={
                "ordering": ("occurred_at", "id"),
            },
        ),
        migrations.CreateModel(
            name="PurchaseIdempotencyRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("credential_ref", models.CharField(max_length=128)),
                ("key", models.CharField(max_length=64)),
                ("method", models.CharField(max_length=8)),
                ("path", models.CharField(max_length=512)),
                ("body_hash", models.CharField(max_length=64)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("in_progress", "In progress"),
                            ("completed", "Completed"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "status_code",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                ("response_body", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
            ],
            options={
                "indexes": [models.Index(fields=["expires_at"], name="purchase_idempotency_exp_idx")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("credential_ref", "key"),
                        name="purchase_idempotency_cred_key_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("response_body__isnull", True),
                                ("state", "in_progress"),
                                ("status_code__isnull", True),
                            ),
                            models.Q(
                                ("response_body__isnull", False),
                                ("state", "completed"),
                                ("status_code__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="purchase_idempotency_state_result",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PurchaseItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("description", models.CharField(max_length=255)),
                (
                    "quantity",
                    models.PositiveIntegerField(
                        default=1,
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "unit_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                ("purpose", models.TextField(blank=True, null=True)),
                ("unit", models.CharField(blank=True, max_length=32, null=True)),
                ("version", models.PositiveIntegerField(default=1)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "purchase",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="items",
                        to="labs.purchase",
                    ),
                ),
            ],
            options={
                "ordering": ("id",),
            },
        ),
        migrations.CreateModel(
            name="PurchaseItemResource",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("resource_id", models.PositiveBigIntegerField()),
                (
                    "acquisition_price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "purchase_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="resource_allocations",
                        to="labs.purchaseitem",
                    ),
                ),
                (
                    "resource_type",
                    models.ForeignKey(
                        limit_choices_to=models.Q(
                            ("app_label__in", {"labs"}),
                            ("model__in", {"bench", "equipment", "license", "station"}),
                        ),
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="purchase_item_resources",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "ordering": ("id",),
            },
        ),
        migrations.CreateModel(
            name="PurchasePriority",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.SlugField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=64)),
                ("rank", models.PositiveSmallIntegerField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("-rank", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        name="purchasepriority_name_ci_uniq",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="purchaseitem",
            name="priority",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="purchase_items",
                to="labs.purchasepriority",
            ),
        ),
        migrations.CreateModel(
            name="PurchaseTransaction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "transaction_type",
                    models.CharField(
                        choices=[("payment", "Payment"), ("refund", "Refund")],
                        max_length=10,
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                ("settled_at", models.DateTimeField()),
                (
                    "reference",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Invoice, receipt, bank transaction, or refund reference.",
                        max_length=255,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "purchase",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transactions",
                        to="labs.purchase",
                    ),
                ),
            ],
            options={
                "ordering": ("-settled_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="ResourceAudit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("resource_object_id", models.CharField(max_length=64)),
                ("audited_at", models.DateTimeField()),
                (
                    "result",
                    models.CharField(
                        choices=[
                            ("PASS", "Pass"),
                            ("FAIL", "Fail"),
                            ("NOT_ASSESSED", "Not assessed"),
                        ],
                        max_length=12,
                    ),
                ),
                ("remarks", models.CharField(blank=True, default="", max_length=255)),
                (
                    "auditor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="resource_audits",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "resource_content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="resource_audits",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "ordering": ("-audited_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="ResourceChangeLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("resource_object_id", models.CharField(max_length=64)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("CREATE", "Create"),
                            ("UPDATE", "Update"),
                            ("DELETE", "Delete"),
                        ],
                        max_length=8,
                    ),
                ),
                (
                    "field_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("old_value", models.JSONField(blank=True, null=True)),
                ("new_value", models.JSONField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "resource_content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="resource_change_logs",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "ordering": ("-created", "-id"),
            },
        ),
        migrations.CreateModel(
            name="ResourceGroup",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                ("description", models.TextField(blank=True, default="")),
                ("active", models.BooleanField(db_index=True, default=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "department",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="groups",
                        to="labs.department",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.AddField(
            model_name="license",
            name="group",
            field=models.ForeignKey(
                blank=True,
                help_text="Owning team; must belong to the selected department.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_resources",
                to="labs.resourcegroup",
            ),
        ),
        migrations.AddField(
            model_name="equipment",
            name="group",
            field=models.ForeignKey(
                blank=True,
                help_text="Owning team; must belong to the selected department.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_resources",
                to="labs.resourcegroup",
            ),
        ),
        migrations.AddField(
            model_name="bench",
            name="group",
            field=models.ForeignKey(
                blank=True,
                help_text="Owning team; must belong to the selected department.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(app_label)s_%(class)s_resources",
                to="labs.resourcegroup",
            ),
        ),
        migrations.CreateModel(
            name="ResourceServiceRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("resource_object_id", models.CharField(max_length=64)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("calibration", "Calibration"),
                            ("inspection", "Inspection"),
                            ("maintenance", "Maintenance"),
                            ("safety_test", "Safety test"),
                        ],
                        max_length=16,
                    ),
                ),
                ("performed_at", models.DateTimeField()),
                ("next_due_at", models.DateTimeField(blank=True, null=True)),
                ("vendor", models.CharField(blank=True, default="", max_length=255)),
                (
                    "result",
                    models.CharField(
                        choices=[
                            ("pass", "Pass"),
                            ("fail", "Fail"),
                            ("adjusted", "Adjusted"),
                        ],
                        default="pass",
                        max_length=12,
                    ),
                ),
                (
                    "certificate_no",
                    models.CharField(blank=True, default="", max_length=100),
                ),
                (
                    "certificate",
                    models.FileField(blank=True, null=True, upload_to="service_certificates/"),
                ),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "performed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="performed_service_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "resource_content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="resource_service_records",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "ordering": ("-performed_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="ResourceUtilizationObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "period_start",
                    models.DateTimeField(help_text="Inclusive start of the interval represented by this observation."),
                ),
                (
                    "period_end",
                    models.DateTimeField(help_text="Exclusive end of the interval represented by this observation."),
                ),
                (
                    "granularity",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                            ("ad_hoc", "Ad hoc"),
                        ],
                        default="daily",
                        max_length=16,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="application",
                        max_length=16,
                    ),
                ),
                (
                    "recorded_at",
                    models.DateTimeField(help_text="When this measurement was produced or ingested."),
                ),
                (
                    "resource_identifier",
                    models.CharField(
                        help_text="Stable identifier supplied by the resource scheduling system.",
                        max_length=255,
                    ),
                ),
                (
                    "resource_kind",
                    models.CharField(
                        help_text="Resource category, such as equipment or bench.",
                        max_length=32,
                    ),
                ),
                (
                    "booked_seconds",
                    models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(0)]),
                ),
                (
                    "available_seconds",
                    models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(0)]),
                ),
            ],
            options={
                "ordering": ("-period_start", "-recorded_at"),
                "abstract": False,
                "indexes": [
                    models.Index(
                        fields=["resource_identifier", "period_start"],
                        name="utilization_identifier_idx",
                    ),
                    models.Index(
                        fields=["resource_kind", "period_start"],
                        name="utilization_kind_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("booked_seconds__lte", models.F("available_seconds"))),
                        name="labs_resource_utilization_booked_within_available",
                    ),
                    models.UniqueConstraint(
                        fields=(
                            "resource_identifier",
                            "resource_kind",
                            "period_start",
                            "period_end",
                            "granularity",
                            "source",
                        ),
                        name="labs_resource_utilization_period_source_uniq",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Room",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "uid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("sku", models.CharField(max_length=255)),
                (
                    "name",
                    models.CharField(blank=True, db_index=True, default="", max_length=255),
                ),
                ("remark", models.CharField(blank=True, default="", max_length=255)),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to=core.infrastructure.storage.uploads.ResourceImageUploadPath(),
                    ),
                ),
                (
                    "label",
                    models.CharField(
                        blank=True,
                        help_text="Position within the parent location, e.g. R1C1 or U12.",
                        max_length=255,
                        null=True,
                    ),
                ),
                ("map_url", models.URLField(blank=True, default="", max_length=500)),
                (
                    "length_m",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=9,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                    ),
                ),
                (
                    "width_m",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=9,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                    ),
                ),
                ("floor", models.CharField(blank=True, default="", max_length=50)),
                (
                    "layout_rows",
                    models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "layout_columns",
                    models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "usable_height_m",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=9,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.001"))],
                    ),
                ),
                (
                    "coordinate_unit",
                    models.CharField(default="mm", editable=False, max_length=8),
                ),
                (
                    "floor_plan_revision",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "floor_plan_url",
                    models.URLField(blank=True, default="", max_length=500),
                ),
                (
                    "max_occupancy",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                (
                    "power_capacity_w",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "cooling_capacity_w",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "network_port_capacity",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                ("utilities", models.JSONField(blank=True, default=dict)),
                (
                    "building",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rooms",
                        to="labs.building",
                    ),
                ),
                (
                    "city",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rooms",
                        to="labs.city",
                    ),
                ),
                (
                    "country",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rooms",
                        to="labs.country",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "department",
                    models.ForeignKey(
                        blank=True,
                        help_text="Owning department.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_department_resources",
                        to="labs.department",
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        blank=True,
                        help_text="Owning team; must belong to the selected department.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_resources",
                        to="labs.resourcegroup",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_owned_resources",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("sku",),
            },
        ),
        migrations.AddField(
            model_name="equipment",
            name="storage_room",
            field=models.ForeignKey(
                blank=True,
                help_text="Where the asset is kept while it is In-storage.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stored_equipment",
                to="labs.room",
            ),
        ),
        migrations.CreateModel(
            name="RoomObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("observed_at", models.DateTimeField()),
                ("source", models.CharField(max_length=100)),
                (
                    "temperature_c",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=6,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(Decimal("-273.15"))],
                    ),
                ),
                (
                    "humidity_percent",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=5,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0")),
                            django.core.validators.MaxValueValidator(Decimal("100")),
                        ],
                    ),
                ),
                ("power_usage_w", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "room",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="observations",
                        to="labs.room",
                    ),
                ),
            ],
            options={
                "ordering": ("-observed_at", "-pk"),
            },
        ),
        migrations.CreateModel(
            name="RoomSlot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("row_index", models.PositiveIntegerField()),
                ("col_index", models.PositiveIntegerField()),
                ("slot_code", models.CharField(max_length=16)),
                (
                    "slot_type",
                    models.CharField(
                        choices=[
                            ("station", "Station"),
                            ("storage", "Storage"),
                            ("aisle", "Aisle"),
                            ("safety", "Safety"),
                            ("utility", "Utility"),
                            ("reserved", "Reserved"),
                        ],
                        default="station",
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("available", "Available"),
                            ("occupied", "Occupied"),
                            ("blocked", "Blocked"),
                            ("maintenance", "Maintenance"),
                            ("retired", "Retired"),
                        ],
                        default="available",
                        max_length=16,
                    ),
                ),
                ("x_mm", models.IntegerField(blank=True, null=True)),
                ("y_mm", models.IntegerField(blank=True, null=True)),
                ("width_mm", models.PositiveIntegerField(blank=True, null=True)),
                ("depth_mm", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "orientation_degrees",
                    models.PositiveSmallIntegerField(
                        default=0,
                        validators=[django.core.validators.MaxValueValidator(359)],
                    ),
                ),
                ("max_load_kg", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "power_capacity_w",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("utilities", models.JSONField(blank=True, default=dict)),
                ("is_accessible", models.BooleanField(default=False)),
                (
                    "clearance_width_mm",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "room",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="slots",
                        to="labs.room",
                    ),
                ),
            ],
            options={
                "ordering": ("room", "row_index", "col_index"),
            },
        ),
        migrations.CreateModel(
            name="RoomStatusRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("available", "Available"),
                            ("reserved", "Reserved"),
                            ("issue", "Issue"),
                            ("restricted", "Restricted"),
                            ("closed", "Closed"),
                            ("maintenance", "Maintenance"),
                            ("retired", "Retired"),
                        ],
                        max_length=255,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "room",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_records",
                        to="labs.room",
                    ),
                ),
            ],
            options={
                "ordering": ("-created", "-id"),
            },
        ),
        migrations.CreateModel(
            name="SampleCharacteristic",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="SampleCustomer",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="SpecificationDefinition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("name", models.CharField(max_length=120)),
                ("unit", models.CharField(blank=True, default="", max_length=20)),
                (
                    "value_type",
                    models.CharField(
                        choices=[
                            ("text", "Text"),
                            ("number", "Number"),
                            ("boolean", "Yes / No"),
                        ],
                        default="text",
                        max_length=10,
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        help_text="Category it mostly applies to; empty = any.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="specification_definitions",
                        to="labs.equipmentcategory",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("category__name", "name"),
            },
        ),
        migrations.CreateModel(
            name="ProductModelSpecification",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("value", models.CharField(max_length=255)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "product_model",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="specifications",
                        to="labs.equipmentproductmodel",
                    ),
                ),
                (
                    "definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="values",
                        to="labs.specificationdefinition",
                    ),
                ),
            ],
            options={
                "ordering": ("product_model", "definition__name"),
            },
        ),
        migrations.CreateModel(
            name="Station",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "uid",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("sku", models.CharField(max_length=255)),
                (
                    "name",
                    models.CharField(blank=True, db_index=True, default="", max_length=255),
                ),
                ("remark", models.CharField(blank=True, default="", max_length=255)),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to=core.infrastructure.storage.uploads.ResourceImageUploadPath(),
                    ),
                ),
                (
                    "label",
                    models.CharField(
                        blank=True,
                        help_text="Position within the parent location, e.g. R1C1 or U12.",
                        max_length=255,
                        null=True,
                    ),
                ),
                (
                    "position",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.FloatField(
                            validators=[
                                django.core.validators.MinValueValidator(-1000000.0),
                                django.core.validators.MaxValueValidator(1000000.0),
                            ]
                        ),
                        blank=True,
                        null=True,
                        size=3,
                    ),
                ),
                ("height_mm", models.PositiveIntegerField(blank=True, null=True)),
                ("width_mm", models.PositiveIntegerField(blank=True, null=True)),
                ("depth_mm", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "orientation_degrees",
                    models.PositiveSmallIntegerField(
                        default=0,
                        validators=[django.core.validators.MaxValueValidator(359)],
                    ),
                ),
                ("max_load_kg", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "bench_capacity",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                (
                    "max_concurrent_users",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                (
                    "usable_surface_mm2",
                    models.PositiveBigIntegerField(blank=True, null=True),
                ),
                (
                    "power_capacity_w",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("power_reserved_w", models.PositiveIntegerField(default=0)),
                (
                    "cooling_capacity_w",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "network_port_capacity",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                ("utilities", models.JSONField(blank=True, default=dict)),
                (
                    "safety_classification",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "department",
                    models.ForeignKey(
                        blank=True,
                        help_text="Owning department.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_department_resources",
                        to="labs.department",
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        blank=True,
                        help_text="Owning team; must belong to the selected department.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_resources",
                        to="labs.resourcegroup",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_owned_resources",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "room",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stations",
                        to="labs.room",
                    ),
                ),
                (
                    "slot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stations",
                        to="labs.roomslot",
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name="bench",
            name="setup_location",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="configured_benches",
                to="labs.station",
            ),
        ),
        migrations.CreateModel(
            name="StationSlot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("position_index", models.PositiveSmallIntegerField()),
                ("slot_code", models.CharField(max_length=32)),
                ("label", models.CharField(blank=True, default="", max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("available", "Available"),
                            ("occupied", "Occupied"),
                            ("reserved", "Reserved"),
                            ("maintenance", "Maintenance"),
                            ("out_of_service", "Out of service"),
                            ("retired", "Retired"),
                        ],
                        default="available",
                        max_length=32,
                    ),
                ),
                ("width_mm", models.PositiveIntegerField(blank=True, null=True)),
                ("depth_mm", models.PositiveIntegerField(blank=True, null=True)),
                ("height_mm", models.PositiveIntegerField(blank=True, null=True)),
                ("max_load_kg", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "power_capacity_w",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "network_port_count",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                ("utilities", models.JSONField(blank=True, default=dict)),
                (
                    "compatible_bench_types",
                    models.ManyToManyField(
                        blank=True,
                        related_name="compatible_station_slots",
                        to="labs.benchtype",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "station",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bench_slots",
                        to="labs.station",
                    ),
                ),
            ],
            options={
                "ordering": ("station", "position_index"),
            },
        ),
        migrations.AddField(
            model_name="bench",
            name="station_slot",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bench",
                to="labs.stationslot",
            ),
        ),
        migrations.CreateModel(
            name="StationStatusRecord",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("available", "Available"),
                            ("reserved", "Reserved"),
                            ("issue", "Issue"),
                            ("restricted", "Restricted"),
                            ("closed", "Closed"),
                            ("maintenance", "Maintenance"),
                            ("retired", "Retired"),
                        ],
                        max_length=255,
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "station",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_records",
                        to="labs.station",
                    ),
                ),
            ],
            options={
                "ordering": ("-created", "-id"),
            },
        ),
        migrations.CreateModel(
            name="StationType",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.AddField(
            model_name="station",
            name="type",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stations",
                to="labs.stationtype",
            ),
        ),
        migrations.CreateModel(
            name="StorageQuotaMeasurement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "measured_at",
                    models.DateTimeField(help_text="When storage capacity was measured."),
                ),
                ("account_identifier", models.CharField(max_length=255)),
                (
                    "account_display_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "computer_identifier",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Stable asset identifier supplied by the storage collector.",
                        max_length=255,
                    ),
                ),
                (
                    "used_gibibytes",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                    ),
                ),
                (
                    "quota_gibibytes",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="collector",
                        max_length=16,
                    ),
                ),
                (
                    "source_account_identifier",
                    models.CharField(blank=True, default="", max_length=255),
                ),
            ],
            options={
                "ordering": ("-measured_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["computer_identifier", "measured_at"],
                        name="storage_computer_at_idx",
                    ),
                    models.Index(
                        fields=["account_identifier", "measured_at"],
                        name="storage_account_at_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("used_gibibytes__gte", 0)),
                        name="labs_storage_measurement_used_nonnegative",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quota_gibibytes__gte", 0)),
                        name="labs_storage_measurement_quota_nonnegative",
                    ),
                    models.UniqueConstraint(
                        fields=(
                            "computer_identifier",
                            "account_identifier",
                            "measured_at",
                            "source",
                        ),
                        name="labs_storage_measurement_identity_uniq",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="TechnicalUser",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("username", models.CharField(max_length=255, unique=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="VisitorVolumeObservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "period_start",
                    models.DateTimeField(help_text="Inclusive start of the interval represented by this observation."),
                ),
                (
                    "period_end",
                    models.DateTimeField(help_text="Exclusive end of the interval represented by this observation."),
                ),
                (
                    "granularity",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                            ("ad_hoc", "Ad hoc"),
                        ],
                        default="daily",
                        max_length=16,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("application", "Application"),
                            ("collector", "Collector"),
                            ("import", "Import"),
                            ("manual", "Manual"),
                        ],
                        default="application",
                        max_length=16,
                    ),
                ),
                (
                    "recorded_at",
                    models.DateTimeField(help_text="When this measurement was produced or ingested."),
                ),
                (
                    "distinct_visitor_count",
                    models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(0)]),
                ),
            ],
            options={
                "ordering": ("-period_start", "-recorded_at"),
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        fields=("period_start", "period_end", "granularity", "source"),
                        name="labs_visitor_volume_observation_period_source_uniq",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="MonitoringEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("agent_id", models.CharField(max_length=128)),
                (
                    "agent_version",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("event_id", models.UUIDField()),
                (
                    "reported_at",
                    models.DateTimeField(help_text="Timestamp at which the agent emitted the report."),
                ),
                ("occurred_at", models.DateTimeField()),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("heartbeat", "Heartbeat"),
                            ("device_inserted", "Device inserted"),
                            ("device_removed", "Device removed"),
                            ("device_changed", "Device changed"),
                            ("device_status_changed", "Device status changed"),
                            ("inventory_snapshot", "Inventory snapshot"),
                            ("metric_reported", "Metric reported"),
                            ("alert_raised", "Alert raised"),
                            ("alert_resolved", "Alert resolved"),
                            ("custom", "Custom"),
                        ],
                        max_length=64,
                    ),
                ),
                (
                    "action_name",
                    models.CharField(blank=True, default="", max_length=128),
                ),
                (
                    "subject_type",
                    models.CharField(blank=True, default="", max_length=128),
                ),
                (
                    "subject_id",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "subject_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "computer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="monitoring_events",
                        to="labs.computingequipment",
                    ),
                ),
            ],
            options={
                "ordering": ("-occurred_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="LabSessionLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                ("agent_id", models.CharField(max_length=128)),
                (
                    "agent_version",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("event_id", models.UUIDField()),
                (
                    "reported_at",
                    models.DateTimeField(help_text="Timestamp at which the agent emitted the report."),
                ),
                ("login_time", models.DateTimeField(blank=True, null=True)),
                ("logout_time", models.DateTimeField(blank=True, null=True)),
                ("host_name", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "remote_host",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    "remote_user",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    "remote_user_display_name",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("remote_ip", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "booking_code",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("active_duration_seconds", models.FloatField(blank=True, null=True)),
                (
                    "creator",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_creator",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created by",
                    ),
                ),
                (
                    "last_modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_last_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Last modified by",
                    ),
                ),
                (
                    "computing_equipment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="session_logs",
                        to="labs.computingequipment",
                    ),
                ),
            ],
            options={
                "verbose_name": "Lab session log",
                "verbose_name_plural": "Lab session logs",
                "ordering": ("-login_time", "-created"),
            },
        ),
        migrations.AddField(
            model_name="computingequipment",
            name="technical_user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="computing_equipment",
                to="labs.technicaluser",
            ),
        ),
        migrations.CreateModel(
            name="ComputingActivity",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("offline", "Offline"),
                            ("free", "Free"),
                            ("active", "Active"),
                            ("inactive", "Inactive"),
                            ("maintaining", "Maintaining"),
                        ],
                        db_index=True,
                        default="offline",
                        max_length=16,
                    ),
                ),
                (
                    "remote_user",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "remote_user_display_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "remote_computer",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("remote_ip", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "booking_code",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("last_agent_report_at", models.DateTimeField(blank=True, null=True)),
                ("offline_at", models.DateTimeField(blank=True, null=True)),
                ("inactive_at", models.DateTimeField(blank=True, null=True)),
                ("inactive_reminder_count", models.PositiveIntegerField(default=0)),
                (
                    "computing",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activity",
                        to="labs.computingequipment",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DisplayEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
                (
                    "interfaces",
                    models.ManyToManyField(
                        blank=True,
                        related_name="%(app_label)s_%(class)s_interfaces",
                        to="labs.equipmentinterface",
                    ),
                ),
                (
                    "resolution",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_resolution",
                        to="labs.displayresolution",
                    ),
                ),
                (
                    "size",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_size",
                        to="labs.displaysize",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="FurnitureEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
                (
                    "dimensions",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Keys length_mm, width_mm, height_mm.",
                    ),
                ),
                (
                    "material",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_material",
                        to="labs.material",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="InstrumentEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
                (
                    "interfaces",
                    models.ManyToManyField(
                        blank=True,
                        related_name="%(app_label)s_%(class)s_instruments",
                        to="labs.equipmentinterface",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="MechanicalEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
                (
                    "dimensions",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Keys length_mm, width_mm, height_mm.",
                    ),
                ),
                (
                    "material",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_material",
                        to="labs.material",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="NetworkingEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
                (
                    "mac_address",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=17,
                        validators=[
                            django.core.validators.RegexValidator(
                                message="Enter a MAC address like AA:BB:CC:DD:EE:FF.",
                                regex="^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$",
                            )
                        ],
                    ),
                ),
                (
                    "protocol",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_protocol",
                        to="labs.networkingprotocol",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="PowerEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
                ("channels", models.PositiveSmallIntegerField(blank=True, null=True)),
                (
                    "power_rating",
                    models.PositiveIntegerField(blank=True, help_text="Output capacity in watts.", null=True),
                ),
                (
                    "interface",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_interface",
                        to="labs.equipmentinterface",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="SampleEquipment",
            fields=[
                (
                    "equipment_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="labs.equipment",
                    ),
                ),
                (
                    "characteristics",
                    models.ManyToManyField(
                        blank=True,
                        related_name="%(app_label)s_%(class)s_characteristics",
                        to="labs.samplecharacteristic",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="%(app_label)s_%(class)s_customer",
                        to="labs.samplecustomer",
                    ),
                ),
                (
                    "interfaces",
                    models.ManyToManyField(
                        blank=True,
                        related_name="%(app_label)s_%(class)s_interfaces",
                        to="labs.equipmentinterface",
                    ),
                ),
            ],
            bases=("labs.equipment",),
        ),
        migrations.CreateModel(
            name="BenchBookingDecisionReceipt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "operation",
                    models.CharField(
                        choices=[("approve", "Approve"), ("reject", "Reject")],
                        max_length=8,
                    ),
                ),
                ("key", models.CharField(max_length=36)),
                ("request_hash", models.CharField(max_length=64)),
                ("status_code", models.PositiveSmallIntegerField()),
                ("response_body", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bench_booking_decision_receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "booking",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="decision_receipts",
                        to="labs.benchbooking",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["expires_at"], name="bench_decision_receipt_exp_idx")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("actor", "operation", "booking", "key"),
                        name="bench_decision_actor_op_book_key_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("status_code__gte", 200), ("status_code__lt", 300)),
                        name="bench_decision_receipt_success_only",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("expires_at__gt", models.F("created_at"))),
                        name="bench_decision_receipt_expiry_valid",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BenchFavorite",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "bench",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="favorited_by",
                        to="labs.bench",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bench_favorites",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Bench Favorite",
                "verbose_name_plural": "Bench Favorites",
                "ordering": ("-created", "-pk"),
                "constraints": [
                    models.UniqueConstraint(fields=("user", "bench"), name="bench_favorite_user_bench_uniq")
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="benchgroup",
            constraint=models.CheckConstraint(
                condition=models.Q(("name", ""), _negated=True),
                name="bench_group_name_not_empty",
            ),
        ),
        migrations.AddConstraint(
            model_name="benchtype",
            constraint=models.CheckConstraint(
                condition=models.Q(("name", ""), _negated=True),
                name="bench_type_name_not_empty",
            ),
        ),
        migrations.AddIndex(
            model_name="building",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="building_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddConstraint(
            model_name="building",
            constraint=models.UniqueConstraint(fields=("city", "name"), name="building_city_name_uniq"),
        ),
        migrations.AddConstraint(
            model_name="building",
            constraint=models.UniqueConstraint(
                condition=models.Q(("city__isnull", True)),
                fields=("name",),
                name="building_name_without_city_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="city",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"], name="city_name_trgm_idx", opclasses=["gin_trgm_ops"]
            ),
        ),
        migrations.AddConstraint(
            model_name="city",
            constraint=models.UniqueConstraint(fields=("country", "name"), name="city_country_name_uniq"),
        ),
        migrations.AddConstraint(
            model_name="city",
            constraint=models.UniqueConstraint(
                condition=models.Q(("country__isnull", True)),
                fields=("name",),
                name="city_name_without_country_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="department",
            constraint=models.CheckConstraint(
                condition=models.Q(("name", ""), _negated=True),
                name="department_name_not_empty",
            ),
        ),
        migrations.AddIndex(
            model_name="displayresolution",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["resolution"],
                name="display_resolution_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddConstraint(
            model_name="displayresolution",
            constraint=models.UniqueConstraint(
                condition=models.Q(("height_px__isnull", False), ("width_px__isnull", False)),
                fields=("width_px", "height_px"),
                name="display_resolution_pixels_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="displaysize",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["size"], name="display_size_idx", opclasses=("gin_trgm_ops",)
            ),
        ),
        migrations.AddIndex(
            model_name="equipmentassignment",
            index=models.Index(
                condition=models.Q(("unassigned_at__isnull", True)),
                fields=["bench", "position"],
                name="equipment_assign_bench_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("unassigned_at__isnull", True)),
                fields=("equipment",),
                name="one_active_bench_per_equipment",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentassignment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("unassigned_at__isnull", True),
                    ("unassigned_at__gte", models.F("assigned_at")),
                    _connector="OR",
                ),
                name="assignment_end_after_start",
            ),
        ),
        migrations.AddIndex(
            model_name="bookingnotification",
            index=models.Index(fields=["state", "available_at"], name="booking_notice_ready_idx"),
        ),
        migrations.AddConstraint(
            model_name="bookingnotification",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("booking__isnull", False), ("equipment_booking__isnull", True)),
                    models.Q(("booking__isnull", True), ("equipment_booking__isnull", False)),
                    _connector="OR",
                ),
                name="booking_notice_one_booking",
            ),
        ),
        migrations.AddConstraint(
            model_name="bookingnotification",
            constraint=models.CheckConstraint(
                condition=models.Q(("channel__in", ("email", "teams"))),
                name="booking_notice_channel",
            ),
        ),
        migrations.AddConstraint(
            model_name="bookingnotification",
            constraint=models.CheckConstraint(
                condition=models.Q(("kind__in", ("created", "updated", "start", "inactive"))),
                name="booking_notice_kind",
            ),
        ),
        migrations.AddConstraint(
            model_name="bookingnotification",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "state__in",
                        ("pending", "leased", "sent", "failed", "skipped", "expired"),
                    )
                ),
                name="booking_notice_state",
            ),
        ),
        migrations.AddConstraint(
            model_name="bookingnotification",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("lease_token__isnull", False),
                        ("lease_until__isnull", False),
                        ("state", "leased"),
                    ),
                    models.Q(
                        models.Q(("state", "leased"), _negated=True),
                        ("lease_token__isnull", True),
                        ("lease_until__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="booking_notice_lease",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentcategory",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="equipment_category_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="equipmentinterface",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="equipment_interface_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentkind",
            constraint=models.UniqueConstraint(
                models.F("category"),
                django.db.models.functions.text.Lower("name"),
                name="equipment_kind_category_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="equipmentmanufacturer",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="equipment_mfr_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentmanufacturer",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="equipment_manufacturer_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="equipmentstatusrecord",
            index=models.Index(
                fields=["equipment", "-created", "-id"],
                name="equipment_status_latest_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="equipmenttype",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="equipment_type_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmenttype",
            constraint=models.UniqueConstraint(
                models.F("kind"),
                django.db.models.functions.text.Lower("name"),
                name="equipment_type_kind_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="equipmentproductmodel",
            index=models.Index(
                fields=["equipment_type", "manufacturer"],
                name="labs_equipm_equipme_496c23_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="equipmentproductmodel",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="equipment_model_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentproductmodel",
            constraint=models.UniqueConstraint(
                models.F("manufacturer"),
                django.db.models.functions.text.Lower("name"),
                name="equipment_product_model_mfr_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["resource_type", "resource_id"], name="expense_resource_idx"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["resource_type", "expense_type"], name="expense_type_idx"),
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(
                fields=["currency", "billing_period"],
                name="expense_currency_period_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="expense",
            constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="expense_amount_positive"),
        ),
        migrations.AddConstraint(
            model_name="expense",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("valid_until__isnull", True),
                    ("valid_until__gte", models.F("valid_from")),
                    _connector="OR",
                ),
                name="expense_valid_dates",
            ),
        ),
        migrations.AddIndex(
            model_name="expensepayment",
            index=models.Index(fields=["expense", "paid_at"], name="expense_payment_date_idx"),
        ),
        migrations.AddIndex(
            model_name="expensepayment",
            index=models.Index(fields=["expense", "transaction_type"], name="expense_payment_type_idx"),
        ),
        migrations.AddConstraint(
            model_name="expensepayment",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gt", 0)),
                name="expense_payment_amount_positive",
            ),
        ),
        migrations.AddIndex(
            model_name="laboratoryvisitevent",
            index=models.Index(fields=["visitor", "occurred_at"], name="lab_visit_visitor_at_idx"),
        ),
        migrations.AddIndex(
            model_name="laboratoryvisitevent",
            index=models.Index(
                fields=["facility_identifier", "occurred_at"],
                name="lab_visit_facility_at_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="laboratoryvisitevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(("external_reference", ""), _negated=True),
                fields=("source", "external_reference"),
                name="labs_laboratoryvisitevent_source_reference_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="labproject",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["project_name"],
                name="lab_project_name_trgm_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddConstraint(
            model_name="labproject",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("project_name"),
                condition=models.Q(("project_name", ""), _negated=True),
                name="lab_project_name_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="labproject",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("starts_on__isnull", True),
                    ("ends_on__isnull", True),
                    ("ends_on__gte", models.F("starts_on")),
                    _connector="OR",
                ),
                name="lab_project_valid_dates",
            ),
        ),
        migrations.AddIndex(
            model_name="equipmentbooking",
            index=models.Index(
                fields=["equipment", "starts_at", "ends_at"],
                name="equipment_booking_schedule_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="equipmentbooking",
            index=models.Index(
                fields=["equipment", "status", "approval_status"],
                name="equipment_booking_state_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentbooking",
            constraint=models.CheckConstraint(
                condition=models.Q(("ends_at__gt", models.F("starts_at"))),
                name="labs_equipmentbooking_valid_booking_period",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentbooking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("approval_status", "rejected"), _negated=True),
                    models.Q(("rejection_reason__regex", "^\\s*$"), _negated=True),
                    _connector="OR",
                ),
                name="labs_equipmentbooking_rejection_has_reason",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentbooking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("approval_status", "pending"), _negated=True),
                    ("approved_by__isnull", True),
                    _connector="OR",
                ),
                name="labs_equipmentbooking_pending_has_no_approver",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentbooking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("status", "cancelled"), _negated=True),
                    models.Q(("cancellation_reason__regex", "^\\s*$"), _negated=True),
                    _connector="OR",
                ),
                name="labs_equipmentbooking_cancellation_has_reason",
            ),
        ),
        migrations.AddConstraint(
            model_name="equipmentbooking",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(
                    ("approval_status__in", ["pending", "approved"]),
                    ("status__in", ["reserved", "in_progress"]),
                ),
                expressions=[
                    ("equipment", "="),
                    (
                        core.labs.models.booking.base.TsTzRange(
                            "starts_at",
                            "ends_at",
                            django.contrib.postgres.fields.ranges.RangeBoundary(),
                        ),
                        "&&",
                    ),
                ],
                name="equipment_booking_no_overlap",
            ),
        ),
        migrations.AddIndex(
            model_name="benchbooking",
            index=models.Index(
                fields=["bench", "starts_at", "ends_at"],
                name="bench_booking_schedule_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="benchbooking",
            index=models.Index(
                fields=["bench", "status", "approval_status"],
                name="bench_booking_state_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="benchbooking",
            constraint=models.CheckConstraint(
                condition=models.Q(("ends_at__gt", models.F("starts_at"))),
                name="labs_benchbooking_valid_booking_period",
            ),
        ),
        migrations.AddConstraint(
            model_name="benchbooking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("approval_status", "rejected"), _negated=True),
                    models.Q(("rejection_reason__regex", "^\\s*$"), _negated=True),
                    _connector="OR",
                ),
                name="labs_benchbooking_rejection_has_reason",
            ),
        ),
        migrations.AddConstraint(
            model_name="benchbooking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("approval_status", "pending"), _negated=True),
                    ("approved_by__isnull", True),
                    _connector="OR",
                ),
                name="labs_benchbooking_pending_has_no_approver",
            ),
        ),
        migrations.AddConstraint(
            model_name="benchbooking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("status", "cancelled"), _negated=True),
                    models.Q(("cancellation_reason__regex", "^\\s*$"), _negated=True),
                    _connector="OR",
                ),
                name="labs_benchbooking_cancellation_has_reason",
            ),
        ),
        migrations.AddConstraint(
            model_name="benchbooking",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(
                    ("approval_status__in", ["pending", "approved"]),
                    ("status__in", ["reserved", "in_progress"]),
                ),
                expressions=[
                    ("bench", "="),
                    (
                        core.labs.models.booking.base.TsTzRange(
                            "starts_at",
                            "ends_at",
                            django.contrib.postgres.fields.ranges.RangeBoundary(),
                        ),
                        "&&",
                    ),
                ],
                name="bench_booking_no_overlap",
            ),
        ),
        migrations.AddIndex(
            model_name="licenseagreement",
            index=models.Index(fields=["license", "valid_from"], name="license_agreement_start_idx"),
        ),
        migrations.AddConstraint(
            model_name="licenseagreement",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("valid_until__isnull", True),
                    ("valid_until__gte", models.F("valid_from")),
                    _connector="OR",
                ),
                name="license_agreement_valid_dates",
            ),
        ),
        migrations.AddIndex(
            model_name="licenseassignment",
            index=models.Index(
                condition=models.Q(("unassigned_at__isnull", True)),
                fields=["license", "-assigned_at"],
                name="license_assign_license_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="licenseassignment",
            index=models.Index(
                condition=models.Q(("unassigned_at__isnull", True)),
                fields=["equipment", "-assigned_at"],
                name="license_assign_equipment_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="licenseassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("unassigned_at__isnull", True)),
                fields=("license", "equipment"),
                name="license_equipment_active_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="licenseassignment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("unassigned_at__isnull", True),
                    ("unassigned_at__gte", models.F("assigned_at")),
                    _connector="OR",
                ),
                name="license_assignment_end_after_start",
            ),
        ),
        migrations.AddIndex(
            model_name="licensecategory",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="license_category_name_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddConstraint(
            model_name="licensecategory",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="license_category_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="licensepayment",
            index=models.Index(fields=["paid_at"], name="license_payment_date_idx"),
        ),
        migrations.AddIndex(
            model_name="licenserestriction",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="license_restriction_name_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddConstraint(
            model_name="licenserestriction",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="license_restriction_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="licensestatusrecord",
            index=models.Index(fields=["license", "-created", "-id"], name="license_status_latest_idx"),
        ),
        migrations.AddIndex(
            model_name="licensetype",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="license_type_name_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddConstraint(
            model_name="licensetype",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="license_type_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="licensevendor",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="license_vendor_name_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddConstraint(
            model_name="licensevendor",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="license_vendor_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="licenseproduct",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="license_product_name_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddConstraint(
            model_name="licenseproduct",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="license_product_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="material",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"], name="material_name_idx", opclasses=("gin_trgm_ops",)
            ),
        ),
        migrations.AddIndex(
            model_name="networkingprotocol",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="networking_protocol_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddIndex(
            model_name="projectusageobservation",
            index=models.Index(fields=["project", "period_start"], name="project_usage_project_idx"),
        ),
        migrations.AddIndex(
            model_name="projectusageobservation",
            index=models.Index(
                fields=["project_identifier", "period_start"],
                name="project_usage_identifier_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="projectusageobservation",
            constraint=models.UniqueConstraint(
                fields=(
                    "project",
                    "project_identifier",
                    "period_start",
                    "period_end",
                    "granularity",
                    "source",
                ),
                name="labs_project_usage_period_source_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="purchase",
            index=models.Index(fields=["purchase_date"], name="purchase_date_idx"),
        ),
        migrations.AddIndex(
            model_name="purchase",
            index=models.Index(fields=["status", "purchase_date"], name="purchase_status_date_idx"),
        ),
        migrations.AddConstraint(
            model_name="purchase",
            constraint=models.CheckConstraint(
                condition=models.Q(("total_amount__gte", 0)),
                name="purchase_total_nonnegative",
            ),
        ),
        migrations.AddIndex(
            model_name="purchaseauditevent",
            index=models.Index(fields=["purchase", "occurred_at"], name="purchase_audit_time_idx"),
        ),
        migrations.AddIndex(
            model_name="purchaseitemresource",
            index=models.Index(
                fields=["resource_type", "resource_id"],
                name="purchase_item_resource_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseitemresource",
            constraint=models.UniqueConstraint(
                fields=("resource_type", "resource_id"), name="purchase_resource_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseitemresource",
            constraint=models.CheckConstraint(
                condition=models.Q(("acquisition_price__gte", 0)),
                name="purchase_item_resource_price_nonnegative",
            ),
        ),
        migrations.AddIndex(
            model_name="purchaseitem",
            index=models.Index(fields=["purchase"], name="purchase_item_purchase_idx"),
        ),
        migrations.AddConstraint(
            model_name="purchaseitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity__gte", 1)),
                name="purchase_item_quantity_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="purchaseitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("unit_price__gte", 0)),
                name="purchase_item_price_nonnegative",
            ),
        ),
        migrations.AddIndex(
            model_name="purchasetransaction",
            index=models.Index(fields=["purchase", "settled_at"], name="purchase_txn_purchase_idx"),
        ),
        migrations.AddIndex(
            model_name="purchasetransaction",
            index=models.Index(fields=["settled_at"], name="purchase_txn_settled_idx"),
        ),
        migrations.AddConstraint(
            model_name="purchasetransaction",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gt", 0)),
                name="purchase_txn_amount_positive",
            ),
        ),
        migrations.AddIndex(
            model_name="resourceaudit",
            index=models.Index(
                fields=["resource_content_type", "resource_object_id", "-audited_at"],
                name="resource_audit_latest_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="resourceaudit",
            index=models.Index(fields=["result", "-audited_at"], name="resource_audit_result_idx"),
        ),
        migrations.AddIndex(
            model_name="resourcechangelog",
            index=models.Index(
                fields=["resource_content_type", "resource_object_id", "-created"],
                name="resource_change_latest_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="resourcechangelog",
            index=models.Index(fields=["action", "-created"], name="resource_change_action_idx"),
        ),
        migrations.AddIndex(
            model_name="license",
            index=models.Index(fields=["product", "deleted_at"], name="license_product_deleted_idx"),
        ),
        migrations.AddIndex(
            model_name="license",
            index=models.Index(fields=["expiry_date"], name="license_expiry_idx"),
        ),
        migrations.AddConstraint(
            model_name="license",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("sku",),
                name="labs_license_active_sku_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="resourceservicerecord",
            index=models.Index(
                fields=[
                    "resource_content_type",
                    "resource_object_id",
                    "kind",
                    "-performed_at",
                ],
                name="service_record_latest_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="resourceservicerecord",
            index=models.Index(fields=["kind", "next_due_at"], name="service_record_due_idx"),
        ),
        migrations.AddConstraint(
            model_name="resourceservicerecord",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("next_due_at__isnull", True),
                    ("next_due_at__gt", models.F("performed_at")),
                    _connector="OR",
                ),
                name="service_record_due_after_service",
            ),
        ),
        migrations.AddConstraint(
            model_name="room",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("sku",),
                name="labs_room_active_sku_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="room",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("layout_columns__isnull", True), ("layout_rows__isnull", True)),
                    models.Q(
                        ("layout_columns__gt", 0),
                        ("layout_columns__isnull", False),
                        ("layout_rows__gt", 0),
                        ("layout_rows__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="room_layout_positive_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="room",
            constraint=models.CheckConstraint(
                condition=models.Q(("length_m__isnull", True), ("length_m__gt", 0), _connector="OR"),
                name="room_length_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="room",
            constraint=models.CheckConstraint(
                condition=models.Q(("width_m__isnull", True), ("width_m__gt", 0), _connector="OR"),
                name="room_width_positive",
            ),
        ),
        migrations.AddIndex(
            model_name="equipment",
            index=models.Index(fields=["kind", "deleted_at"], name="equipment_kind_deleted_idx"),
        ),
        migrations.AddIndex(
            model_name="equipment",
            index=models.Index(fields=["kind", "name"], name="equipment_kind_name_idx"),
        ),
        migrations.AddConstraint(
            model_name="equipment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("sku",),
                name="equipment_active_sku_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="roomobservation",
            index=models.Index(fields=["room", "-observed_at"], name="room_observation_time_idx"),
        ),
        migrations.AddConstraint(
            model_name="roomobservation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("temperature_c__isnull", False),
                    ("humidity_percent__isnull", False),
                    ("power_usage_w__isnull", False),
                    _connector="OR",
                ),
                name="room_observation_has_value",
            ),
        ),
        migrations.AddConstraint(
            model_name="roomobservation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("temperature_c__isnull", True),
                    ("temperature_c__gte", Decimal("-273.15")),
                    _connector="OR",
                ),
                name="room_temperature_physical_min",
            ),
        ),
        migrations.AddConstraint(
            model_name="roomobservation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("humidity_percent__isnull", True),
                    models.Q(("humidity_percent__gte", 0), ("humidity_percent__lte", 100)),
                    _connector="OR",
                ),
                name="room_humidity_valid_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="roomslot",
            constraint=models.UniqueConstraint(fields=("room", "row_index", "col_index"), name="uniq_room_row_col"),
        ),
        migrations.AddConstraint(
            model_name="roomslot",
            constraint=models.UniqueConstraint(fields=("room", "slot_code"), name="uniq_room_slot_code"),
        ),
        migrations.AddIndex(
            model_name="roomstatusrecord",
            index=models.Index(fields=["room", "-created", "-id"], name="room_status_latest_idx"),
        ),
        migrations.AddIndex(
            model_name="samplecharacteristic",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="sample_characteristic_name_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddIndex(
            model_name="samplecustomer",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"],
                name="sample_customer_name_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddConstraint(
            model_name="specificationdefinition",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="specification_definition_name_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="productmodelspecification",
            constraint=models.UniqueConstraint(
                fields=("product_model", "definition"),
                name="product_model_specification_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="stationslot",
            constraint=models.UniqueConstraint(
                fields=("station", "position_index"), name="uniq_station_slot_position"
            ),
        ),
        migrations.AddConstraint(
            model_name="stationslot",
            constraint=models.UniqueConstraint(fields=("station", "slot_code"), name="uniq_station_slot_code"),
        ),
        migrations.AddIndex(
            model_name="bench",
            index=models.Index(
                fields=["setup_location", "deleted_at"],
                name="bench_location_deleted_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="bench",
            index=models.Index(fields=["bench_group", "deleted_at"], name="bench_group_deleted_idx"),
        ),
        migrations.AddIndex(
            model_name="bench",
            index=models.Index(fields=["type", "deleted_at"], name="bench_type_deleted_idx"),
        ),
        migrations.AddConstraint(
            model_name="bench",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("sku",),
                name="labs_bench_active_sku_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="stationstatusrecord",
            index=models.Index(fields=["station", "-created", "-id"], name="station_status_latest_idx"),
        ),
        migrations.AddConstraint(
            model_name="station",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("sku",),
                name="labs_station_active_sku_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="station",
            constraint=models.UniqueConstraint(
                condition=models.Q(("slot__isnull", False)),
                fields=("slot",),
                name="station_slot_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="technicaluser",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["username"],
                name="technical_user_username_idx",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="monitoringevent",
            index=models.Index(fields=["computer", "-occurred_at"], name="monitor_computer_time_idx"),
        ),
        migrations.AddIndex(
            model_name="monitoringevent",
            index=models.Index(fields=["action", "-occurred_at"], name="monitor_action_time_idx"),
        ),
        migrations.AddIndex(
            model_name="monitoringevent",
            index=models.Index(
                fields=["subject_type", "subject_id", "-occurred_at"],
                name="monitor_subject_time_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="monitoringevent",
            constraint=models.UniqueConstraint(
                fields=("computer", "agent_id", "event_id"),
                name="unique_monitoring_event_per_agent",
            ),
        ),
        migrations.AddIndex(
            model_name="labsessionlog",
            index=models.Index(
                fields=["computing_equipment", "login_time"],
                name="session_equipment_login_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="labsessionlog",
            index=models.Index(
                fields=["remote_user", "login_time"],
                name="session_remote_user_login_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="labsessionlog",
            index=models.Index(fields=["booking_code"], name="session_booking_code_idx"),
        ),
        migrations.AddIndex(
            model_name="labsessionlog",
            index=models.Index(fields=["host_name", "login_time"], name="session_host_login_idx"),
        ),
        migrations.AddConstraint(
            model_name="labsessionlog",
            constraint=models.UniqueConstraint(
                fields=("computing_equipment", "agent_id", "event_id"),
                name="unique_session_report_per_agent",
            ),
        ),
        migrations.AddConstraint(
            model_name="labsessionlog",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("login_time__isnull", True),
                    ("logout_time__isnull", True),
                    ("logout_time__gt", models.F("login_time")),
                    _connector="OR",
                ),
                name="labsess_valid_period",
            ),
        ),
        migrations.AddConstraint(
            model_name="labsessionlog",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("active_duration_seconds__isnull", True),
                    ("active_duration_seconds__gte", 0),
                    _connector="OR",
                ),
                name="labsess_active_duration_nonnegative",
            ),
        ),
        migrations.AddIndex(
            model_name="computingequipment",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["os_name"],
                name="computing_os_name_idx",
                opclasses=("gin_trgm_ops",),
            ),
        ),
        migrations.AddConstraint(
            model_name="computingactivity",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("status", "offline"), _negated=True),
                    ("offline_at__isnull", False),
                    _connector="OR",
                ),
                name="labs_comp_activity_offline_at_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="computingactivity",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("status", "inactive"), _negated=True),
                    ("inactive_at__isnull", False),
                    _connector="OR",
                ),
                name="labs_comp_activity_inactive_at_required",
            ),
        ),
        migrations.AddIndex(
            model_name="powerequipment",
            index=models.Index(fields=["channels"], name="power_channels_idx"),
        ),
        migrations.AddIndex(
            model_name="powerequipment",
            index=models.Index(fields=["power_rating"], name="power_rating_idx"),
        ),
        migrations.RunPython(seed_purchase_priorities, unseed_purchase_priorities),
    ]
