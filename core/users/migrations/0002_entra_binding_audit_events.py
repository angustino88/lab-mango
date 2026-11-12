"""Add Entra link and unlink events to the role audit log (owner decision 2026-11-12, option A)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="roleauditevent",
            name="users_roleaudit_valid_event_type",
        ),
        migrations.AlterField(
            model_name="roleauditevent",
            name="event_type",
            field=models.CharField(
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
        migrations.AddConstraint(
            model_name="roleauditevent",
            constraint=models.CheckConstraint(
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
            ),
        ),
    ]
