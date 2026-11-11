"""Record URS sync outcomes and enforce URS group and username invariants in PostgreSQL.

Expand-only. The precheck stops with a clear message, before any constraint is added, when existing
data would violate one; clean the data first (see docs/proposals/user-roles-and-urs-sync.md R2, R11).
"""

import django.db.models.functions.text
from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def check_existing_data(apps, schema_editor):
    user_model = apps.get_model("users", "User")
    urs_group_model = apps.get_model("users", "URSGroup")
    problems = []
    duplicate_usernames = (
        user_model.objects.annotate(lower_username=Lower("username"))
        .values("lower_username")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
        .count()
    )
    if duplicate_usernames:
        problems.append(f"{duplicate_usernames} username(s) exist in more than one letter case")
    duplicate_urs_ids = urs_group_model.objects.values("urs_group_id").annotate(n=Count("id")).filter(n__gt=1).count()
    if duplicate_urs_ids:
        problems.append(f"{duplicate_urs_ids} URS group id(s) are mapped more than once")
    invalid_roles = urs_group_model.objects.exclude(labs_role__in=["", "admin", "coord", "user"]).count()
    if invalid_roles:
        problems.append(f"{invalid_roles} URS group(s) have an unknown labs_role")
    if problems:
        raise RuntimeError("Fix existing data before migrating: " + "; ".join(problems) + ".")


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("users", "0004_drop_jira_integration"),
    ]

    operations = [
        migrations.RunPython(check_existing_data, migrations.RunPython.noop),
        migrations.AddField(
            model_name="ursgroup",
            name="last_sync_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="ursgroup",
            name="last_sync_message",
            field=models.CharField(blank=True, default="", editable=False, max_length=500),
        ),
        migrations.AddField(
            model_name="ursgroup",
            name="last_sync_status",
            field=models.CharField(
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
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("username"),
                name="users_user_username_ci_unique",
            ),
        ),
    ]
