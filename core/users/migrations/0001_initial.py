"""Initial users schema: one migration (ADR 005, consolidated 2026-11-12; no deployed database).

Hand-written: PostgreSQL triggers that make RoleAuditEvent append-only (no UPDATE or DELETE).
Retention, if ever needed, requires a reviewed migration that replaces the trigger.
"""

import django.contrib.auth.models
import django.contrib.auth.validators
import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
import model_utils.fields
from django.conf import settings
from django.db import migrations, models

import core.infrastructure.storage.uploads


def create_role_audit_trigger(apps, schema_editor):
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


def drop_role_audit_trigger(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("""
            DROP TRIGGER IF EXISTS trg_prevent_role_audit_event_update ON users_roleauditevent;
            DROP TRIGGER IF EXISTS trg_prevent_role_audit_event_delete ON users_roleauditevent;
            DROP FUNCTION IF EXISTS prevent_role_audit_event_modification();
        """)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="EntraLoginNonce",
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
                ("nonce_digest", models.CharField(max_length=64, unique=True)),
                ("used_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
            ],
        ),
        migrations.CreateModel(
            name="LabManagementEmail",
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
                    "display_name",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("email", models.EmailField(max_length=254)),
                ("is_active", models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name="User",
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
                ("password", models.CharField(max_length=128, verbose_name="password")),
                (
                    "last_login",
                    models.DateTimeField(blank=True, null=True, verbose_name="last login"),
                ),
                (
                    "is_superuser",
                    models.BooleanField(
                        default=False,
                        help_text="Designates that this user has all permissions without explicitly assigning them.",
                        verbose_name="superuser status",
                    ),
                ),
                (
                    "username",
                    models.CharField(
                        error_messages={"unique": "A user with that username already exists."},
                        help_text="Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.",
                        max_length=150,
                        unique=True,
                        validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
                        verbose_name="username",
                    ),
                ),
                (
                    "first_name",
                    models.CharField(blank=True, max_length=150, verbose_name="first name"),
                ),
                (
                    "last_name",
                    models.CharField(blank=True, max_length=150, verbose_name="last name"),
                ),
                (
                    "email",
                    models.EmailField(blank=True, max_length=254, verbose_name="email address"),
                ),
                (
                    "is_staff",
                    models.BooleanField(
                        default=False,
                        help_text="Designates whether the user can log into this admin site.",
                        verbose_name="staff status",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Designates whether this user should be treated as active. Unselect this instead of deleting accounts.",
                        verbose_name="active",
                    ),
                ),
                (
                    "date_joined",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date joined"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("ONLINE", "Online"), ("OFFLINE", "Offline")],
                        default="OFFLINE",
                        max_length=100,
                        verbose_name="status",
                    ),
                ),
                (
                    "status_changed",
                    model_utils.fields.MonitorField(
                        default=django.utils.timezone.now,
                        monitor="status",
                        verbose_name="status changed",
                    ),
                ),
                (
                    "account_type",
                    models.CharField(
                        choices=[
                            ("PROVIDER", "Platform Provider"),
                            ("STAFF", "Platform Staff"),
                            ("CUSTOMER", "Customer"),
                        ],
                        default="CUSTOMER",
                        max_length=100,
                        verbose_name="Account Type",
                    ),
                ),
                (
                    "name",
                    models.CharField(blank=True, max_length=255, verbose_name="Name of User"),
                ),
                ("display_name", models.CharField(blank=True, max_length=255)),
                ("department", models.CharField(blank=True, max_length=255)),
                ("is_urs_managed", models.BooleanField(default=True)),
                (
                    "avatar",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to=core.infrastructure.storage.uploads.ResourceImageUploadPath("avatars/"),
                    ),
                ),
                (
                    "groups",
                    models.ManyToManyField(
                        blank=True,
                        help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.",
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.group",
                        verbose_name="groups",
                    ),
                ),
                (
                    "user_permissions",
                    models.ManyToManyField(
                        blank=True,
                        help_text="Specific permissions for this user.",
                        related_name="user_set",
                        related_query_name="user",
                        to="auth.permission",
                        verbose_name="user permissions",
                    ),
                ),
            ],
            options={
                "verbose_name": "user",
                "verbose_name_plural": "users",
                "abstract": False,
            },
            managers=[
                ("objects", django.contrib.auth.models.UserManager()),
            ],
        ),
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
            name="EntraIdentity",
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
                ("tenant_id", models.UUIDField()),
                ("object_id", models.UUIDField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="entra_identity",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
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
                            ("entra_identity_bound", "Entra identity linked"),
                            ("entra_identity_unlinked", "Entra identity unlinked"),
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
                                    "entra_identity_bound",
                                    "entra_identity_unlinked",
                                ],
                            )
                        ),
                        name="users_roleaudit_valid_event_type",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="URSGroup",
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
                    "urs_group_name",
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ("urs_group_id", models.PositiveBigIntegerField()),
                ("active", models.BooleanField(default=True)),
                (
                    "labs_role",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("admin", "Lab admin"),
                            ("coord", "Lab coordinator"),
                            ("user", "Lab user"),
                        ],
                        default="",
                        help_text="Labs role granted to members of the linked Django group. Empty grants no Labs role.",
                        max_length=10,
                        verbose_name="Labs role",
                    ),
                ),
                (
                    "last_sync_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "last_sync_status",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("applied", "Applied"),
                            ("blocked", "Blocked by safety check"),
                            ("failed", "Failed"),
                        ],
                        default="",
                        editable=False,
                        max_length=16,
                    ),
                ),
                (
                    "last_sync_message",
                    models.CharField(blank=True, default="", editable=False, max_length=500),
                ),
                (
                    "group",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="auth.group",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("username"),
                name="users_user_username_ci_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(("account_type__in", ["PROVIDER", "STAFF", "CUSTOMER"])),
                name="users_user_valid_account_type",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(("status__in", ["ONLINE", "OFFLINE"])),
                name="users_user_valid_presence",
            ),
        ),
        migrations.AddConstraint(
            model_name="entraidentity",
            constraint=models.UniqueConstraint(fields=("tenant_id", "object_id"), name="users_entra_unique_subject"),
        ),
        migrations.AddConstraint(
            model_name="ursgroup",
            constraint=models.UniqueConstraint(fields=("urs_group_id",), name="users_ursgroup_unique_urs_group_id"),
        ),
        migrations.AddConstraint(
            model_name="ursgroup",
            constraint=models.CheckConstraint(
                condition=models.Q(("labs_role__in", ["", "admin", "coord", "user"])),
                name="users_ursgroup_valid_labs_role",
            ),
        ),
        migrations.AddConstraint(
            model_name="ursgroup",
            constraint=models.CheckConstraint(
                condition=models.Q(("last_sync_status__in", ["", "applied", "blocked", "failed"])),
                name="users_ursgroup_valid_last_sync_status",
            ),
        ),
        migrations.RunPython(create_role_audit_trigger, drop_role_audit_trigger),
    ]
