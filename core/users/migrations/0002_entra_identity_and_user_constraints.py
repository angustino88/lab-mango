"""Add explicit identities and nonce storage; preserve existing users and classifications."""

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("users", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="user", name="account_type",
            field=models.CharField(
                choices=[("PROVIDER", "Platform Provider"), ("STAFF", "Platform Staff"), ("CUSTOMER", "Customer")],
                default="CUSTOMER", max_length=100, verbose_name="Account Type",
            ),
        ),
        migrations.AlterField(
            model_name="user", name="status",
            field=models.CharField(
                choices=[("ONLINE", "Online"), ("OFFLINE", "Offline")],
                default="OFFLINE", max_length=100, verbose_name="status",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(condition=models.Q(account_type__in=["PROVIDER", "STAFF", "CUSTOMER"]), name="users_user_valid_account_type"),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(condition=models.Q(status__in=["ONLINE", "OFFLINE"]), name="users_user_valid_presence"),
        ),
        migrations.CreateModel(
            name="EntraIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_id", models.UUIDField()),
                ("object_id", models.UUIDField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="entra_identity", to="users.user")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("tenant_id", "object_id"), name="users_entra_unique_subject")]},
        ),
        migrations.CreateModel(
            name="EntraLoginChallenge",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("nonce_digest", models.CharField(max_length=64)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
    ]