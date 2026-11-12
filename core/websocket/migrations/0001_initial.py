"""Initial websocket schema: one migration (ADR 005, consolidated 2026-11-12; no deployed database)."""

import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
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
                ("message", models.CharField(default="", max_length=255)),
                (
                    "details",
                    models.CharField(blank=True, default="", max_length=255, null=True),
                ),
                (
                    "message_type",
                    models.CharField(
                        choices=[
                            ("success", "Success"),
                            ("error", "Error"),
                            ("warning", "Warning"),
                            ("info", "Info"),
                            ("announcement", "Announcement"),
                        ],
                        default="info",
                        max_length=255,
                    ),
                ),
                ("expiry_date", models.DateTimeField()),
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
                    "target_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="targeted_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Notification",
                "verbose_name_plural": "Notifications",
                "ordering": ["-created"],
                "indexes": [
                    models.Index(fields=["expiry_date"], name="websocket_n_expiry__bac246_idx"),
                    models.Index(
                        fields=["target_user", "created"],
                        name="websocket_n_target__dbcd3b_idx",
                    ),
                ],
            },
        ),
    ]
