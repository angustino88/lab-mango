"""Append-only role audit log and the access review proxy.

PostgreSQL rejects UPDATE and DELETE on users_roleauditevent, so recorded history cannot be changed.
Retention (if ever needed) requires a reviewed migration that drops and recreates the trigger.
"""

import django.contrib.auth.models
import django.utils.timezone
from django.db import migrations, models


def create_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            CREATE OR REPLACE FUNCTION prevent_role_audit_event_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'RoleAuditEvent records are append-only and cannot be updated or deleted.';
            END;
            $$ LANGUAGE plpgsql;

            DROP TRIGGER IF EXISTS trg_prevent_role_audit_event_update ON users_roleauditevent;
            CREATE TRIGGER trg_prevent_role_audit_event_update
            BEFORE UPDATE ON users_roleauditevent
            FOR EACH ROW EXECUTE FUNCTION prevent_role_audit_event_modification();

            DROP TRIGGER IF EXISTS trg_prevent_role_audit_event_delete ON users_roleauditevent;
            CREATE TRIGGER trg_prevent_role_audit_event_delete
            BEFORE DELETE ON users_roleauditevent
            FOR EACH ROW EXECUTE FUNCTION prevent_role_audit_event_modification();
        """)


def drop_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER IF EXISTS trg_prevent_role_audit_event_update ON users_roleauditevent;
            DROP TRIGGER IF EXISTS trg_prevent_role_audit_event_delete ON users_roleauditevent;
            DROP FUNCTION IF EXISTS prevent_role_audit_event_modification();
        """)


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0005_urs_group_sync_status_and_constraints"),
    ]

    operations = [
        migrations.CreateModel(
            name="PrivilegedUser",
            fields=[],
            options={
                "verbose_name": "privileged user (access review)",
                "verbose_name_plural": "access review: privileged users",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("users.user",),
            managers=[
                ("objects", django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name="RoleAuditEvent",
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
                    "occurred_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now, editable=False),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("urs_group_created", "URS group created"),
                            ("urs_group_changed", "URS group changed"),
                            ("urs_group_deleted", "URS group deleted"),
                            ("user_privileges_changed", "User privileges changed"),
                            ("group_permissions_changed", "Group permissions changed"),
                            ("urs_sync_membership", "URS sync changed group members"),
                            ("user_activity_changed", "User activated or deactivated"),
                        ],
                        editable=False,
                        max_length=40,
                    ),
                ),
                (
                    "actor_id",
                    models.BigIntegerField(blank=True, editable=False, null=True),
                ),
                (
                    "actor_label",
                    models.CharField(
                        editable=False,
                        help_text="Username, or the system job name.",
                        max_length=150,
                    ),
                ),
                (
                    "target_user_id",
                    models.BigIntegerField(blank=True, db_index=True, editable=False, null=True),
                ),
                (
                    "target_label",
                    models.CharField(blank=True, default="", editable=False, max_length=150),
                ),
                (
                    "subject",
                    models.CharField(blank=True, default="", editable=False, max_length=255),
                ),
                ("changes", models.JSONField(blank=True, default=dict, editable=False)),
            ],
            options={
                "ordering": ("-occurred_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["event_type", "occurred_at"],
                        name="users_roleaudit_type_time",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "event_type__in",
                                [
                                    "urs_group_created",
                                    "urs_group_changed",
                                    "urs_group_deleted",
                                    "user_privileges_changed",
                                    "group_permissions_changed",
                                    "urs_sync_membership",
                                    "user_activity_changed",
                                ],
                            )
                        ),
                        name="users_roleaudit_valid_event_type",
                    )
                ],
            },
        ),
        migrations.RunPython(create_trigger, drop_trigger),
    ]
