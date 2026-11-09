"""Additive delivery ledger only; no historical notification backfill."""

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0004_computing_activity_agent_heartbeat_and_offline_constraint"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="BookingNotification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_id", models.UUIDField()),
                ("dedupe_key", models.CharField(max_length=64, unique=True)),
                ("channel", models.CharField(choices=[("email", "Email"), ("teams", "Teams")], max_length=8)),
                ("kind", models.CharField(max_length=16)),
                ("snapshot", models.JSONField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField()),
                ("available_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("state", models.CharField(default="pending", max_length=12)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("lease_token", models.UUIDField(null=True)),
                ("lease_until", models.DateTimeField(null=True)),
                ("finished_at", models.DateTimeField(null=True)),
                ("outcome", models.CharField(blank=True, default="", max_length=32)),
                (
                    "booking",
                    models.ForeignKey(
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
            ],
            options={
                "indexes": [models.Index(fields=["state", "available_at"], name="booking_notice_ready_idx")],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(channel__in=("email", "teams")), name="booking_notice_channel"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(kind__in=("created", "updated", "start", "inactive")),
                        name="booking_notice_kind",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(state__in=("pending", "leased", "sent", "failed", "skipped", "expired")),
                        name="booking_notice_state",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(state="leased", lease_token__isnull=False, lease_until__isnull=False)
                            | (
                                ~models.Q(state="leased")
                                & models.Q(lease_token__isnull=True, lease_until__isnull=True)
                            )
                        ),
                        name="booking_notice_lease",
                    ),
                ],
            },
        ),
    ]
