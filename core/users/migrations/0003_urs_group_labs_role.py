"""Map URS groups to Labs roles, managed in Django admin."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0002_entra_identity_and_user_constraints")]

    operations = [
        migrations.AddField(
            model_name="ursgroup",
            name="labs_role",
            field=models.CharField(
                blank=True,
                choices=[("admin", "Lab admin"), ("coord", "Lab coordinator"), ("user", "Lab user")],
                default="",
                max_length=10,
                verbose_name="Labs role",
                help_text="Labs role granted to members of the linked Django group. Empty grants no Labs role.",
            ),
        ),
    ]
