from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reference_data", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="ReferenceImportReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("principal", models.CharField(max_length=100)),
                ("operation", models.CharField(max_length=200)),
                ("key", models.CharField(max_length=128)),
                ("body_hash", models.CharField(max_length=64)),
                ("result", models.JSONField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "constraints": [models.UniqueConstraint(
                    fields=("principal", "operation", "key"), name="reference_import_receipt_uniq"
                )],
            },
        ),
    ]