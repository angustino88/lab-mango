from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.db.models.functions.text


PRIORITIES = (("low", "Low", 10), ("normal", "Normal", 20), ("high", "High", 30), ("urgent", "Urgent", 40))


def seed_purchase_priorities(apps, schema_editor):
    PurchasePriority = apps.get_model("labs", "PurchasePriority")
    manager = PurchasePriority.objects.using(schema_editor.connection.alias)
    for code, name, rank in PRIORITIES:
        manager.get_or_create(code=code, defaults={"name": name, "rank": rank, "is_active": True})


def unseed_purchase_priorities(apps, schema_editor):
    PurchasePriority = apps.get_model("labs", "PurchasePriority")
    PurchasePriority.objects.using(schema_editor.connection.alias).filter(
        code__in=[code for code, _, _ in PRIORITIES],
        purchase_items__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0009_agentidentity_agent_key_algorithm_ed25519_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchasePriority",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=64)),
                ("rank", models.PositiveSmallIntegerField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("-rank", "id")},
        ),
        migrations.AddConstraint(
            model_name="purchasepriority",
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower("name"), name="purchasepriority_name_ci_uniq"),
        ),
        migrations.AddField(model_name="purchase", name="version", field=models.PositiveIntegerField(default=1)),
        migrations.AddField(model_name="purchaseitem", name="purpose", field=models.TextField(blank=True, null=True)),
        migrations.AddField(
            model_name="purchaseitem",
            name="priority",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="purchase_items", to="labs.purchasepriority"),
        ),
        migrations.AddField(model_name="purchaseitem", name="unit", field=models.CharField(blank=True, max_length=32, null=True)),
        migrations.AddField(model_name="purchaseitem", name="version", field=models.PositiveIntegerField(default=1)),
        migrations.CreateModel(
            name="PurchaseIdempotencyRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("credential_ref", models.CharField(max_length=128)),
                ("key", models.CharField(max_length=64)),
                ("method", models.CharField(max_length=8)),
                ("path", models.CharField(max_length=512)),
                ("body_hash", models.CharField(max_length=64)),
                ("state", models.CharField(choices=[("in_progress", "In progress"), ("completed", "Completed")], max_length=16)),
                ("status_code", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("response_body", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
            ],
        ),
        migrations.AddConstraint(
            model_name="purchaseidempotencyrecord",
            constraint=models.UniqueConstraint(fields=("credential_ref", "key"), name="purchase_idempotency_cred_key_uniq"),
        ),
        migrations.AddConstraint(
            model_name="purchaseidempotencyrecord",
            constraint=models.CheckConstraint(
                condition=models.Q(state="in_progress", status_code__isnull=True, response_body__isnull=True)
                | models.Q(state="completed", status_code__isnull=False, response_body__isnull=False),
                name="purchase_idempotency_state_result",
            ),
        ),
        migrations.AddIndex(model_name="purchaseidempotencyrecord", index=models.Index(fields=["expires_at"], name="purchase_idempotency_exp_idx")),
        migrations.CreateModel(
            name="PurchaseAuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("item_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("action", models.CharField(choices=[("create", "Create"), ("update", "Update"), ("delete", "Delete")], max_length=8)),
                ("credential_ref", models.CharField(blank=True, max_length=128, null=True)),
                ("request_id", models.CharField(max_length=128)),
                ("before", models.JSONField(blank=True, null=True)),
                ("after", models.JSONField(blank=True, null=True)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="purchase_audit_events", to=settings.AUTH_USER_MODEL)),
                ("purchase", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="audit_events", to="labs.purchase")),
            ],
            options={"ordering": ("occurred_at", "id")},
        ),
        migrations.AddIndex(model_name="purchaseauditevent", index=models.Index(fields=["purchase", "occurred_at"], name="purchase_audit_time_idx")),
        migrations.RunPython(seed_purchase_priorities, unseed_purchase_priorities),
    ]