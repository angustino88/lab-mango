"""Labs role display names: Lab Administrator, Lab Coordinator, Lab Member (owner decision D2, 2026-11-20).

State only: the stored values (``admin``, ``coord``, ``user``) do not change; no SQL is run.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ursgroup",
            name="labs_role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("admin", "Lab Administrator"),
                    ("coord", "Lab Coordinator"),
                    ("user", "Lab Member"),
                ],
                default="",
                help_text="Labs role granted to members of the linked Django group. Empty grants no Labs role.",
                max_length=10,
                verbose_name="Labs role",
            ),
        ),
    ]
